from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CustomsStage(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENTS_READY = "DOCUMENTS_READY"
    PRECHECK_PASSED = "PRECHECK_PASSED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    SUPPLEMENT_REQUIRED = "SUPPLEMENT_REQUIRED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PRICE_QUERY = "PRICE_QUERY"
    LICENSE_REVIEW = "LICENSE_REVIEW"
    INSPECTION_REQUIRED = "INSPECTION_REQUIRED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
    TAX_ASSESSED = "TAX_ASSESSED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    TAX_PAID = "TAX_PAID"
    RELEASED = "RELEASED"
    PICKED_UP = "PICKED_UP"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class GoodsItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_no: int = Field(ge=1)
    name: str
    hs_code: str = ""
    quantity: float = Field(gt=0)
    quantity_unit: str
    unit_price: float = Field(ge=0)
    total_price: float = Field(ge=0)
    currency: str = "USD"
    gross_weight: float = Field(gt=0)
    net_weight: float = Field(gt=0)
    origin_country: str
    brand: str = ""
    model: str = ""
    usage: str = ""
    material: str = ""
    declaration_elements: dict[str, Any] = Field(default_factory=dict)
    regulatory_codes: list[str] = Field(default_factory=list)
    reference_unit_price_min: float | None = None
    reference_unit_price_max: float | None = None


class DeclarationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    entry_id: str = ""
    consignee: str
    overseas_consignor: str
    trade_mode: str = "0110"
    transport_mode: str
    bill_of_lading_no: str
    invoice_no: str
    contract_no: str
    packing_list_no: str
    currency: str = "USD"
    incoterm: str = "CIF"
    freight: float = Field(default=0, ge=0)
    insurance: float = Field(default=0, ge=0)
    goods: list[GoodsItem] = Field(min_length=1)
    licenses: list[dict[str, Any]] = Field(default_factory=list)


class MockDocument(BaseModel):
    document_id: str
    document_type: str
    document_version: int = 1
    structured_data: dict[str, Any] = Field(default_factory=dict)
    source: str = "mock_fixture"
    validation_status: str = "pending"
    created_at: str = Field(default_factory=utc_now_iso)
    mock: bool = True


class RuleFinding(BaseModel):
    code: str
    severity: str
    stage: str
    message: str
    field: str | None = None
    blocking: bool = False


class DeclarationVersion(BaseModel):
    version_id: str
    version_no: int
    declaration: DeclarationData
    reason: str
    source_version_id: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class CustomsReceipt(BaseModel):
    receipt_id: str
    receipt_type: str
    window: str
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    message: str
    required_actions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    declaration_version_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    mock: bool = True


class TimelineEvent(BaseModel):
    event_id: str = Field(
        default_factory=lambda: f"MOCK-EVENT-{uuid4().hex[:12].upper()}"
    )
    business_case_id: str = ""
    customs_case_id: str = ""
    sequence: int
    stage: CustomsStage
    event_type: str
    actor: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class TaxAssessment(BaseModel):
    customs_value: float
    exchange_rate: float = 1
    duty_rate: float
    duty_amount: float
    vat_rate: float
    vat_amount: float
    consumption_tax_rate: float = 0
    consumption_tax_amount: float = 0
    total_tax: float
    currency: str = "CNY"
    status: str = "ASSESSED"
    payment_reference: str | None = None


class InspectionRecord(BaseModel):
    reason_codes: list[str]
    directive: str = ""
    inspection_items: list[str] = Field(default_factory=list)
    scheduled_at: str | None = None
    result: str | None = None
    differences: list[str] = Field(default_factory=list)
    disposition: str | None = None


class BusinessCaseSnapshot(BaseModel):
    business_case_id: str
    customs_case_id: str = ""
    tenant_id: str
    user_id: str
    session_id: str
    mock_case_id: str
    case_source: str = "fixed_fixture"
    input_declaration_fingerprint: str = ""
    input_declaration_summary: dict[str, Any] = Field(default_factory=dict)
    trade_mode: str = "0110"
    direction: str = "import"
    case_version: int = 1
    context_version: int = 1
    stage: CustomsStage = CustomsStage.DRAFT
    declaration_versions: list[DeclarationVersion] = Field(default_factory=list)
    documents: list[MockDocument] = Field(default_factory=list)
    findings: list[RuleFinding] = Field(default_factory=list)
    receipts: list[CustomsReceipt] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    tax_assessment: TaxAssessment | None = None
    inspection: InspectionRecord | None = None
    analysis_results: dict[str, Any] = Field(default_factory=dict)
    workflow_config: dict[str, Any] = Field(default_factory=dict)
    resolved_reason_codes: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    case_summary: str = ""
    current_window: str = "case_creation"
    risk_level: str = "unknown"
    mock: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @property
    def current_declaration(self) -> DeclarationVersion:
        if not self.declaration_versions:
            raise ValueError("case has no declaration version")
        return self.declaration_versions[-1]
