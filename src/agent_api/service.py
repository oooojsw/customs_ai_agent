from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI

from .adapters import (
    AuditAdapter,
    CapabilityAdapter,
    ChatAdapter,
    ExecutionContext,
)
from .attachments import AttachmentDownloadManager
from .callbacks import CompletionCallbackClient
from .errors import AgentApiException, error_from_exception
from .events import EventEmitter
from src.services.tool_execution_policy import get_default_run_timeout
from .models import (
    AgentError,
    CreateRunRequest,
    CreateRunResponse,
    EventType,
    RunSnapshot,
    RunStatus,
)
from .outputs import OutputManager
from .store import InMemoryRunStore, TERMINAL_STATUSES


class AgentRunService:
    def __init__(
        self,
        store: InMemoryRunStore | None = None,
        adapters: dict[str, CapabilityAdapter] | None = None,
        attachment_manager: AttachmentDownloadManager | None = None,
        output_manager: OutputManager | None = None,
        callback_client: CompletionCallbackClient | None = None,
        heartbeat_seconds: float = 20.0,
        cancel_grace_seconds: float = 10.0,
    ) -> None:
        self.store = store or InMemoryRunStore()
        self.adapters = adapters or {
            "chat": ChatAdapter(),
            "audit": AuditAdapter(),
        }
        self.attachment_manager = attachment_manager
        self.output_manager = output_manager
        self.callback_client = callback_client
        self.heartbeat_seconds = heartbeat_seconds
        self.cancel_grace_seconds = cancel_grace_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._session_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._session_versions: dict[tuple[str, str], int] = {}

    async def create_run(
        self, request: CreateRunRequest, app: FastAPI
    ) -> CreateRunResponse:
        session_key = (
            request.session.tenant_id,
            request.session.session_id,
        )
        current_version = self._session_versions.get(session_key)
        requested_version = request.session.context_version
        if (
            current_version is not None
            and requested_version is not None
            and requested_version < current_version
        ):
            raise AgentApiException(
                AgentError(
                    error_code="SESSION_CONTEXT_CONFLICT",
                    message=(
                        f"会话上下文版本过旧: {requested_version}, "
                        f"当前版本: {current_version}"
                    ),
                    retryable=False,
                    stage="create_run",
                ),
                http_status=409,
            )
        snapshot, created = await self.store.create(request)
        if created:
            task = asyncio.create_task(
                self._execute_run(snapshot.run_id, request, app),
                name=f"agent-run:{snapshot.run_id}",
            )
            self._tasks[snapshot.run_id] = task
            task.add_done_callback(
                lambda _task, run_id=snapshot.run_id: self._tasks.pop(run_id, None)
            )

        return CreateRunResponse(
            run_id=snapshot.run_id,
            request_id=snapshot.request_id,
            status=snapshot.status,
            events_url=f"/api/agent/v1/runs/{snapshot.run_id}/events",
            status_url=f"/api/agent/v1/runs/{snapshot.run_id}",
        )

    async def cancel_run(self, run_id: str) -> RunSnapshot:
        events = await self.store.events_after(run_id, 0)
        customs_case_ids = [
            str(event.data.get("business_case_id") or "")
            for event in events
            if event.event == EventType.CUSTOMS_PROCESS_UPDATED
            and event.data.get("business_case_id")
        ]
        await self.store.request_cancellation(run_id)
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=self.cancel_grace_seconds)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        snapshot = await self.store.cancel_with_event(run_id)
        if customs_case_ids:
            adapter = self.adapters.get("mock_import_declaration")
            workflow = getattr(adapter, "workflow", None)
            if workflow is not None:
                business_case_id = customs_case_ids[-1]
                try:
                    case = await asyncio.to_thread(
                        workflow.get_case,
                        business_case_id,
                    )
                    if case.stage.value not in {
                        "CANCELLED",
                        "CLOSED",
                        "REJECTED",
                    }:
                        await asyncio.to_thread(
                            workflow.cancel,
                            business_case_id,
                        )
                except Exception:
                    # The run is already cancelled; cleanup reconciliation is
                    # best-effort and must not turn cancel into a 500 response.
                    pass
        return snapshot

    async def _execute_run(
        self,
        run_id: str,
        request: CreateRunRequest,
        app: FastAPI,
    ) -> None:
        emitter = EventEmitter(self.store, run_id)
        heartbeat_task: asyncio.Task[None] | None = None
        downloaded_attachments = []
        started_monotonic = time.monotonic()
        session_key = (
            request.session.tenant_id,
            request.session.session_id,
        )
        session_lock = self._session_locks.setdefault(
            session_key, asyncio.Lock()
        )
        lock_acquired = False
        timeout_explicit = "timeout_seconds" in request.options.model_fields_set
        run_timeout_seconds = (
            request.options.timeout_seconds
            if timeout_explicit
            else get_default_run_timeout(request.options.intent)
        )
        timeout_usage = {
            "configured_timeout_seconds": run_timeout_seconds,
            "timeout_source": "request" if timeout_explicit else "intent_default",
        }

        try:
            await session_lock.acquire()
            lock_acquired = True
            await self.store.set_status(run_id, RunStatus.RUNNING)
            await emitter.emit(EventType.AGENT_STARTED, status=RunStatus.RUNNING.value)
            heartbeat_task = asyncio.create_task(self._heartbeat(run_id, emitter))

            if request.attachments:
                if self.attachment_manager is None:
                    raise AgentApiException(
                        AgentError(
                            error_code="ATTACHMENT_SUPPORT_PENDING",
                            message="Agent V1 尚未配置附件下载管理器",
                            retryable=False,
                            stage="attachment_download",
                        ),
                        http_status=501,
                    )
                await emitter.status(
                    "downloading_attachments",
                    f"正在下载 {len(request.attachments)} 个附件",
                )
                downloaded_attachments = await self.attachment_manager.prepare(
                    run_id, request.attachments
                )

            adapter_name = self._select_adapter(request)
            adapter = self.adapters.get(adapter_name)
            if adapter is None:
                raise AgentApiException(
                    AgentError(
                        error_code="CAPABILITY_NOT_AVAILABLE",
                        message=f"能力尚未启用: {adapter_name}",
                        retryable=False,
                        stage="capability_routing",
                    ),
                    http_status=501,
                )

            await self.store.set_usage(run_id, timeout_usage)
            result = await asyncio.wait_for(
                adapter.execute(
                    request,
                    app,
                    emitter,
                    ExecutionContext(
                        downloaded_attachments=downloaded_attachments,
                        output_manager=self.output_manager,
                    ),
                ),
                timeout=run_timeout_seconds,
            )
            await self._emit_missing_outputs(run_id, emitter, result.outputs)
            for warning in result.warnings:
                await self.store.add_warning(run_id, warning)
                await emitter.emit(
                    EventType.WARNING,
                    error=warning.model_dump(mode="json", exclude_none=True),
                )
            next_context_version = (request.session.context_version or 0) + 1
            usage = {
                **timeout_usage,
                "duration_ms": round(
                    (time.monotonic() - started_monotonic) * 1000
                )
            }
            await self.store.complete_with_event(
                run_id,
                final_answer=result.final_answer,
                structured_result=result.structured_result,
                outputs=result.outputs,
                partial=bool(result.warnings),
                context_version=next_context_version,
                usage=usage,
            )
            self._session_versions[session_key] = next_context_version
        except asyncio.CancelledError:
            await emitter.close_active_tools_as_failed("智能体任务已取消")
            await self.store.cancel_with_event(run_id)
        except asyncio.TimeoutError:
            error = AgentError(
                error_code="RUN_TIMEOUT",
                message="智能体任务执行超时",
                retryable=True,
                stage="run_execution",
                details={
                    "intent": request.options.intent,
                    "configured_timeout_seconds": run_timeout_seconds,
                },
            )
            await self._emit_failure(emitter, run_id, error)
        except AgentApiException as exc:
            await self._emit_failure(emitter, run_id, exc.error)
        except Exception as exc:
            error = error_from_exception(exc, stage="run_execution")
            await self._emit_failure(emitter, run_id, error)
        finally:
            snapshot = await self.store.get(run_id)
            if "duration_ms" not in snapshot.usage:
                snapshot.usage["duration_ms"] = round(
                    (time.monotonic() - started_monotonic) * 1000
                )
                await self.store.set_usage(run_id, snapshot.usage)
                snapshot = await self.store.get(run_id)
            if (
                request.callback
                and request.callback.completed_url
                and self.callback_client
            ):
                try:
                    await self.callback_client.notify(
                        str(request.callback.completed_url),
                        snapshot,
                    )
                except Exception as exc:
                    await self.store.add_warning(
                        run_id,
                        AgentError(
                            error_code="CALLBACK_DELIVERY_FAILED",
                            message="任务已完成，但完成回调发送失败",
                            retryable=True,
                            stage="completion_callback",
                            details={"reason": str(exc)},
                        ),
                    )
            if lock_acquired:
                session_lock.release()
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            if self.attachment_manager and request.attachments:
                self.attachment_manager.cleanup(run_id)

    async def _emit_missing_outputs(
        self,
        run_id: str,
        emitter: EventEmitter,
        outputs,
    ) -> None:
        if not outputs:
            return
        events = await self.store.events_after(run_id, 0)
        emitted_ids = {
            str((event.data.get("output") or {}).get("output_id"))
            for event in events
            if event.event == EventType.OUTPUT_CREATED
            and isinstance(event.data.get("output"), dict)
            and (event.data.get("output") or {}).get("output_id")
        }
        for output in outputs:
            if output.output_id in emitted_ids:
                continue
            await emitter.emit(
                EventType.OUTPUT_CREATED,
                output=output.model_dump(mode="json"),
            )

    async def _emit_failure(
        self, emitter: EventEmitter, run_id: str, error: AgentError
    ) -> None:
        snapshot = await self.store.get(run_id)
        if snapshot.status in TERMINAL_STATUSES:
            return
        await emitter.close_active_tools_as_failed(error.message)
        await self.store.fail_with_event(run_id, error)

    async def _heartbeat(self, run_id: str, emitter: EventEmitter) -> None:
        try:
            while True:
                await asyncio.sleep(self.heartbeat_seconds)
                snapshot = await self.store.get(run_id)
                if snapshot.status in TERMINAL_STATUSES:
                    return
                await emitter.emit(EventType.HEARTBEAT, status=snapshot.status.value)
        except AgentApiException:
            return

    @staticmethod
    def _select_adapter(request: CreateRunRequest) -> str:
        if request.options.intent == "full_review":
            return "full_review"
        if request.options.intent == "mock_import_declaration":
            return "mock_import_declaration"
        if request.options.intent == "report":
            return "report"
        if request.options.intent == "declaration_query":
            return "declaration_query"
        if request.options.intent == "regulation_search":
            return "regulation_search"
        if request.options.intent == "batch_audit":
            return "batch_audit"
        if request.options.intent == "ocr":
            return "ocr"
        if request.options.intent == "audit":
            return "audit"
        if request.options.intent == "auto" and request.attachments:
            return "ocr"
        # Business data enriches the general request but must not silently
        # promote it to a fixed workflow. Callers must select full_review.
        return "chat"
