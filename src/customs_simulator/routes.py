from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.config.loader import settings

from .repository import (
    CaseNotFoundError,
    CaseVersionConflictError,
)
from .service import MockCustomsWorkflowService
from .state_machine import InvalidStateTransition


router = APIRouter()
workflow_service = MockCustomsWorkflowService(
    settings.MOCK_CUSTOMS_DB_PATH,
    settings.MOCK_CUSTOMS_FIXTURE_DIR,
)


def configure_customs_authority(llm_config: dict[str, Any]) -> None:
    workflow_service.configure_authority(llm_config)


class CreateCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mock_case_id: str = "normal_release"
    tenant_id: str = "default"
    user_id: str
    session_id: str
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    declaration: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    workflow_config: dict[str, Any] = Field(default_factory=dict)


class CaseActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=200)
    action: str
    actor: str = "declaration_agent"
    expected_case_version: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def _handle_error(
    exc: Exception,
    business_case_id: str | None = None,
) -> HTTPException:
    status_code = 422
    error_code = str(exc).split(":", 1)[0] or "CUSTOMS_SIMULATOR_ERROR"
    retryable = False
    if isinstance(exc, CaseNotFoundError):
        status_code = 404
        error_code = "BUSINESS_CASE_NOT_FOUND"
    elif isinstance(exc, CaseVersionConflictError):
        status_code = 409
        error_code = "CUSTOMS_CASE_VERSION_CONFLICT"
        retryable = True
    elif isinstance(exc, InvalidStateTransition):
        status_code = 409
        error_code = "INVALID_CUSTOMS_STATE_TRANSITION"

    allowed_actions: list[str] = []
    customs_case_id = business_case_id
    stage = "customs_simulator"
    if business_case_id:
        try:
            case = workflow_service.get_case(business_case_id)
            allowed_actions = case.allowed_actions
            customs_case_id = case.customs_case_id or business_case_id
            stage = case.stage.value
        except Exception:
            pass
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": str(exc),
            "stage": stage,
            "retryable": retryable,
            "business_case_id": business_case_id,
            "customs_case_id": customs_case_id,
            "allowed_actions": allowed_actions,
            "mock": True,
        },
    )


@router.post("/cases")
async def create_case(body: CreateCaseBody) -> dict[str, Any]:
    try:
        if body.declaration:
            snapshot = workflow_service.create_case_from_data(
                body.declaration,
                body.documents,
                body.tenant_id,
                body.user_id,
                body.session_id,
                body.request_id,
                body.workflow_config,
            )
        else:
            snapshot = workflow_service.create_case(
                body.mock_case_id,
                body.tenant_id,
                body.user_id,
                body.session_id,
                body.request_id,
            )
        return snapshot.model_dump(mode="json")
    except Exception as exc:
        raise _handle_error(exc) from exc


@router.get("/cases/{business_case_id}")
async def get_case(business_case_id: str) -> dict[str, Any]:
    try:
        return workflow_service.get_case(business_case_id).model_dump(mode="json")
    except Exception as exc:
        raise _handle_error(exc, business_case_id) from exc


@router.get("/cases/{business_case_id}/events")
async def get_case_events(business_case_id: str) -> list[dict[str, Any]]:
    try:
        case = workflow_service.get_case(business_case_id)
        return [event.model_dump(mode="json") for event in case.timeline]
    except Exception as exc:
        raise _handle_error(exc, business_case_id) from exc


@router.get("/cases/{business_case_id}/receipts")
async def get_case_receipts(business_case_id: str) -> list[dict[str, Any]]:
    try:
        case = workflow_service.get_case(business_case_id)
        return [receipt.model_dump(mode="json") for receipt in case.receipts]
    except Exception as exc:
        raise _handle_error(exc, business_case_id) from exc


@router.post("/cases/{business_case_id}/actions")
async def execute_action(
    business_case_id: str, body: CaseActionBody
) -> dict[str, Any]:
    try:
        return workflow_service.execute_action(
            business_case_id,
            body.request_id,
            body.action,
            body.expected_case_version,
        )
    except Exception as exc:
        raise _handle_error(exc, business_case_id) from exc
