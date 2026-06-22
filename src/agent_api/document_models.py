from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import SCHEMA_VERSION


class DocumentType(str, Enum):
    CUSTOMS_DECLARATION = "customs_declaration"
    INVOICE = "invoice"
    PACKING_LIST = "packing_list"
    CERTIFICATE = "certificate"
    TABLE = "table"
    UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    AUTO_ACCEPTED = "auto_accepted"
    REVIEW_RECOMMENDED = "review_recommended"
    REVIEW_REQUIRED = "review_required"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(gt=0)
    y2: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "BoundingBox":
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bbox x2/y2 must be greater than x1/y1")
        return self


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(default_factory=lambda: f"block-{uuid4().hex}")
    page: int = Field(ge=1)
    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CellResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    normalized_value: Any = None
    page: int = Field(default=1, ge=1)
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.REVIEW_RECOMMENDED


class TableResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(default_factory=lambda: f"table-{uuid4().hex}")
    page: int = Field(default=1, ge=1)
    rows: int = Field(ge=1)
    columns: int = Field(ge=1)
    bbox: BoundingBox | None = None
    cells: list[CellResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cells(self) -> "TableResult":
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            if (
                cell.row + cell.row_span > self.rows
                or cell.column + cell.column_span > self.columns
            ):
                raise ValueError("cell position exceeds declared table dimensions")
            positions = {
                (row, column)
                for row in range(cell.row, cell.row + cell.row_span)
                for column in range(
                    cell.column, cell.column + cell.column_span
                )
            }
            if occupied.intersection(positions):
                raise ValueError("table cells overlap")
            occupied.update(positions)
        return self


class FieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=200)
    raw_text: str = ""
    normalized_value: Any = None
    source_file_id: str = Field(min_length=1, max_length=300)
    page: int = Field(default=1, ge=1)
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.REVIEW_RECOMMENDED
    model_used: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, max_length=100)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    severity: ValidationSeverity
    field_key: str | None = Field(default=None, max_length=200)
    source_file_id: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    text_blocks: list[TextBlock] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)


class DocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    document_id: str = Field(default_factory=lambda: f"doc-{uuid4().hex}")
    source_file_id: str = Field(min_length=1, max_length=300)
    source_name: str = Field(min_length=1, max_length=500)
    document_type: DocumentType = DocumentType.UNKNOWN
    language: str = Field(default="zh", pattern=r"^(zh|vi)$")
    full_text: str = ""
    pages: list[PageResult] = Field(default_factory=list)
    tables: list[TableResult] = Field(default_factory=list)
    fields: list[FieldEvidence] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    model_used: str | None = Field(default=None, max_length=200)
    backend: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemplateTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["excel", "docx", "pdf", "image"]
    sheet: str | None = Field(default=None, max_length=200)
    cell: str | None = Field(default=None, max_length=50)
    cell_range: str | None = Field(default=None, max_length=100)
    bookmark: str | None = Field(default=None, max_length=200)
    page: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "TemplateTarget":
        if self.kind == "excel" and not (self.cell or self.cell_range):
            raise ValueError("excel target requires cell or cell_range")
        if self.kind == "docx" and not self.bookmark:
            raise ValueError("docx target requires bookmark")
        if self.kind in {"pdf", "image"} and not (self.page and self.bbox):
            raise ValueError("pdf/image target requires page and bbox")
        return self


class TemplateFieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=200)
    target: TemplateTarget
    required: bool = False
    formatter: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] = Field(default_factory=dict)


class TemplateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    template_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["excel", "docx", "pdf", "image"]
    source_file_id: str = Field(min_length=1, max_length=300)
    mappings: list[TemplateFieldMapping] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
