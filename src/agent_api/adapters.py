from __future__ import annotations

import json
import re
import tempfile
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol
from uuid import uuid4

from fastapi import FastAPI

from src.config.loader import settings
from src.core.orchestrator import RiskAnalysisOrchestrator
from src.services.data_client import DataClient
from src.customs_simulator.models import CustomsStage
from src.customs_simulator.service import MockCustomsWorkflowService
from src.customs_simulator.toolset import DeclarationAgentToolset

from .attachments import DownloadedAttachment
from .document_models import DocumentResult, DocumentType
from .errors import AgentApiException
from .events import EventEmitter
from .models import (
    AgentError,
    AgentOutput,
    CreateRunRequest,
    EventType,
    OutputKind,
)
from .outputs import OutputManager
from .report_export import ReportDocumentExporter
from .table_export import TableWorkbookExporter
from .vision import VisionBackend


@dataclass
class AdapterResult:
    final_answer: str
    structured_result: dict[str, Any] = field(default_factory=dict)
    outputs: list[AgentOutput] = field(default_factory=list)
    warnings: list[AgentError] = field(default_factory=list)


@dataclass
class ExecutionContext:
    downloaded_attachments: list[DownloadedAttachment] = field(default_factory=list)
    output_manager: OutputManager | None = None


class CapabilityAdapter(Protocol):
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult: ...


def parse_legacy_sse(event_text: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for block in event_text.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[6:]
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise AgentApiException(
                AgentError(
                    error_code="LEGACY_EVENT_INVALID",
                    message="旧能力返回了无法解析的 SSE 事件",
                    retryable=False,
                    stage="legacy_event_mapping",
                    details={"preview": event_text[:500]},
                )
            ) from exc
        if isinstance(payload, dict):
            parsed.append(payload)
    return parsed


async def iter_legacy_events(stream: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    async for event_text in stream:
        for payload in parse_legacy_sse(event_text):
            yield payload


class ChatAdapter:
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        if context.downloaded_attachments:
            raise AgentApiException(
                AgentError(
                    error_code="CHAT_ATTACHMENT_PROCESSING_PENDING",
                    message="聊天附件将在视觉编排阶段接入，请使用 intent=ocr 先识别",
                    retryable=False,
                    stage="chat",
                ),
                http_status=501,
            )
        agent = getattr(app.state, "agent", None)
        if agent is None:
            raise AgentApiException(
                AgentError(
                    error_code="AGENT_INITIALIZATION_FAILED",
                    message="对话智能体尚未就绪",
                    retryable=True,
                    stage="chat",
                    dependency="customs_chat_agent",
                ),
                http_status=503,
            )

        answer_parts: list[str] = []
        outputs: list[AgentOutput] = []
        warnings: list[AgentError] = []
        active_legacy_tools: set[str] = set()
        latest_customs_case_id: str | None = None
        await emitter.status("chatting", "智能体正在处理请求")

        stream = agent.chat_stream(
            request.message.content,
            request.session.session_id,
            language=request.language,
        )
        async for payload in iter_legacy_events(stream):
            event_type = payload.get("type")
            if event_type == "answer":
                content = str(payload.get("content") or "")
                if content:
                    answer_parts.append(content)
                    await emitter.emit(EventType.MESSAGE_DELTA, content=content)
            elif event_type == "tool_start":
                tool_name = str(payload.get("tool_name") or "unknown_tool")
                if tool_name in active_legacy_tools:
                    continue
                active_legacy_tools.add(tool_name)
                if tool_name == "delegate_to_opencode":
                    await emitter.emit(
                        EventType.SUBAGENT_STARTED,
                        subagent="opencode",
                        tool=tool_name,
                        display_name="OpenCode 子智能体",
                        interaction_kind="subagent",
                        auto_expand=True,
                    )
                await emitter.tool_started(
                    tool_name,
                    str(payload.get("display_name") or tool_name),
                    interaction_kind=str(
                        payload.get("interaction_kind") or "agent_tool"
                    ),
                    auto_expand=payload.get("auto_expand") is True,
                )
            elif event_type == "tool_end":
                tool_name = str(payload.get("tool_name") or "unknown_tool")
                active_legacy_tools.discard(tool_name)
                tool_result = str(payload.get("tool_result") or "")
                parsed_tool_result: dict[str, Any] | None = None
                try:
                    candidate = json.loads(tool_result)
                    if isinstance(candidate, dict):
                        parsed_tool_result = candidate
                except json.JSONDecodeError:
                    parsed_tool_result = None
                case_match = re.search(r"MOCK-CASE-[A-Z0-9]+", tool_result)
                if case_match:
                    latest_customs_case_id = case_match.group(0)
                summary = tool_result[:500] if request.options.include_tool_trace else ""
                await emitter.tool_finished(
                    tool_name,
                    str(payload.get("display_name") or tool_name),
                    summary,
                    status=(
                        "error" if payload.get("status") == "error" else "success"
                    ),
                    interaction_kind=str(
                        payload.get("interaction_kind") or "agent_tool"
                    ),
                    auto_expand=payload.get("auto_expand") is True,
                    customs_reply=payload.get("customs_reply"),
                )
                if (
                    tool_name == "delegate_to_opencode"
                    and parsed_tool_result is not None
                ):
                    await emitter.emit(
                        EventType.SUBAGENT_FINISHED,
                        subagent="opencode",
                        tool=tool_name,
                        task_id=parsed_tool_result.get("task_id"),
                        session_id=parsed_tool_result.get("session_id"),
                        status=parsed_tool_result.get("status"),
                        ok=parsed_tool_result.get("ok") is True,
                        summary=str(parsed_tool_result.get("summary") or "")[:1000],
                        verification=parsed_tool_result.get("verification") or [],
                        error=parsed_tool_result.get("error"),
                    )
                    if parsed_tool_result.get("ok") is not True:
                        error_payload = parsed_tool_result.get("error")
                        message = str(
                            (error_payload or {}).get("message")
                            if isinstance(error_payload, dict)
                            else parsed_tool_result.get("summary")
                            or "子智能体执行失败"
                        )
                        warnings.append(
                            AgentError(
                                error_code=(
                                    str(error_payload.get("error_code"))
                                    if isinstance(error_payload, dict)
                                    and error_payload.get("error_code")
                                    else "SUBAGENT_FAILED"
                                ),
                                message=message[:1000],
                                retryable=(
                                    bool(error_payload.get("retryable"))
                                    if isinstance(error_payload, dict)
                                    else True
                                ),
                                stage="subagent",
                                details={
                                    "subagent": parsed_tool_result.get("subagent"),
                                    "task_id": parsed_tool_result.get("task_id"),
                                    "session_id": parsed_tool_result.get("session_id"),
                                },
                            )
                        )
                    elif parsed_tool_result.get("ok") is True:
                        created_outputs, created_warnings = (
                            await self._publish_subagent_artifacts(
                                parsed_tool_result,
                                request,
                                context,
                                emitter,
                            )
                        )
                        outputs.extend(created_outputs)
                        warnings.extend(created_warnings)
            elif event_type == "model_end":
                await emitter.emit(
                    EventType.STATUS_CHANGED,
                    phase="model_turn_completed",
                    diagnostics={
                        "finish_reason": payload.get("finish_reason"),
                        "tool_call_count": payload.get("tool_call_count", 0),
                        "tool_call_names": payload.get("tool_call_names", []),
                        "invalid_tool_call_count": payload.get(
                            "invalid_tool_call_count", 0
                        ),
                        "content_tail": payload.get("content_tail", ""),
                        "graph_step": payload.get("graph_step"),
                        "graph_node": payload.get("graph_node"),
                    },
                )
            elif event_type == "error":
                raise AgentApiException(
                    AgentError(
                        error_code="AGENT_EXECUTION_FAILED",
                        message=str(payload.get("content") or "智能体执行失败"),
                        retryable=True,
                        stage="chat",
                    )
                )
            # The legacy `thinking` event is intentionally not exposed. It may
            # contain private model reasoning rather than user-facing progress.

        final_answer = "".join(answer_parts).strip()
        if not final_answer:
            raise AgentApiException(
                AgentError(
                    error_code="AGENT_EMPTY_RESPONSE",
                    message="智能体未返回有效回答",
                    retryable=True,
                    stage="chat",
                )
            )
        structured_result: dict[str, Any] = {}
        if latest_customs_case_id:
            workflow = getattr(agent, "customs_workflow", None)
            if workflow is not None:
                case = await asyncio.to_thread(
                    workflow.get_case, latest_customs_case_id
                )
                declaration = case.current_declaration.declaration
                verified_summary = {
                    "business_case_id": case.business_case_id,
                    "case_source": case.case_source,
                    "stage": case.stage.value,
                    "input_declaration_fingerprint": (
                        case.input_declaration_fingerprint
                    ),
                    "goods": [
                        {
                            "name": item.name,
                            "hs_code": item.hs_code,
                            "quantity": item.quantity,
                            "quantity_unit": item.quantity_unit,
                            "unit_price": item.unit_price,
                            "total_price": item.total_price,
                            "currency": item.currency,
                            "origin_country": item.origin_country,
                        }
                        for item in declaration.goods
                    ],
                    "findings": [
                        finding.model_dump(mode="json")
                        for finding in case.findings
                    ],
                    "mock": True,
                }
                goods_text = "；".join(
                    f"{item.name} / HS {item.hs_code} / "
                    f"{item.quantity:g}{item.quantity_unit} / "
                    f"{item.total_price:g} {item.currency}"
                    for item in declaration.goods
                )
                verification_text = (
                    "\n\n【系统核验】"
                    f"案件 {case.business_case_id}；来源 {case.case_source}；"
                    f"当前状态 {case.stage.value}；实际持久化商品：{goods_text}。"
                )
                answer_parts.append(verification_text)
                final_answer += verification_text
                structured_result["verified_customs_case"] = verified_summary
                await emitter.emit(
                    EventType.MESSAGE_DELTA,
                    content=verification_text,
                )
        return AdapterResult(
            final_answer=final_answer,
            structured_result=structured_result,
            outputs=outputs,
            warnings=warnings,
        )

    async def _publish_subagent_artifacts(
        self,
        tool_result: dict[str, Any],
        request: CreateRunRequest,
        context: ExecutionContext,
        emitter: EventEmitter,
    ) -> tuple[list[AgentOutput], list[AgentError]]:
        if context.output_manager is None:
            return [], []
        outputs: list[AgentOutput] = []
        warnings: list[AgentError] = []
        project_root = Path(settings.BASE_DIR).resolve()
        data_root = (project_root / "data").resolve()
        for artifact in tool_result.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            rel_path = str(artifact.get("path") or "").replace("\\", "/").lstrip("./")
            if not rel_path:
                continue
            source_path = (project_root / rel_path).resolve()
            try:
                source_path.relative_to(data_root)
            except ValueError:
                warnings.append(
                    AgentError(
                        error_code="SUBAGENT_ARTIFACT_PATH_REJECTED",
                        message=f"子智能体产物路径越界，已拒绝发布: {rel_path}",
                        retryable=False,
                        stage="subagent_artifact_publish",
                    )
                )
                continue
            if not source_path.is_file():
                warnings.append(
                    AgentError(
                        error_code="SUBAGENT_ARTIFACT_MISSING",
                        message=f"子智能体产物不存在，无法发布: {rel_path}",
                        retryable=True,
                        stage="subagent_artifact_publish",
                    )
                )
                continue
            ext = source_path.suffix.lower().lstrip(".") or "bin"
            kind = self._output_kind_for_extension(ext)
            output, warning = await context.output_manager.publish_file(
                source_path=source_path,
                tenant_id=request.session.tenant_id,
                kind=kind,
                format=ext,
                name=source_path.name,
                mime_type=artifact.get("mime_type"),
                source_tool="delegate_to_opencode",
                metadata={
                    "source": "subagent",
                    "subagent": tool_result.get("subagent"),
                    "task_id": tool_result.get("task_id"),
                    "session_id": tool_result.get("session_id"),
                    "original_path": rel_path,
                    "sha256_reported": artifact.get("sha256"),
                },
                prefer_platform=request.options.output_file_policy
                == "upload_to_platform",
            )
            outputs.append(output)
            await emitter.emit(
                EventType.OUTPUT_CREATED,
                output=output.model_dump(mode="json"),
            )
            if warning:
                warnings.append(warning)
        return outputs, warnings

    @staticmethod
    def _output_kind_for_extension(ext: str) -> OutputKind:
        ext = ext.lower()
        if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
            return OutputKind.IMAGE
        if ext in {"xlsx", "xls", "csv", "tsv"}:
            return OutputKind.SPREADSHEET
        if ext in {"zip", "rar", "7z"}:
            return OutputKind.ARCHIVE
        if ext in {"json", "yaml", "yml"}:
            return OutputKind.STRUCTURED_DATA
        return OutputKind.DOCUMENT


class AuditAdapter:
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        if context.downloaded_attachments:
            raise AgentApiException(
                AgentError(
                    error_code="AUDIT_ATTACHMENT_PROCESSING_PENDING",
                    message="图片审单串联将在视觉编排阶段接入，请先执行 OCR",
                    retryable=False,
                    stage="audit",
                ),
                http_status=501,
            )
        raw_data = str(
            request.business_context.get("declaration_text")
            or request.message.content
        ).strip()
        if len(raw_data) < 5:
            raise AgentApiException(
                AgentError(
                    error_code="INVALID_DECLARATION_DATA",
                    message="报关数据太短，无法分析",
                    retryable=False,
                    stage="audit",
                ),
                http_status=422,
            )

        llm_config = getattr(app.state, "llm_config", None)
        orchestrator = RiskAnalysisOrchestrator(llm_config=llm_config)
        findings: list[dict[str, Any]] = []
        final_answer = ""

        async for payload in iter_legacy_events(
            orchestrator.analyze_stream(raw_data, language=request.language)
        ):
            event_type = payload.get("type")
            if event_type == "init":
                await emitter.status(
                    "auditing",
                    f"开始执行 {payload.get('total_steps', 0)} 项审单规则",
                )
            elif event_type == "step_start":
                rule_id = str(payload.get("rule_id") or "unknown_rule")
                await emitter.tool_started(rule_id, str(payload.get("loading_text") or rule_id))
            elif event_type == "step_result":
                finding = {
                    "rule_id": payload.get("rule_id"),
                    "status": payload.get("status"),
                    "message": payload.get("message"),
                }
                findings.append(finding)
                await emitter.tool_finished(
                    str(payload.get("rule_id") or "unknown_rule"),
                    str(payload.get("rule_id") or "unknown_rule"),
                    str(payload.get("message") or "")[:500],
                )
            elif event_type == "complete":
                final_answer = str(payload.get("summary") or "")

        if not final_answer:
            raise AgentApiException(
                AgentError(
                    error_code="AUDIT_ENGINE_FAILED",
                    message="审单引擎未返回最终结论",
                    retryable=True,
                    stage="audit",
                )
            )

        await emitter.emit(EventType.MESSAGE_DELTA, content=final_answer)
        return AdapterResult(
            final_answer=final_answer,
            structured_result={"findings": findings},
        )


class MockImportDeclarationAdapter:
    """Run the persistent customs declaration simulation through Agent V1."""

    def __init__(self, workflow: MockCustomsWorkflowService):
        self.workflow = workflow
        self.toolset = DeclarationAgentToolset(workflow)

    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        mock_case_id = str(
            request.business_context.get("mock_case_id") or "normal_release"
        ).strip()
        configured_step_delay = request.business_context.get("step_delay_ms")
        step_delay_ms = min(
            max(
                int(
                    800
                    if configured_step_delay is None
                    else configured_step_delay
                ),
                0,
            ),
            5000,
        )
        configured_max_amendments = request.business_context.get(
            "max_amendments"
        )
        max_amendments = min(
            max(
                int(
                    3
                    if configured_max_amendments is None
                    else configured_max_amendments
                ),
                0,
            ),
            10,
        )
        configured_max_supplements = request.business_context.get(
            "max_supplements"
        )
        max_supplements = min(
            max(
                int(
                    3
                    if configured_max_supplements is None
                    else configured_max_supplements
                ),
                0,
            ),
            10,
        )
        amendment_count = 0
        supplement_count = 0
        await emitter.status("creating_case", "正在创建一般贸易进口模拟业务")
        declaration = request.business_context.get("declaration")
        if isinstance(declaration, dict):
            case = await asyncio.to_thread(
                self.workflow.create_case_from_data,
                declaration,
                list(request.business_context.get("documents") or []),
                request.session.tenant_id,
                request.session.user_id,
                request.session.session_id,
                request.request_id,
                dict(request.business_context.get("workflow_config") or {}),
            )
        else:
            case = await asyncio.to_thread(
                self.workflow.create_case,
                mock_case_id,
                request.session.tenant_id,
                request.session.user_id,
                request.session.session_id,
                request.request_id,
            )
        await self._emit_process(emitter, case)

        try:
            for _ in range(30):
                if case.stage in {
                    CustomsStage.CLOSED,
                    CustomsStage.REJECTED,
                    CustomsStage.CANCELLED,
                }:
                    break
                if (
                    case.stage == CustomsStage.DOCUMENTS_READY
                    and "goods_classification" not in case.analysis_results
                ):
                    case = await self._run_predeclaration_analysis(
                        emitter, case
                    )
                if step_delay_ms:
                    await asyncio.sleep(step_delay_ms / 1000)
                customs_interaction = self._next_step_is_customs(case.stage)
                operation = self._operation_for_stage(case.stage)
                if case.stage == CustomsStage.RETURNED:
                    amendment_count += 1
                    if amendment_count > max_amendments:
                        raise AgentApiException(
                            AgentError(
                                error_code="CUSTOMS_MAX_AMENDMENTS_EXCEEDED",
                                message="模拟报关流程超过最大改单次数",
                                retryable=False,
                                stage="amending_declaration",
                                details={
                                    "business_case_id": case.business_case_id,
                                    "max_amendments": max_amendments,
                                    "mock": True,
                                },
                            )
                        )
                if case.stage == CustomsStage.SUPPLEMENT_REQUIRED:
                    supplement_count += 1
                    if supplement_count > max_supplements:
                        raise AgentApiException(
                            AgentError(
                                error_code="CUSTOMS_MAX_SUPPLEMENTS_EXCEEDED",
                                message="模拟报关流程超过最大补件次数",
                                retryable=False,
                                stage="supplying_materials",
                                details={
                                    "business_case_id": case.business_case_id,
                                    "max_supplements": max_supplements,
                                    "mock": True,
                                },
                            )
                        )
                await emitter.tool_started(
                    operation,
                    self._display_stage(case.stage),
                    interaction_kind=(
                        "customs_authority"
                        if customs_interaction
                        else "declaration_operation"
                    ),
                )
                receipt_count = len(case.receipts)
                await asyncio.to_thread(
                    getattr(self.toolset, operation),
                    {"business_case_id": case.business_case_id},
                )
                case = await asyncio.to_thread(
                    self.workflow.get_case, case.business_case_id
                )
                new_receipt = (
                    case.receipts[-1]
                    if len(case.receipts) > receipt_count
                    else None
                )
                customs_reply = self._format_customs_reply(
                    case, new_receipt
                ) if customs_interaction else ""
                await emitter.tool_finished(
                    operation,
                    self._display_stage(case.stage),
                    customs_reply or case.timeline[-1].summary,
                    interaction_kind=(
                        "customs_authority"
                        if customs_interaction
                        else "declaration_operation"
                    ),
                    auto_expand=customs_interaction,
                    customs_reply=customs_reply or None,
                )
                await self._emit_process(emitter, case)
                await asyncio.sleep(0)
            else:
                raise AgentApiException(
                    AgentError(
                        error_code="CUSTOMS_WORKFLOW_MAX_STEPS_EXCEEDED",
                        message="模拟报关流程超过最大步骤数",
                        retryable=False,
                        stage="mock_import_declaration",
                    )
                )
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self.workflow.cancel,
                case.business_case_id,
            )
            raise

        final_answer = self._final_answer(case)
        outputs = self._build_outputs(case)
        for output in outputs:
            await emitter.emit(
                EventType.OUTPUT_CREATED,
                output=output.model_dump(mode="json"),
            )
        await emitter.emit(EventType.MESSAGE_DELTA, content=final_answer)
        return AdapterResult(
            final_answer=final_answer,
            structured_result={
                "mode": "mock_import_declaration",
                "mock": True,
                "business_case_id": case.business_case_id,
                "customs_stage": case.stage.value,
                "case_version": case.case_version,
                "declaration_version_count": len(case.declaration_versions),
                "amendment_count": amendment_count,
                "supplement_count": supplement_count,
                "analysis_results": case.analysis_results,
                "authority_decisions": [
                    event.data
                    for event in case.timeline
                    if event.event_type == "customs_decision"
                ],
                "receipts": [
                    receipt.model_dump(mode="json")
                    for receipt in case.receipts
                ],
                "tax_assessment": (
                    case.tax_assessment.model_dump(mode="json")
                    if case.tax_assessment
                    else None
                ),
                "inspection": (
                    case.inspection.model_dump(mode="json")
                    if case.inspection
                    else None
                ),
                "timeline": [
                    event.model_dump(mode="json") for event in case.timeline
                ],
            },
            outputs=outputs,
        )

    @staticmethod
    async def _emit_process(
        emitter: EventEmitter, case
    ) -> None:
        latest = case.timeline[-1]
        progress = MockImportDeclarationAdapter._stage_progress(case.stage)
        await emitter.emit(
            EventType.CUSTOMS_PROCESS_UPDATED,
            business_case_id=case.business_case_id,
            customs_case_id=case.customs_case_id or case.business_case_id,
            stage=case.stage.value,
            stage_label=MockImportDeclarationAdapter._display_stage(case.stage),
            stage_order=progress["stage_order"],
            total_stages=progress["total_stages"],
            progress_percent=progress["progress_percent"],
            is_terminal=MockImportDeclarationAdapter._is_terminal_stage(case.stage),
            progress_index=len(case.timeline),
            process_event_type=latest.event_type,
            summary=latest.summary,
            receipt_summary=(
                case.receipts[-1].message if case.receipts else latest.summary
            ),
            allowed_actions=case.allowed_actions,
            receipt=(
                case.receipts[-1].model_dump(mode="json")
                if case.receipts
                else None
            ),
            risk_items=MockImportDeclarationAdapter._risk_items(case),
            mock=True,
        )
        await emitter.status(
            MockImportDeclarationAdapter._phase(case.stage),
            latest.summary,
        )

    async def _run_predeclaration_analysis(self, emitter, case):
        operations = [
            (
                "normalize_declaration_data",
                "标准化申报数据",
                "loading_documents",
            ),
            ("classify_goods", "大模型商品归类", "classifying_goods"),
            (
                "validate_declaration_elements",
                "校验申报要素",
                "validating_documents",
            ),
            (
                "check_regulatory_requirements",
                "检查监管条件",
                "checking_regulations",
            ),
            ("estimate_customs_tax", "估算进口税费", "estimating_tax"),
            ("pre_audit_declaration", "执行申报前审单", "pre_auditing"),
        ]
        for operation, display_name, phase in operations:
            await emitter.status(phase, display_name)
            await emitter.tool_started(
                operation,
                display_name,
                interaction_kind="declaration_operation",
            )
            result = await asyncio.to_thread(
                getattr(self.toolset, operation),
                {"business_case_id": case.business_case_id},
            )
            summary = json.dumps(result, ensure_ascii=False)
            await emitter.tool_finished(
                operation,
                display_name,
                summary[:1000],
                interaction_kind="declaration_operation",
            )
            case = await asyncio.to_thread(
                self.workflow.get_case, case.business_case_id
            )
            await asyncio.sleep(0)
        return case

    @staticmethod
    def _phase(stage: CustomsStage) -> str:
        mapping = {
            CustomsStage.DRAFT: "creating_case",
            CustomsStage.DOCUMENTS_READY: "loading_documents",
            CustomsStage.PRECHECK_PASSED: "pre_auditing",
            CustomsStage.READY_TO_SUBMIT: "building_declaration",
            CustomsStage.SUBMITTED: "submitting_customs",
            CustomsStage.ACCEPTED: "waiting_customs_receipt",
            CustomsStage.UNDER_REVIEW: "waiting_customs_review",
            CustomsStage.RETURNED: "amending_declaration",
            CustomsStage.SUPPLEMENT_REQUIRED: "supplying_materials",
            CustomsStage.PRICE_QUERY: "responding_price_query",
            CustomsStage.INSPECTION_REQUIRED: "waiting_inspection",
            CustomsStage.INSPECTION_SCHEDULED: "waiting_inspection",
            CustomsStage.INSPECTION_COMPLETED: "inspection_completed",
            CustomsStage.TAX_ASSESSED: "estimating_tax",
            CustomsStage.PAYMENT_PENDING: "paying_tax",
            CustomsStage.TAX_PAID: "waiting_release",
            CustomsStage.RELEASED: "released",
            CustomsStage.PICKED_UP: "closing_case",
            CustomsStage.CLOSED: "closed",
            CustomsStage.REJECTED: "rejected",
        }
        return mapping.get(stage, stage.value.lower())

    @staticmethod
    def _display_stage(stage: CustomsStage) -> str:
        labels = {
            CustomsStage.DRAFT: "创建业务",
            CustomsStage.DOCUMENTS_READY: "单证就绪",
            CustomsStage.PRECHECK_PASSED: "申报前检查通过",
            CustomsStage.READY_TO_SUBMIT: "生成申报草稿",
            CustomsStage.SUBMITTED: "提交海关模拟窗口",
            CustomsStage.ACCEPTED: "海关受理",
            CustomsStage.RETURNED: "海关退单",
            CustomsStage.SUPPLEMENT_REQUIRED: "补充材料",
            CustomsStage.UNDER_REVIEW: "海关审单",
            CustomsStage.PRICE_QUERY: "价格质疑",
            CustomsStage.LICENSE_REVIEW: "许可证核验",
            CustomsStage.INSPECTION_REQUIRED: "要求查验",
            CustomsStage.INSPECTION_SCHEDULED: "安排查验",
            CustomsStage.INSPECTION_COMPLETED: "查验完成",
            CustomsStage.TAX_ASSESSED: "税费核定",
            CustomsStage.PAYMENT_PENDING: "等待缴税",
            CustomsStage.TAX_PAID: "税款已缴",
            CustomsStage.RELEASED: "海关放行",
            CustomsStage.PICKED_UP: "货物提取",
            CustomsStage.CLOSED: "结关归档",
            CustomsStage.REJECTED: "拒绝放行",
            CustomsStage.CANCELLED: "流程取消",
        }
        return labels.get(stage, stage.value)

    @staticmethod
    def _is_terminal_stage(stage: CustomsStage) -> bool:
        return stage in {
            CustomsStage.CLOSED,
            CustomsStage.REJECTED,
            CustomsStage.CANCELLED,
        }

    @staticmethod
    def _stage_sequence() -> list[CustomsStage]:
        return [
            CustomsStage.DRAFT,
            CustomsStage.DOCUMENTS_READY,
            CustomsStage.PRECHECK_PASSED,
            CustomsStage.READY_TO_SUBMIT,
            CustomsStage.SUBMITTED,
            CustomsStage.ACCEPTED,
            CustomsStage.UNDER_REVIEW,
            CustomsStage.PRICE_QUERY,
            CustomsStage.LICENSE_REVIEW,
            CustomsStage.INSPECTION_REQUIRED,
            CustomsStage.INSPECTION_SCHEDULED,
            CustomsStage.INSPECTION_COMPLETED,
            CustomsStage.TAX_ASSESSED,
            CustomsStage.PAYMENT_PENDING,
            CustomsStage.TAX_PAID,
            CustomsStage.RELEASED,
            CustomsStage.PICKED_UP,
            CustomsStage.CLOSED,
        ]

    @staticmethod
    def _stage_progress(stage: CustomsStage) -> dict[str, int]:
        sequence = MockImportDeclarationAdapter._stage_sequence()
        total = len(sequence)
        order_by_stage = {stage_item: index + 1 for index, stage_item in enumerate(sequence)}
        if stage == CustomsStage.REJECTED:
            stage_order = total
        elif stage == CustomsStage.CANCELLED:
            stage_order = max(1, min(total, order_by_stage.get(stage, 1)))
        else:
            stage_order = order_by_stage.get(stage, 1)
        return {
            "stage_order": stage_order,
            "total_stages": total,
            "progress_percent": round(stage_order / total * 100),
        }

    @staticmethod
    def _risk_items(case) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for finding in case.findings:
            code = str(getattr(finding, "code", "") or "RISK_FINDING")
            message = str(getattr(finding, "message", "") or code)
            key = (code, message)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "code": code,
                    "severity": str(getattr(finding, "severity", "") or "medium"),
                    "stage": str(getattr(finding, "stage", "") or case.stage.value),
                    "message": message,
                    "blocking": bool(getattr(finding, "blocking", False)),
                    "source": "rule_finding",
                }
            )

        for receipt in case.receipts:
            for reason_code in receipt.reason_codes:
                code = str(reason_code or "").strip()
                if not code:
                    continue
                message = receipt.message or code
                key = (code, message)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "code": code,
                        "severity": "medium",
                        "stage": case.stage.value,
                        "message": message,
                        "blocking": receipt.decision in {"REJECTED", "RETURNED"},
                        "source": "customs_receipt",
                        "receipt_id": receipt.receipt_id,
                    }
                )

        stage_risks = {
            CustomsStage.RETURNED: ("CUSTOMS_RETURNED", "海关退单，需修改后重报"),
            CustomsStage.SUPPLEMENT_REQUIRED: ("SUPPLEMENT_REQUIRED", "海关要求补充材料"),
            CustomsStage.PRICE_QUERY: ("PRICE_QUERY", "海关发起价格质疑"),
            CustomsStage.LICENSE_REVIEW: ("LICENSE_REVIEW", "海关进入许可证核验"),
            CustomsStage.INSPECTION_REQUIRED: ("INSPECTION_REQUIRED", "海关要求查验"),
            CustomsStage.REJECTED: ("CUSTOMS_REJECTED", "海关拒绝放行"),
        }
        if case.stage in stage_risks:
            code, message = stage_risks[case.stage]
            key = (code, message)
            if key not in seen:
                items.append(
                    {
                        "code": code,
                        "severity": "high",
                        "stage": case.stage.value,
                        "message": message,
                        "blocking": case.stage == CustomsStage.REJECTED,
                        "source": "workflow_stage",
                    }
                )
        return items

    @staticmethod
    def _next_step_is_customs(stage: CustomsStage) -> bool:
        return stage in {
            CustomsStage.SUBMITTED,
            CustomsStage.ACCEPTED,
            CustomsStage.UNDER_REVIEW,
            CustomsStage.PRICE_QUERY,
            CustomsStage.LICENSE_REVIEW,
            CustomsStage.INSPECTION_SCHEDULED,
            CustomsStage.INSPECTION_COMPLETED,
            CustomsStage.TAX_ASSESSED,
            CustomsStage.TAX_PAID,
            CustomsStage.PICKED_UP,
        }

    @staticmethod
    def _operation_for_stage(stage: CustomsStage) -> str:
        operations = {
            CustomsStage.DRAFT: "load_mock_documents",
            CustomsStage.DOCUMENTS_READY: "validate_document_set",
            CustomsStage.PRECHECK_PASSED: "build_declaration_draft",
            CustomsStage.READY_TO_SUBMIT: "submit_customs_declaration",
            CustomsStage.SUBMITTED: "process_customs_acceptance",
            CustomsStage.RETURNED: "amend_declaration",
            CustomsStage.SUPPLEMENT_REQUIRED: "submit_supplementary_materials",
            CustomsStage.ACCEPTED: "start_customs_review",
            CustomsStage.UNDER_REVIEW: "process_customs_review",
            CustomsStage.PRICE_QUERY: "respond_to_price_query",
            CustomsStage.LICENSE_REVIEW: "confirm_license_information",
            CustomsStage.INSPECTION_REQUIRED: "schedule_mock_inspection",
            CustomsStage.INSPECTION_SCHEDULED: "submit_inspection_result",
            CustomsStage.INSPECTION_COMPLETED: "assess_mock_customs_tax",
            CustomsStage.TAX_ASSESSED: "issue_mock_tax_bill",
            CustomsStage.PAYMENT_PENDING: "pay_mock_customs_tax",
            CustomsStage.TAX_PAID: "release_mock_goods",
            CustomsStage.RELEASED: "confirm_mock_pickup",
            CustomsStage.PICKED_UP: "close_import_case",
        }
        try:
            return operations[stage]
        except KeyError as exc:
            raise ValueError(
                f"CUSTOMS_ACTION_NOT_ALLOWED: {stage.value}"
            ) from exc

    @staticmethod
    def _format_customs_reply(case, receipt) -> str:
        if receipt:
            reason_text = (
                "、".join(receipt.reason_codes)
                if receipt.reason_codes
                else "无"
            )
            actions = [
                str(item.get("action") or "")
                for item in receipt.required_actions
                if item.get("action")
            ]
            action_text = "、".join(actions) if actions else "无"
            return (
                f"【海关模拟回复】\n"
                f"窗口：{receipt.window}\n"
                f"决定：{receipt.decision}\n"
                f"理由码：{reason_text}\n"
                f"回复：{receipt.message}\n"
                f"下一步要求：{action_text}\n"
                f"智能体模型：{receipt.metadata.get('model_version') or '程序窗口'}\n"
                f"模型降级：{'是' if receipt.metadata.get('fallback_used') else '否'}\n"
                f"回执编号：{receipt.receipt_id}"
            )
        latest = case.timeline[-1]
        return (
            "【海关模拟回复】\n"
            f"当前阶段：{MockImportDeclarationAdapter._display_stage(case.stage)}\n"
            f"回复：{latest.summary}\n"
            f"允许动作：{'、'.join(case.allowed_actions) or '无'}"
        )

    @staticmethod
    def _build_outputs(case) -> list[AgentOutput]:
        outputs = [
            AgentOutput(
                output_id=f"out-{uuid4().hex}",
                kind=OutputKind.ARCHIVE,
                format="json",
                name="模拟报关案件归档",
                source_tool="generate_case_archive",
                data=case.model_dump(mode="json"),
                metadata={
                    "business_case_id": case.business_case_id,
                    "mock": True,
                },
            ),
            AgentOutput(
                output_id=f"out-{uuid4().hex}",
                kind=OutputKind.STRUCTURED_DATA,
                format="json",
                name="海关模拟回执集合",
                source_tool="query_customs_case",
                data=[
                    receipt.model_dump(mode="json")
                    for receipt in case.receipts
                ],
                metadata={
                    "business_case_id": case.business_case_id,
                    "mock": True,
                },
            ),
            AgentOutput(
                output_id=f"out-{uuid4().hex}",
                kind=OutputKind.STRUCTURED_DATA,
                format="json",
                name="模拟报关完整时间线",
                source_tool="get_customs_process_timeline",
                data=[
                    event.model_dump(mode="json") for event in case.timeline
                ],
                metadata={
                    "business_case_id": case.business_case_id,
                    "mock": True,
                },
            ),
        ]
        if case.tax_assessment:
            outputs.append(
                AgentOutput(
                    output_id=f"out-{uuid4().hex}",
                    kind=OutputKind.STRUCTURED_DATA,
                    format="json",
                    name="模拟税单",
                    source_tool="issue_mock_tax_bill",
                    data=case.tax_assessment.model_dump(mode="json"),
                    metadata={
                        "business_case_id": case.business_case_id,
                        "mock": True,
                    },
                )
            )
        if case.inspection:
            outputs.append(
                AgentOutput(
                    output_id=f"out-{uuid4().hex}",
                    kind=OutputKind.VALIDATION_REPORT,
                    format="json",
                    name="模拟查验记录",
                    source_tool="submit_inspection_result",
                    data=case.inspection.model_dump(mode="json"),
                    metadata={
                        "business_case_id": case.business_case_id,
                        "mock": True,
                    },
                )
            )
        return outputs

    @staticmethod
    def _final_answer(case) -> str:
        tax_text = ""
        if case.tax_assessment:
            tax_text = f"模拟税费 {case.tax_assessment.total_tax:.2f} CNY；"
        return (
            f"一般贸易进口模拟流程已完成。业务编号：{case.business_case_id}；"
            f"最终状态：{MockImportDeclarationAdapter._display_stage(case.stage)}；"
            f"申报版本 {len(case.declaration_versions)} 个；"
            f"海关回执 {len(case.receipts)} 份；{tax_text}"
            "以上均为 Mock 演示结果。"
        )


class DeclarationQueryAdapter:
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        entry_id = str(request.business_context.get("entry_id") or "").strip()
        if not entry_id:
            raise AgentApiException(
                AgentError(
                    error_code="DECLARATION_ID_REQUIRED",
                    message="报关数据查询需要 business_context.entry_id",
                    retryable=False,
                    stage="declaration_query",
                ),
                http_status=422,
            )
        await emitter.tool_started("declaration_query", f"查询报关单 {entry_id}")
        text = await asyncio.to_thread(DataClient().fetch_declaration_text, entry_id)
        if not text:
            raise AgentApiException(
                AgentError(
                    error_code="DECLARATION_DATA_NOT_FOUND",
                    message=f"未找到报关单数据: {entry_id}",
                    retryable=False,
                    stage="declaration_query",
                ),
                http_status=404,
            )
        data_source = (
            "mock"
            if request.business_context.get("mock_mode") is True
            else "platform_or_mock_fallback"
        )
        await emitter.tool_finished(
            "declaration_query",
            f"查询报关单 {entry_id}",
            f"已取得 {len(text)} 个字符",
        )
        return AdapterResult(
            final_answer=f"已取得报关单 {entry_id} 的数据。",
            structured_result={
                "entry_id": entry_id,
                "declaration_text": text,
                "data_source": data_source,
            },
        )


class RegulationSearchAdapter:
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        kb = getattr(app.state, "kb", None)
        if kb is None:
            raise AgentApiException(
                AgentError(
                    error_code="REGULATION_SEARCH_FAILED",
                    message="法规知识库尚未就绪",
                    retryable=True,
                    stage="regulation_search",
                ),
                http_status=503,
            )
        query = str(
            request.business_context.get("regulation_query")
            or request.message.content
        ).strip()
        await emitter.tool_started("regulation_search", "检索法规依据")
        results = await kb.search_with_score(query, k=5)
        citations = []
        for document, score in results:
            metadata = getattr(document, "metadata", {}) or {}
            citations.append(
                {
                    "source": metadata.get("source", "unknown"),
                    "snippet": str(getattr(document, "page_content", ""))[:2000],
                    "score": float(score),
                }
            )
        await emitter.tool_finished(
            "regulation_search",
            "检索法规依据",
            f"找到 {len(citations)} 条相关依据",
        )
        return AdapterResult(
            final_answer=f"已检索到 {len(citations)} 条法规或知识库依据。",
            structured_result={"citations": citations},
            outputs=[
                AgentOutput(
                    output_id=f"out-{uuid4().hex}",
                    kind=OutputKind.CITATION_SET,
                    format="json",
                    name="法规引用清单",
                    source_tool="regulation_search",
                    data=citations,
                )
            ],
        )


class BatchAuditAdapter:
    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        spreadsheet = next(
            (
                item
                for item in context.downloaded_attachments
                if item.path.suffix.lower() in {".xlsx", ".xls", ".csv"}
            ),
            None,
        )
        if spreadsheet is None:
            raise AgentApiException(
                AgentError(
                    error_code="BATCH_FILE_REQUIRED",
                    message="批量审单需要 XLSX、XLS 或 CSV 附件",
                    retryable=False,
                    stage="batch_audit",
                ),
                http_status=422,
            )
        try:
            from src.database.connection import AsyncSessionLocal
            from src.database.crud import BatchRepository
            from src.services.batch_processor import (
                BatchProcessor,
                start_batch_processing,
            )
        except ImportError as exc:
            raise AgentApiException(
                AgentError(
                    error_code="BATCH_SERVICE_UNAVAILABLE",
                    message="批量审单依赖尚未就绪",
                    retryable=True,
                    stage="batch_audit",
                ),
                http_status=503,
            ) from exc

        await emitter.tool_started("batch_audit", "创建批量审单任务")
        processor = BatchProcessor()
        items = await processor.parse_file(
            spreadsheet.path.read_bytes(),
            spreadsheet.name,
        )
        async with AsyncSessionLocal() as database:
            repository = BatchRepository(database)
            task_id = await repository.create_batch_task(len(items))
            await repository.add_batch_items(task_id, items)
        start_batch_processing(task_id)
        await emitter.tool_finished(
            "batch_audit",
            "创建批量审单任务",
            f"已提交 {len(items)} 条记录",
        )
        return AdapterResult(
            final_answer=f"批量审单任务已创建，共 {len(items)} 条记录。",
            structured_result={
                "task_id": task_id,
                "item_count": len(items),
                "status": "queued",
            },
        )


class ReportAdapter:
    def __init__(
        self,
        exporter: ReportDocumentExporter | None = None,
    ) -> None:
        self.exporter = exporter or ReportDocumentExporter()

    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        reporter_template = getattr(app.state, "reporter", None)
        if reporter_template is None:
            raise AgentApiException(
                AgentError(
                    error_code="REPORT_GENERATION_FAILED",
                    message="报告生成服务尚未就绪",
                    retryable=True,
                    stage="generating_report",
                ),
                http_status=503,
            )
        try:
            reporter = reporter_template.__class__(
                kb=getattr(app.state, "kb", None),
                llm_config=getattr(app.state, "llm_config", None),
            )
        except TypeError:
            reporter = reporter_template
        input_text = str(
            request.business_context.get("report_source")
            or request.business_context.get("declaration_text")
            or request.message.content
        ).strip()
        await emitter.tool_started("report_generation", "生成合规建议书")
        async for event_text in reporter.generate_stream(
            input_text,
            language=request.language,
            stream_chunks=False,
        ):
            for payload in parse_legacy_sse(event_text):
                event_type = payload.get("type")
                event_payload = payload.get("payload")
                if event_type == "step_start" and isinstance(event_payload, dict):
                    await emitter.status(
                        "generating_report",
                        str(event_payload.get("title") or "正在生成报告"),
                    )
                elif event_type == "error":
                    raise AgentApiException(
                        AgentError(
                            error_code="REPORT_GENERATION_FAILED",
                            message=str(event_payload or "报告生成失败"),
                            retryable=True,
                            stage="generating_report",
                        )
                    )

        report_text = str(getattr(reporter, "report_text_buffer", "")).strip()
        if not report_text:
            raise AgentApiException(
                AgentError(
                    error_code="REPORT_GENERATION_FAILED",
                    message="报告服务未生成有效内容",
                    retryable=True,
                    stage="generating_report",
                )
            )
        outputs: list[AgentOutput] = []
        warnings: list[AgentError] = []
        if (
            context.output_manager
            and request.options.output_file_policy != "none"
        ):
            with tempfile.TemporaryDirectory(prefix="customs-report-") as temp_dir:
                report_path = Path(temp_dir) / "compliance-report.docx"
                self.exporter.export_docx(
                    title="报关合规建议书",
                    markdown_text=report_text,
                    destination=report_path,
                )
                output, warning = await context.output_manager.publish_file(
                    source_path=report_path,
                    tenant_id=request.session.tenant_id,
                    kind=OutputKind.DOCUMENT,
                    format="docx",
                    name="报关合规建议书.docx",
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    source_tool="report_generation",
                    metadata={"character_count": len(report_text)},
                    prefer_platform=(
                        request.options.output_file_policy
                        == "upload_to_platform"
                    ),
                )
                outputs.append(output)
                if warning:
                    warnings.append(warning)
                await emitter.emit(
                    EventType.OUTPUT_CREATED,
                    output=output.model_dump(mode="json"),
                )
        await emitter.tool_finished(
            "report_generation",
            "生成合规建议书",
            f"报告共 {len(report_text)} 个字符",
        )
        return AdapterResult(
            final_answer="合规建议书已生成。",
            structured_result={
                "report_text": report_text,
                "character_count": len(report_text),
            },
            outputs=outputs,
            warnings=warnings,
        )


class DemoFullReviewAdapter:
    """Stable demo workflow for platform integration without multimodal dependencies."""

    def __init__(
        self,
        exporter: ReportDocumentExporter | None = None,
    ) -> None:
        self.exporter = exporter or ReportDocumentExporter()

    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        entry_id = str(request.business_context.get("entry_id") or "").strip()
        declaration_text = str(
            request.business_context.get("declaration_text") or ""
        ).strip()

        if not declaration_text:
            if not entry_id:
                entry_id = "530120250001"
            await emitter.tool_started(
                "declaration_query",
                f"查询演示报关单 {entry_id}",
            )
            declaration_text = await asyncio.to_thread(
                DataClient().fetch_declaration_text,
                entry_id,
            )
            if not declaration_text:
                declaration_text = self._fallback_declaration_text(entry_id)
            await emitter.tool_finished(
                "declaration_query",
                f"查询演示报关单 {entry_id}",
                "已取得演示报关数据",
            )

        await emitter.tool_started("declaration_audit", "执行演示审单")
        audit = self._demo_audit(declaration_text)
        await emitter.tool_finished(
            "declaration_audit",
            "执行演示审单",
            f"风险等级: {audit['risk_level']}",
        )

        await emitter.tool_started("regulation_search", "整理演示法规依据")
        citations = self._demo_citations(declaration_text)
        citation_output = AgentOutput(
            output_id=f"out-{uuid4().hex}",
            kind=OutputKind.CITATION_SET,
            format="json",
            name="演示法规依据",
            source_tool="regulation_search",
            data=citations,
        )
        await emitter.emit(
            EventType.OUTPUT_CREATED,
            output=citation_output.model_dump(mode="json"),
        )
        await emitter.tool_finished(
            "regulation_search",
            "整理演示法规依据",
            f"已整理 {len(citations)} 条依据",
        )

        report_text = self._demo_report(
            entry_id=entry_id,
            declaration_text=declaration_text,
            audit=audit,
            citations=citations,
        )
        outputs = [citation_output]
        warnings: list[AgentError] = []
        if context.output_manager and request.options.output_file_policy != "none":
            await emitter.tool_started("report_generation", "生成演示 DOCX 报告")
            with tempfile.TemporaryDirectory(prefix="customs-demo-report-") as temp_dir:
                report_path = Path(temp_dir) / "demo-customs-review.docx"
                self.exporter.export_docx(
                    title="报关智能体演示审单报告",
                    markdown_text=report_text,
                    destination=report_path,
                )
                output, warning = await context.output_manager.publish_file(
                    source_path=report_path,
                    tenant_id=request.session.tenant_id,
                    kind=OutputKind.DOCUMENT,
                    format="docx",
                    name="报关智能体演示审单报告.docx",
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    source_tool="demo_full_review",
                    metadata={
                        "entry_id": entry_id,
                        "risk_level": audit["risk_level"],
                        "process_state": audit["process_state"],
                    },
                    prefer_platform=(
                        request.options.output_file_policy == "upload_to_platform"
                    ),
                )
                outputs.append(output)
                if warning:
                    warnings.append(warning)
                await emitter.emit(
                    EventType.OUTPUT_CREATED,
                    output=output.model_dump(mode="json"),
                )
            await emitter.tool_finished(
                "report_generation",
                "生成演示 DOCX 报告",
                "演示报告已生成",
            )

        final_answer = (
            f"演示审单完成。报关单号：{entry_id or '文本输入'}；"
            f"风险等级：{audit['risk_level']}；"
            f"流程状态：{audit['process_state']}。"
        )
        await emitter.emit(EventType.MESSAGE_DELTA, content=final_answer)
        return AdapterResult(
            final_answer=final_answer,
            structured_result={
                "mode": "demo",
                "entry_id": entry_id,
                "declaration_text": declaration_text,
                "audit": audit,
                "regulations": {"citations": citations},
                "report": {"character_count": len(report_text)},
                "process": {
                    "data_source": "mock_or_input",
                    "state": audit["process_state"],
                    "next_action": audit["next_action"],
                },
            },
            outputs=outputs,
            warnings=warnings,
        )

    @staticmethod
    def _fallback_declaration_text(entry_id: str) -> str:
        return f"""报关单号：{entry_id}
境内收货人：演示进出口有限公司
货物名称：32位数字信号处理器(IC)
HS编码：85423100
数量：5000 个
单价：15.00 USD
总价：75000.00 USD
原产国：马来西亚
品牌：TI
申报要素：
1.品名：32位数字信号处理器；2.品牌：TI；3.型号：TMS320F28335PGFA；4.用途：工业电机控制。

【随附单证信息】
1. 商业发票：金额 75000.00 USD
2. 装箱单：毛重 55.0 KG / 净重 50.0 KG
"""

    @staticmethod
    def _demo_audit(declaration_text: str) -> dict[str, Any]:
        findings = []
        if "HS编码" in declaration_text or "85423100" in declaration_text:
            findings.append(
                {
                    "rule_id": "HS_CONSISTENCY",
                    "status": "review_recommended",
                    "message": "HS 编码与集成电路类商品描述基本匹配，建议复核型号和功能说明。",
                }
            )
        if "总价" in declaration_text or "75000" in declaration_text:
            findings.append(
                {
                    "rule_id": "PRICE_LOGIC",
                    "status": "pass",
                    "message": "数量、单价和总价逻辑可用于演示核对，未发现明显计算异常。",
                }
            )
        if "原产国" in declaration_text:
            findings.append(
                {
                    "rule_id": "DOCUMENT_CONSISTENCY",
                    "status": "review_recommended",
                    "message": "建议在真实流程中继续核对发票、装箱单和原产地信息一致性。",
                }
            )
        risk_level = "medium" if findings else "low"
        return {
            "risk_level": risk_level,
            "risk_count": len(
                [item for item in findings if item["status"] != "pass"]
            ),
            "findings": findings,
            "process_state": "review_recommended",
            "next_action": "演示环境建议进入人工复核，确认后可模拟放行。",
        }

    @staticmethod
    def _demo_citations(declaration_text: str) -> list[dict[str, Any]]:
        _ = declaration_text
        return [
            {
                "source": "mock-regulation/customs-declaration-elements",
                "snippet": "申报要素应与商品名称、型号、用途、品牌及随附单证保持一致。",
                "score": 0.95,
            },
            {
                "source": "mock-regulation/price-review",
                "snippet": "价格审核应关注数量、单价、总价及贸易单证之间的逻辑关系。",
                "score": 0.9,
            },
        ]

    @staticmethod
    def _demo_report(
        *,
        entry_id: str,
        declaration_text: str,
        audit: dict[str, Any],
        citations: list[dict[str, Any]],
    ) -> str:
        finding_lines = "\n".join(
            f"- {item['rule_id']}：{item['message']}"
            for item in audit["findings"]
        )
        citation_lines = "\n".join(
            f"- {item['source']}：{item['snippet']}" for item in citations
        )
        return f"""# 报关智能体演示审单报告

## 基本信息
- 报关单号：{entry_id or '文本输入'}
- 风险等级：{audit['risk_level']}
- 流程状态：{audit['process_state']}

## 审单结论
{finding_lines or '- 未发现明显风险。'}

## 法规/规则依据
{citation_lines}

## 下一步建议
{audit['next_action']}

## 输入摘要
{declaration_text[:1200]}
"""


class FullReviewAdapter:
    def __init__(
        self,
        *,
        ocr: CapabilityAdapter,
        audit: CapabilityAdapter,
        regulations: CapabilityAdapter,
        report: CapabilityAdapter,
        declaration: CapabilityAdapter,
    ) -> None:
        self.ocr = ocr
        self.audit = audit
        self.regulations = regulations
        self.report = report
        self.declaration = declaration

    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        accumulated_text = request.message.content.strip()
        outputs: list[AgentOutput] = []
        warnings: list[AgentError] = []
        structured: dict[str, Any] = {}

        if request.business_context.get("entry_id"):
            declaration_result = await self.declaration.execute(
                request, app, emitter, context
            )
            structured["declaration"] = declaration_result.structured_result
            accumulated_text += (
                "\n\n" + declaration_result.structured_result["declaration_text"]
            )

        if context.downloaded_attachments:
            ocr_result = await self.ocr.execute(request, app, emitter, context)
            structured["documents"] = ocr_result.structured_result.get(
                "documents", []
            )
            outputs.extend(ocr_result.outputs)
            warnings.extend(ocr_result.warnings)
            for document in structured["documents"]:
                text = str(document.get("full_text") or "").strip()
                if text:
                    accumulated_text += "\n\n" + text

        working_request = request.model_copy(deep=True)
        working_request.message.content = accumulated_text
        working_request.business_context["declaration_text"] = accumulated_text
        audit_result = await self.audit.execute(
            working_request, app, emitter, ExecutionContext()
        )
        structured["audit"] = audit_result.structured_result

        regulation_request = working_request.model_copy(deep=True)
        regulation_request.business_context["regulation_query"] = (
            request.message.content + "\n" + audit_result.final_answer
        )
        regulation_result = await self.regulations.execute(
            regulation_request, app, emitter, ExecutionContext()
        )
        structured["regulations"] = regulation_result.structured_result
        outputs.extend(regulation_result.outputs)

        report_request = working_request.model_copy(deep=True)
        report_request.business_context["report_source"] = (
            accumulated_text
            + "\n\n审单结论："
            + audit_result.final_answer
            + "\n\n法规依据："
            + str(regulation_result.structured_result)
        )
        report_result = await self.report.execute(
            report_request, app, emitter, context
        )
        structured["report"] = {
            "character_count": report_result.structured_result.get(
                "character_count", 0
            )
        }
        outputs.extend(report_result.outputs)
        warnings.extend(report_result.warnings)

        final_answer = (
            f"{audit_result.final_answer}\n\n"
            f"{regulation_result.final_answer}\n"
            f"{report_result.final_answer}"
        )
        await emitter.emit(EventType.MESSAGE_DELTA, content=final_answer)
        return AdapterResult(
            final_answer=final_answer,
            structured_result=structured,
            outputs=outputs,
            warnings=warnings,
        )


class OcrAdapter:
    def __init__(
        self,
        backend: VisionBackend,
        table_exporter: TableWorkbookExporter | None = None,
    ):
        self.backend = backend
        self.table_exporter = table_exporter or TableWorkbookExporter()

    async def execute(
        self,
        request: CreateRunRequest,
        app: FastAPI,
        emitter: EventEmitter,
        context: ExecutionContext,
    ) -> AdapterResult:
        if not context.downloaded_attachments:
            raise AgentApiException(
                AgentError(
                    error_code="ATTACHMENT_REQUIRED",
                    message="OCR 任务至少需要一个图片或文档附件",
                    retryable=False,
                    stage="recognizing_image",
                ),
                http_status=422,
            )

        outputs: list[AgentOutput] = []
        results: list[dict[str, Any]] = []
        warnings: list[AgentError] = []
        for attachment in context.downloaded_attachments:
            await emitter.tool_started("image_ocr", f"识别 {attachment.name}")
            result = await self.backend.extract(
                path=attachment.path,
                name=attachment.name,
                mime_type=attachment.mime_type,
                language=request.language,
            )
            document = result.document or DocumentResult(
                source_file_id=attachment.file_id,
                source_name=attachment.name,
                document_type=DocumentType.UNKNOWN,
                language=request.language,
                full_text=result.text,
            )
            document = document.model_copy(
                update={
                    "source_file_id": attachment.file_id,
                    "source_name": attachment.name,
                    "language": request.language,
                    "model_used": result.model,
                    "backend": self.backend.__class__.__name__,
                    "metadata": {
                        **document.metadata,
                        "format": result.format,
                        "session_id": result.session_id,
                        "sha256": attachment.sha256,
                    },
                }
            )
            data = document.model_dump(mode="json", exclude_none=True)
            output = AgentOutput(
                output_id=f"out-{uuid4().hex}",
                kind=OutputKind.STRUCTURED_DATA,
                format="json",
                name=f"{attachment.name} 识别结果",
                source_tool="image_ocr",
                data=data,
                metadata={
                    "source_attachment_ids": [attachment.file_id],
                    "model_used": result.model,
                },
            )
            outputs.append(output)
            results.append(data)
            await emitter.tool_finished(
                "image_ocr",
                f"识别 {attachment.name}",
                f"已识别 {len(result.text)} 个字符",
            )
            await emitter.emit(
                EventType.OUTPUT_CREATED,
                output=output.model_dump(mode="json"),
            )
            workbook_output, warning = await self._export_tables(
                request=request,
                document=document,
                attachment_name=attachment.name,
                output_manager=context.output_manager,
            )
            if workbook_output:
                outputs.append(workbook_output)
                await emitter.emit(
                    EventType.OUTPUT_CREATED,
                    output=workbook_output.model_dump(mode="json"),
                )
            if warning:
                warnings.append(warning)
                results[-1].setdefault("warnings", []).append(
                    warning.model_dump(mode="json", exclude_none=True)
                )

        final_answer = f"已完成 {len(results)} 个附件的图片文字识别。"
        spreadsheet_count = sum(
            output.kind == OutputKind.SPREADSHEET for output in outputs
        )
        if spreadsheet_count:
            final_answer += f" 已生成 {spreadsheet_count} 个可编辑 Excel 文件。"
        await emitter.emit(EventType.MESSAGE_DELTA, content=final_answer)
        return AdapterResult(
            final_answer=final_answer,
            structured_result={"documents": results},
            outputs=outputs,
            warnings=warnings,
        )

    async def _export_tables(
        self,
        *,
        request: CreateRunRequest,
        document: DocumentResult,
        attachment_name: str,
        output_manager: OutputManager | None,
    ) -> tuple[AgentOutput | None, AgentError | None]:
        if (
            not document.tables
            or output_manager is None
            or request.options.output_file_policy == "none"
        ):
            return None, None

        with tempfile.TemporaryDirectory(prefix="customs-table-") as temp_dir:
            stem = Path(attachment_name).stem or "table"
            workbook_path = Path(temp_dir) / f"{stem}.xlsx"
            self.table_exporter.export(document, workbook_path)
            return await output_manager.publish_file(
                source_path=workbook_path,
                tenant_id=request.session.tenant_id,
                kind=OutputKind.SPREADSHEET,
                format="xlsx",
                name=f"{stem}-识别表格.xlsx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                source_tool="table_export",
                metadata={
                    "source_attachment_ids": [document.source_file_id],
                    "document_id": document.document_id,
                    "table_count": len(document.tables),
                },
                prefer_platform=(
                    request.options.output_file_policy == "upload_to_platform"
                ),
            )
