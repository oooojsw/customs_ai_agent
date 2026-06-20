from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


SCHEMA_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    AGENT_STARTED = "agent_started"
    STATUS_CHANGED = "status_changed"
    MESSAGE_DELTA = "message_delta"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_FINISHED = "tool_finished"
    OUTPUT_CREATED = "output_created"
    WARNING = "warning"
    HEARTBEAT = "heartbeat"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_CANCELLED = "agent_cancelled"


class AttachmentKind(str, Enum):
    IMAGE = "image"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    ARCHIVE = "archive"
    STRUCTURED_DATA = "structured_data"


class OutputKind(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    SPREADSHEET = "spreadsheet"
    STRUCTURED_DATA = "structured_data"
    TABLE = "table"
    ARCHIVE = "archive"
    CITATION_SET = "citation_set"
    VALIDATION_REPORT = "validation_report"
    TEMPLATE_DEFINITION = "template_definition"


class SessionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(default="default", min_length=1, max_length=200)
    context_version: int | None = Field(default=None, ge=0)


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"] = "user"
    content: str = Field(default="", max_length=200_000)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=300)
    kind: AttachmentKind
    name: str = Field(min_length=1, max_length=500)
    purpose: str = Field(default="unknown", max_length=100)
    mime_type: str | None = Field(default=None, max_length=200)
    size: int | None = Field(default=None, ge=0)
    download_url: HttpUrl | None = None
    expires_at: datetime | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=100_000)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_mode: Literal["stream", "poll"] = "stream"
    intent: Literal[
        "auto",
        "chat",
        "audit",
        "ocr",
        "report",
        "declaration_query",
        "regulation_search",
        "batch_audit",
        "full_review",
    ] = "auto"
    include_tool_trace: bool = True
    include_structured_result: bool = True
    output_file_policy: Literal[
        "upload_to_platform", "agent_temporary", "none"
    ] = "upload_to_platform"
    timeout_seconds: int = Field(default=600, ge=10, le=3600)
    output_formats: list[
        Literal["json", "xlsx", "docx", "pdf", "png", "txt", "md"]
    ] = Field(default_factory=list, max_length=10)
    template_id: str | None = Field(default=None, max_length=200)
    require_review: bool = False
    preserve_layout: bool = True
    branch_id: str | None = Field(default=None, max_length=200)


class CallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_url: HttpUrl | None = None


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=200)
    session: SessionRef
    message: AgentMessage
    language: str = Field(default="zh", pattern=r"^(zh|vi)$")
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)
    business_context: dict[str, Any] = Field(default_factory=dict)
    conversation_context: ConversationContext | None = None
    options: RunOptions = Field(default_factory=RunOptions)
    callback: CallbackConfig | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "CreateRunRequest":
        has_business_input = bool(
            str(
                self.business_context.get("entry_id")
                or self.business_context.get("declaration_text")
                or self.business_context.get("report_source")
                or ""
            ).strip()
        )
        if (
            not self.message.content.strip()
            and not self.attachments
            and not has_business_input
        ):
            raise ValueError("message.content or at least one attachment is required")
        return self


class AgentError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    stage: str | None = Field(default=None, max_length=100)
    dependency: str | None = Field(default=None, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, max_length=200)


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_id: str = Field(min_length=1, max_length=200)
    kind: OutputKind
    format: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=500)
    mime_type: str | None = Field(default=None, max_length=200)
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    source_tool: str | None = Field(default=None, max_length=100)
    platform_file_id: str | None = Field(default=None, max_length=300)
    preview_url: HttpUrl | None = None
    download_url: HttpUrl | None = None
    agent_output_url: str | None = Field(default=None, max_length=2000)
    data: dict[str, Any] | list[Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=utc_now)
    event: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class RunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=200)
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    final_answer: str = ""
    structured_result: dict[str, Any] = Field(default_factory=dict)
    outputs: list[AgentOutput] = Field(default_factory=list)
    warnings: list[AgentError] = Field(default_factory=list)
    error: AgentError | None = None
    last_sequence: int = 0
    context_version: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class CreateRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    request_id: str
    status: RunStatus
    events_url: str
    status_url: str


class CancelRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    cancellation_requested: bool


class CapabilityDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    status: Literal["available", "planned", "degraded"] = "available"
    input_kinds: list[str] = Field(default_factory=list)
    output_kinds: list[str] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str = "customs_agent"
    display_name: str = "报关智能体"
    schema_version: str = SCHEMA_VERSION
    capabilities: list[CapabilityDescriptor]
