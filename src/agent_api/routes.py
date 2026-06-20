from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from src.config.loader import settings

from .adapters import (
    BatchAuditAdapter,
    DeclarationQueryAdapter,
    DemoFullReviewAdapter,
    FullReviewAdapter,
    OcrAdapter,
    RegulationSearchAdapter,
    ReportAdapter,
)
from .attachments import AttachmentDownloadManager
from .auth import ServiceAuthenticator
from .callbacks import CompletionCallbackClient
from .errors import AgentApiException
from .events import format_sse
from .models import (
    CancelRunResponse,
    CapabilitiesResponse,
    CapabilityDescriptor,
    CreateRunRequest,
    CreateRunResponse,
    RunSnapshot,
)
from .outputs import LocalOutputRegistry, OutputManager
from .platform_files import HttpPlatformFilePublisher
from .service import AgentRunService
from .sqlite_store import SQLiteRunStore
from .store import InMemoryRunStore
from .vision import LegacyTableOcrBackend


router = APIRouter()
authenticator = ServiceAuthenticator(
    enabled=settings.AGENT_V1_AUTH_ENABLED,
    api_key=settings.AGENT_V1_SERVICE_API_KEY,
)
attachment_manager = AttachmentDownloadManager(
    settings.AGENT_V1_TEMP_DIR,
    allowed_hosts=settings.AGENT_V1_ATTACHMENT_ALLOWED_HOSTS,
    max_bytes=settings.AGENT_V1_ATTACHMENT_MAX_BYTES,
)
local_output_registry = LocalOutputRegistry(
    settings.AGENT_V1_OUTPUT_DIR,
    ttl_seconds=settings.AGENT_V1_OUTPUT_TTL_SECONDS,
)
platform_file_publisher = (
    HttpPlatformFilePublisher(
        settings.AGENT_V1_PLATFORM_FILE_UPLOAD_URL,
        api_key=settings.AGENT_V1_PLATFORM_FILE_API_KEY,
        timeout_seconds=settings.AGENT_V1_PLATFORM_FILE_TIMEOUT_SECONDS,
    )
    if settings.AGENT_V1_USE_PLATFORM_FILES
    else None
)
output_manager = OutputManager(
    local_output_registry,
    platform_publisher=platform_file_publisher,
)
run_store = (
    SQLiteRunStore(settings.AGENT_V1_RUN_DB_PATH)
    if settings.AGENT_V1_RUN_STORE == "sqlite"
    else InMemoryRunStore()
)
run_service = AgentRunService(
    store=run_store,
    attachment_manager=attachment_manager,
    output_manager=output_manager,
    callback_client=CompletionCallbackClient(
        allowed_hosts=settings.AGENT_V1_CALLBACK_ALLOWED_HOSTS,
        service_key=settings.AGENT_V1_SERVICE_API_KEY,
    ),
)
ocr_adapter = OcrAdapter(
    LegacyTableOcrBackend(
        os.getenv(
            "TABLE_OCR_URL",
            "http://172.18.23.177:7861/api/recognize",
        )
    )
)
report_adapter = ReportAdapter()
regulation_adapter = RegulationSearchAdapter()
declaration_adapter = DeclarationQueryAdapter()
run_service.adapters.update(
    {
        "ocr": ocr_adapter,
        "report": report_adapter,
        "declaration_query": declaration_adapter,
        "regulation_search": regulation_adapter,
        "batch_audit": BatchAuditAdapter(),
        "full_review": (
            DemoFullReviewAdapter()
            if settings.AGENT_V1_DEMO_MODE
            else FullReviewAdapter(
                ocr=ocr_adapter,
                audit=run_service.adapters["audit"],
                regulations=regulation_adapter,
                report=report_adapter,
                declaration=declaration_adapter,
            )
        ),
    }
)


def _error_response(
    exc: AgentApiException, request: Request | None = None
) -> JSONResponse:
    error = exc.error.model_copy(deep=True)
    if request is not None and not error.trace_id:
        error.trace_id = getattr(
            request.state,
            "agent_trace_id",
            request.headers.get("X-Request-ID"),
        )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": error.model_dump(mode="json", exclude_none=True),
        },
    )


@router.post(
    "/runs",
    response_model=CreateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(body: CreateRunRequest, request: Request) -> CreateRunResponse | Response:
    try:
        identity = authenticator.authenticate(request)
        authenticator.require_tenant(identity, body.session.tenant_id)
        return await run_service.create_run(body, request.app)
    except AgentApiException as exc:
        return _error_response(exc, request)


@router.get("/runs/{run_id}", response_model=RunSnapshot)
async def get_run(run_id: str, request: Request) -> RunSnapshot | Response:
    try:
        identity = authenticator.authenticate(request)
        snapshot = await run_service.store.get(run_id)
        authenticator.require_tenant(identity, snapshot.tenant_id)
        return snapshot
    except AgentApiException as exc:
        return _error_response(exc, request)


@router.get("/runs/{run_id}/events", response_model=None)
async def stream_run_events(
    request: Request,
    run_id: str,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse | Response:
    try:
        after_sequence = int(last_event_id or "0")
        if after_sequence < 0:
            raise ValueError
        identity = authenticator.authenticate(request)
        snapshot = await run_service.store.get(run_id)
        authenticator.require_tenant(identity, snapshot.tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Last-Event-ID 必须是非负整数",
        ) from exc
    except AgentApiException as exc:
        return _error_response(exc, request)

    async def event_stream():
        async for event in run_service.store.stream_events(run_id, after_sequence):
            yield format_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(run_id: str, request: Request) -> CancelRunResponse | Response:
    try:
        identity = authenticator.authenticate(request)
        existing = await run_service.store.get(run_id)
        authenticator.require_tenant(identity, existing.tenant_id)
        snapshot = await run_service.cancel_run(run_id)
        return CancelRunResponse(
            run_id=run_id,
            status=snapshot.status,
            cancellation_requested=True,
        )
    except AgentApiException as exc:
        return _error_response(exc, request)


@router.get("/outputs/{output_id}", response_model=None)
async def get_output(output_id: str, request: Request) -> dict | Response:
    try:
        identity = authenticator.authenticate(request)
        output = local_output_registry.get(output_id, identity.tenant_id)
        return output.model_dump(mode="json", exclude_none=True)
    except AgentApiException as exc:
        return _error_response(exc, request)


@router.get("/outputs/{output_id}/content", response_model=None)
async def download_output(output_id: str, request: Request) -> FileResponse | Response:
    try:
        identity = authenticator.authenticate(request)
        output = local_output_registry.get(output_id, identity.tenant_id)
        path = local_output_registry.get_path(output_id, identity.tenant_id)
        return FileResponse(
            path=path,
            filename=output.name,
            media_type=output.mime_type or "application/octet-stream",
        )
    except AgentApiException as exc:
        return _error_response(exc, request)


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(request: Request) -> CapabilitiesResponse | Response:
    try:
        authenticator.authenticate(request)
    except AgentApiException as exc:
        return _error_response(exc, request)
    return CapabilitiesResponse(
        capabilities=[
            CapabilityDescriptor(
                name="customs_chat",
                description="报关咨询、多轮对话及现有 Agent 工具编排",
                input_kinds=["text"],
                output_kinds=["text", "structured_data"],
            ),
            CapabilityDescriptor(
                name="declaration_audit",
                description="报关单多规则风险审查",
                input_kinds=["text", "structured_data"],
                output_kinds=["text", "structured_data"],
            ),
            CapabilityDescriptor(
                name="image_ocr",
                description="通过平台临时 URL 下载附件并调用现有表格 OCR",
                status=(
                    "available"
                    if settings.AGENT_V1_ATTACHMENT_ALLOWED_HOSTS
                    else "degraded"
                ),
                input_kinds=["image"],
                output_kinds=["text", "structured_data"],
            ),
            CapabilityDescriptor(
                name="compliance_report",
                description="合规报告生成与文件 Output",
                status="available",
                input_kinds=["text", "structured_data"],
                output_kinds=["document"],
            ),
            CapabilityDescriptor(
                name="full_customs_review",
                description="报关查询、审单、法规依据和报告生成统一演示链路",
                input_kinds=["text", "structured_data"],
                output_kinds=[
                    "text",
                    "structured_data",
                    "citation_set",
                    "document",
                ],
            ),
            CapabilityDescriptor(
                name="batch_audit",
                description="Excel/CSV 批量审单任务创建",
                input_kinds=["spreadsheet"],
                output_kinds=["structured_data", "spreadsheet"],
                status="degraded",
            ),
            CapabilityDescriptor(
                name="table_image_to_xlsx",
                description="结构化表格结果生成可编辑 Excel；视觉模型接入后自动发布",
                status="degraded",
                input_kinds=["image", "document"],
                output_kinds=["structured_data", "spreadsheet", "image"],
            ),
            CapabilityDescriptor(
                name="declaration_template_fill",
                description="结构化数据填写报关单模板并生成 XLSX/PDF/PNG",
                status="planned",
                input_kinds=["structured_data", "document", "image"],
                output_kinds=["spreadsheet", "document", "image"],
            ),
        ]
    )


@router.get("/health")
async def health(request: Request) -> dict:
    dependency_statuses = {
        "chat_agent": "ready"
        if getattr(request.app.state, "agent", None) is not None
        else "not_ready",
        "knowledge_base": "ready"
        if getattr(request.app.state, "kb", None) is not None
        else "not_ready",
        "reporter": "ready"
        if getattr(request.app.state, "reporter", None) is not None
        else "not_ready",
        "ocr": "configured",
        "file_center": (
            "configured" if platform_file_publisher else "local_fallback"
        ),
        "run_store": run_service.store.__class__.__name__,
    }
    return {
        "status": (
            "ok"
            if dependency_statuses["chat_agent"] == "ready"
            else "degraded"
        ),
        "schema_version": "1.0",
        "service": "customs-agent-v1",
        "dependencies": dependency_statuses,
    }
