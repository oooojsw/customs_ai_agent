from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import uuid4

from .errors import AgentApiException
from .models import (
    AgentError,
    AgentEvent,
    AgentOutput,
    CreateRunRequest,
    EventType,
    RunSnapshot,
    RunStatus,
    utc_now,
)


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.PARTIALLY_COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


@dataclass
class _RunRecord:
    snapshot: RunSnapshot
    request_fingerprint: str
    events: list[AgentEvent] = field(default_factory=list)
    cancellation_requested: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class InMemoryRunStore:
    """Process-local Run storage with ordered events and reconnect support."""

    def __init__(self) -> None:
        self._runs: dict[str, _RunRecord] = {}
        self._request_index: dict[tuple[str, str], str] = {}
        self._index_lock = asyncio.Lock()

    async def create(self, request: CreateRunRequest) -> tuple[RunSnapshot, bool]:
        fingerprint = request.model_dump_json(exclude_none=True)
        index_key = (request.session.tenant_id, request.request_id)

        async with self._index_lock:
            existing_run_id = self._request_index.get(index_key)
            if existing_run_id:
                record = self._runs[existing_run_id]
                if record.request_fingerprint != fingerprint:
                    raise AgentApiException(
                        AgentError(
                            error_code="IDEMPOTENCY_CONFLICT",
                            message="request_id 已被不同请求使用",
                            retryable=False,
                            stage="create_run",
                        ),
                        http_status=409,
                    )
                return record.snapshot.model_copy(deep=True), False

            run_id = f"run-{uuid4().hex}"
            snapshot = RunSnapshot(
                run_id=run_id,
                request_id=request.request_id,
                session_id=request.session.session_id,
                user_id=request.session.user_id,
                tenant_id=request.session.tenant_id,
                context_version=request.session.context_version,
            )
            self._runs[run_id] = _RunRecord(
                snapshot=snapshot,
                request_fingerprint=fingerprint,
            )
            self._request_index[index_key] = run_id
            return snapshot.model_copy(deep=True), True

    async def get(self, run_id: str) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            return record.snapshot.model_copy(deep=True)

    async def set_status(self, run_id: str, status: RunStatus) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            snapshot = record.snapshot
            snapshot.status = status
            if status == RunStatus.RUNNING and snapshot.started_at is None:
                snapshot.started_at = utc_now()
            if status in TERMINAL_STATUSES:
                snapshot.completed_at = utc_now()
            record.condition.notify_all()
            return snapshot.model_copy(deep=True)

    async def append_event(
        self,
        run_id: str,
        event_type: EventType,
        data: dict | None = None,
    ) -> AgentEvent:
        record = self._get_record(run_id)
        async with record.condition:
            snapshot = record.snapshot
            if snapshot.status in TERMINAL_STATUSES:
                raise AgentApiException(
                    AgentError(
                        error_code="RUN_ALREADY_TERMINAL",
                        message="终止状态的 Run 不能继续写入事件",
                        stage="append_event",
                    ),
                    http_status=409,
                )

            sequence = snapshot.last_sequence + 1
            event = AgentEvent(
                run_id=run_id,
                request_id=snapshot.request_id,
                session_id=snapshot.session_id,
                sequence=sequence,
                event=event_type,
                data=data or {},
            )
            snapshot.last_sequence = sequence
            record.events.append(event)
            record.condition.notify_all()
            return event.model_copy(deep=True)

    async def complete_with_event(
        self,
        run_id: str,
        *,
        final_answer: str,
        structured_result: dict | None = None,
        outputs: list[AgentOutput] | None = None,
        partial: bool = False,
        context_version: int | None = None,
        usage: dict | None = None,
    ) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            snapshot = record.snapshot
            if snapshot.status in TERMINAL_STATUSES:
                return snapshot.model_copy(deep=True)

            status = (
                RunStatus.PARTIALLY_COMPLETED if partial else RunStatus.COMPLETED
            )
            self._append_event_locked(
                record,
                EventType.AGENT_COMPLETED,
                {
                    "status": status.value,
                    "final_answer": final_answer,
                    "structured_result": structured_result or {},
                    "outputs": [
                        output.model_dump(mode="json", exclude_none=True)
                        for output in outputs or []
                    ],
                    "context_version": context_version,
                    "usage": usage or {},
                },
            )
            snapshot.final_answer = final_answer
            snapshot.structured_result = structured_result or {}
            snapshot.context_version = context_version
            snapshot.usage = dict(usage or {})
            if outputs:
                snapshot.outputs.extend(outputs)
            snapshot.status = status
            snapshot.completed_at = utc_now()
            record.condition.notify_all()
            return snapshot.model_copy(deep=True)

    async def fail_with_event(self, run_id: str, error: AgentError) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            snapshot = record.snapshot
            if snapshot.status in TERMINAL_STATUSES:
                return snapshot.model_copy(deep=True)
            self._append_event_locked(
                record,
                EventType.AGENT_FAILED,
                {
                    "status": RunStatus.FAILED.value,
                    "error": error.model_dump(mode="json", exclude_none=True),
                },
            )
            snapshot.error = error
            snapshot.status = RunStatus.FAILED
            snapshot.completed_at = utc_now()
            record.condition.notify_all()
            return snapshot.model_copy(deep=True)

    async def cancel_with_event(self, run_id: str) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            if record.snapshot.status in TERMINAL_STATUSES:
                return record.snapshot.model_copy(deep=True)
            record.cancellation_requested = True
            self._append_event_locked(
                record,
                EventType.AGENT_CANCELLED,
                {"status": RunStatus.CANCELLED.value},
            )
            record.snapshot.status = RunStatus.CANCELLED
            record.snapshot.completed_at = utc_now()
            record.condition.notify_all()
            return record.snapshot.model_copy(deep=True)

    async def request_cancellation(self, run_id: str) -> RunSnapshot:
        record = self._get_record(run_id)
        async with record.condition:
            if record.snapshot.status not in TERMINAL_STATUSES:
                record.cancellation_requested = True
                record.condition.notify_all()
            return record.snapshot.model_copy(deep=True)

    async def is_cancellation_requested(self, run_id: str) -> bool:
        record = self._get_record(run_id)
        async with record.condition:
            return record.cancellation_requested

    async def add_warning(self, run_id: str, warning: AgentError) -> None:
        record = self._get_record(run_id)
        async with record.condition:
            record.snapshot.warnings.append(warning)
            record.condition.notify_all()

    async def set_usage(self, run_id: str, usage: dict) -> None:
        record = self._get_record(run_id)
        async with record.condition:
            record.snapshot.usage = dict(usage)
            record.condition.notify_all()

    async def set_context_version(
        self, run_id: str, context_version: int | None
    ) -> None:
        record = self._get_record(run_id)
        async with record.condition:
            record.snapshot.context_version = context_version
            record.condition.notify_all()

    async def events_after(self, run_id: str, sequence: int = 0) -> list[AgentEvent]:
        record = self._get_record(run_id)
        async with record.condition:
            return [
                event.model_copy(deep=True)
                for event in record.events
                if event.sequence > sequence
            ]

    async def stream_events(
        self, run_id: str, after_sequence: int = 0
    ) -> AsyncIterator[AgentEvent]:
        record = self._get_record(run_id)
        cursor = after_sequence

        while True:
            async with record.condition:
                pending = [event for event in record.events if event.sequence > cursor]
                if not pending and record.snapshot.status in TERMINAL_STATUSES:
                    return
                if not pending:
                    await record.condition.wait()
                    continue

            for event in pending:
                cursor = event.sequence
                yield event.model_copy(deep=True)

    def _get_record(self, run_id: str) -> _RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise AgentApiException(
                AgentError(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run 不存在: {run_id}",
                    retryable=False,
                    stage="run_lookup",
                ),
                http_status=404,
            ) from exc

    @staticmethod
    def _append_event_locked(
        record: _RunRecord,
        event_type: EventType,
        data: dict,
    ) -> AgentEvent:
        snapshot = record.snapshot
        sequence = snapshot.last_sequence + 1
        event = AgentEvent(
            run_id=snapshot.run_id,
            request_id=snapshot.request_id,
            session_id=snapshot.session_id,
            sequence=sequence,
            event=event_type,
            data=data,
        )
        snapshot.last_sequence = sequence
        record.events.append(event)
        return event
