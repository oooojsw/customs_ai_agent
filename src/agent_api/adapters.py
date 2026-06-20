from __future__ import annotations

import json
import tempfile
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol
from uuid import uuid4

from fastapi import FastAPI

from src.core.orchestrator import RiskAnalysisOrchestrator
from src.services.data_client import DataClient

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
                await emitter.tool_started(tool_name, tool_name)
            elif event_type == "tool_end":
                tool_name = str(payload.get("tool_name") or "unknown_tool")
                tool_result = str(payload.get("tool_result") or "")
                summary = tool_result[:500] if request.options.include_tool_trace else ""
                await emitter.tool_finished(tool_name, tool_name, summary)
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
        return AdapterResult(final_answer=final_answer)


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
                    output=output.model_dump(mode="json", exclude_none=True),
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
            output=citation_output.model_dump(mode="json", exclude_none=True),
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
                    output=output.model_dump(mode="json", exclude_none=True),
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
                output=output.model_dump(mode="json", exclude_none=True),
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
                    output=workbook_output.model_dump(
                        mode="json", exclude_none=True
                    ),
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
