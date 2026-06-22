import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_api.adapters import (
    ExecutionContext,
    MockImportDeclarationAdapter,
)
from src.agent_api.events import EventEmitter
from src.agent_api.models import CreateRunRequest, EventType
from src.agent_api.store import InMemoryRunStore
from src.agent_api.service import AgentRunService
from src.agent_api.models import RunStatus
from src.customs_simulator.models import (
    BusinessCaseSnapshot,
    CustomsStage,
    DeclarationData,
    TaxAssessment,
)
from src.customs_simulator.authority import PersistentCustomsAuthority
from src.customs_simulator.classifier import GoodsClassificationAgent
from src.customs_simulator.knowledge_rules import KnowledgeRulePackLoader
from src.customs_simulator.repository import CaseVersionConflictError
from src.customs_simulator.routes import router as simulator_router
from src.customs_simulator import routes as simulator_routes
from src.customs_simulator.service import MockCustomsWorkflowService
from src.customs_simulator.state_machine import (
    InvalidStateTransition,
    ensure_transition,
)
from src.customs_simulator.toolset import DeclarationAgentToolset


FIXTURE_DIR = Path("data/mock_customs_cases")


@pytest.fixture
def workflow(tmp_path):
    return MockCustomsWorkflowService(
        tmp_path / "mock-customs.db",
        FIXTURE_DIR,
    )


@pytest.mark.parametrize(
    ("mock_case_id", "versions", "must_have_stage"),
    [
        ("normal_release", 1, CustomsStage.TAX_PAID),
        ("returned_then_release", 2, CustomsStage.RETURNED),
        ("high_risk_inspection", 1, CustomsStage.INSPECTION_COMPLETED),
    ],
)
def test_three_full_workflows_close_with_expected_evidence(
    workflow, mock_case_id, versions, must_have_stage
):
    case = workflow.run_full_workflow(
        mock_case_id,
        "tenant-001",
        "user-001",
        f"session-{mock_case_id}",
    )

    assert case.stage == CustomsStage.CLOSED
    assert case.mock is True
    assert len(case.declaration_versions) == versions
    assert case.tax_assessment is not None
    assert case.tax_assessment.status == "PAID"
    assert any(event.stage == must_have_stage for event in case.timeline)
    assert case.timeline[-1].event_type == "case_closed"
    assert [event.sequence for event in case.timeline] == list(
        range(1, len(case.timeline) + 1)
    )


def test_returned_case_preserves_old_version_and_records_diff(workflow):
    toolset = DeclarationAgentToolset(workflow)
    case = workflow.create_case(
        "returned_then_release", "tenant-001", "user-001", "session-001"
    )
    while case.stage != CustomsStage.RETURNED:
        case = workflow.advance(case.business_case_id)

    old_version = case.current_declaration.model_copy(deep=True)
    case = workflow.advance(case.business_case_id)
    differences = toolset.compare_declaration_versions(
        {"business_case_id": case.business_case_id}
    )

    assert case.current_declaration.version_no == 2
    assert old_version.declaration.goods[0].model == ""
    assert case.current_declaration.declaration.goods[0].model == "MX-SV-7500"
    changed_fields = {item["field"] for item in differences["differences"]}
    assert "goods[0].model" in changed_fields
    assert "goods[0].usage" in changed_fields


def test_case_persists_after_repository_recreation(tmp_path):
    database = tmp_path / "persistent.db"
    first = MockCustomsWorkflowService(database, FIXTURE_DIR)
    created = first.create_case(
        "normal_release", "tenant-001", "user-001", "session-001"
    )
    advanced = first.advance(created.business_case_id)

    second = MockCustomsWorkflowService(database, FIXTURE_DIR)
    restored = second.get_case(created.business_case_id)

    assert restored.case_version == advanced.case_version
    assert restored.stage == CustomsStage.DOCUMENTS_READY
    assert restored.timeline == advanced.timeline


def test_case_version_conflict_is_rejected(workflow):
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-001"
    )
    first_copy = workflow.get_case(case.business_case_id)
    advanced = workflow.advance(case.business_case_id)
    first_copy.stage = CustomsStage.DOCUMENTS_READY

    with pytest.raises(CaseVersionConflictError):
        workflow.repository.save(first_copy, case.case_version)

    assert workflow.get_case(case.business_case_id).case_version == advanced.case_version


def test_illegal_state_transition_is_rejected():
    with pytest.raises(InvalidStateTransition):
        ensure_transition(CustomsStage.DRAFT, CustomsStage.RELEASED)


def test_cancel_persists_terminal_case(workflow):
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-001"
    )
    cancelled = workflow.cancel(case.business_case_id)

    assert cancelled.stage == CustomsStage.CANCELLED
    assert cancelled.allowed_actions == []
    assert workflow.get_case(case.business_case_id).stage == CustomsStage.CANCELLED


def test_fixed_cases_are_reproducible_for_core_results(tmp_path):
    results = []
    for index in range(5):
        workflow = MockCustomsWorkflowService(
            tmp_path / f"repeat-{index}.db", FIXTURE_DIR
        )
        case = workflow.run_full_workflow(
            "high_risk_inspection",
            "tenant-001",
            "user-001",
            f"session-{index}",
        )
        results.append(
            (
                case.stage,
                case.tax_assessment.total_tax,
                case.inspection.result,
                tuple(receipt.receipt_type for receipt in case.receipts),
            )
        )

    assert len(set(results)) == 1


@pytest.mark.parametrize(
    ("case_id", "fixture_updates", "expected_stage"),
    [
        (
            "supplement_path",
            {"acceptance_requires_supplement": True},
            CustomsStage.SUPPLEMENT_REQUIRED,
        ),
        (
            "license_path",
            {
                "license_review_passes": True,
                "declaration": {
                    "goods": [{"regulatory_codes": ["7"]}],
                },
            },
            CustomsStage.LICENSE_REVIEW,
        ),
    ],
)
def test_optional_customs_windows_complete(
    tmp_path, case_id, fixture_updates, expected_stage
):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    base = json.loads(
        (FIXTURE_DIR / "normal_release.json").read_text(encoding="utf-8")
    )
    if case_id == "license_path":
        base["license_review_passes"] = True
        base["declaration"]["goods"][0]["regulatory_codes"] = ["7"]
    else:
        base.update(fixture_updates)
    (fixture_dir / f"{case_id}.json").write_text(
        json.dumps(base, ensure_ascii=False),
        encoding="utf-8",
    )
    service = MockCustomsWorkflowService(tmp_path / "optional.db", fixture_dir)
    case = service.run_full_workflow(
        case_id, "tenant-001", "user-001", f"session-{case_id}"
    )

    assert case.stage == CustomsStage.CLOSED
    assert any(event.stage == expected_stage for event in case.timeline)
    if expected_stage == CustomsStage.SUPPLEMENT_REQUIRED:
        assert "SUPPLEMENT_COMPLETED" in case.resolved_reason_codes
    if expected_stage == CustomsStage.LICENSE_REVIEW:
        assert "LICENSE_REQUIRED" in case.resolved_reason_codes


def test_toolset_runs_real_operations(workflow):
    tools = DeclarationAgentToolset(workflow)
    created = tools.create_import_case(
        {
            "source_mode": "fixed_fixture",
            "mock_case_id": "normal_release",
            "tenant_id": "tenant-001",
            "user_id": "user-001",
            "session_id": "session-001",
        }
    )
    case_id = created["business_case_id"]

    loaded = tools.load_mock_documents({"business_case_id": case_id})
    validated = tools.validate_document_set({"business_case_id": case_id})
    classified = tools.classify_goods({"business_case_id": case_id})
    tax = tools.estimate_customs_tax({"business_case_id": case_id})

    assert loaded["stage"] == CustomsStage.DOCUMENTS_READY.value
    assert validated["stage"] == CustomsStage.PRECHECK_PASSED.value
    assert classified["candidates"][0]["declared_hs_code"] == "85423100"
    assert tax["total_tax"] > 0


def test_internal_routes_enforce_allowed_action_and_version(
    workflow, monkeypatch
):
    monkeypatch.setattr(simulator_routes, "workflow_service", workflow)
    app = FastAPI()
    app.include_router(simulator_router, prefix="/internal/customs-simulator/v1")

    with TestClient(app) as client:
        created = client.post(
            "/internal/customs-simulator/v1/cases",
            json={
                "mock_case_id": "normal_release",
                "tenant_id": "tenant-001",
                "user_id": "user-001",
                "session_id": "session-001",
            },
        )
        assert created.status_code == 200
        case = created.json()
        case_id = case["business_case_id"]

        invalid = client.post(
            f"/internal/customs-simulator/v1/cases/{case_id}/actions",
            json={
                "request_id": "action-invalid",
                "action": "PAY_TAX",
                "expected_case_version": case["case_version"],
            },
        )
        assert invalid.status_code == 422
        assert (
            invalid.json()["detail"]["error_code"]
            == "CUSTOMS_ACTION_NOT_ALLOWED"
        )
        assert invalid.json()["detail"]["mock"] is True
        assert invalid.json()["detail"]["allowed_actions"] == [
            "LOAD_DOCUMENTS",
            "CANCEL",
        ]

        advanced = client.post(
            f"/internal/customs-simulator/v1/cases/{case_id}/actions",
            json={
                "request_id": "action-load",
                "action": "LOAD_DOCUMENTS",
                "expected_case_version": case["case_version"],
            },
        )
        assert advanced.status_code == 200
        assert advanced.json()["status"] == CustomsStage.DOCUMENTS_READY.value

        conflict = client.post(
            f"/internal/customs-simulator/v1/cases/{case_id}/actions",
            json={
                "request_id": "action-conflict",
                "action": "RUN_PRECHECK",
                "expected_case_version": case["case_version"],
            },
        )
        assert conflict.status_code == 409


def test_internal_action_request_id_is_idempotent(workflow, monkeypatch):
    monkeypatch.setattr(simulator_routes, "workflow_service", workflow)
    app = FastAPI()
    app.include_router(simulator_router, prefix="/internal/customs-simulator/v1")

    with TestClient(app) as client:
        case = client.post(
            "/internal/customs-simulator/v1/cases",
            json={
                "mock_case_id": "normal_release",
                "tenant_id": "tenant-001",
                "user_id": "user-001",
                "session_id": "session-idempotent",
            },
        ).json()
        payload = {
            "request_id": "same-action-request",
            "action": "LOAD_DOCUMENTS",
            "expected_case_version": case["case_version"],
        }
        first = client.post(
            f"/internal/customs-simulator/v1/cases/{case['business_case_id']}/actions",
            json=payload,
        )
        second = client.post(
            f"/internal/customs-simulator/v1/cases/{case['business_case_id']}/actions",
            json=payload,
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == first.json()
        restored = workflow.get_case(case["business_case_id"])
        assert restored.case_version == case["case_version"] + 1
        assert len(restored.timeline) == 2


def test_case_creation_request_id_is_idempotent(workflow):
    first = workflow.create_case(
        "normal_release",
        "tenant-idempotent",
        "user-001",
        "session-001",
        "create-request-001",
    )
    second = workflow.create_case(
        "normal_release",
        "tenant-idempotent",
        "user-001",
        "session-001",
        "create-request-001",
    )

    assert second.business_case_id == first.business_case_id
    assert second.case_version == first.case_version
    assert len(
        workflow.repository.list_for_session(
            "tenant-idempotent", "session-001"
        )
    ) == 1


def test_custom_structured_product_is_not_limited_to_fixed_hs(workflow):
    declaration = {
        "consignee": "杭州纺织品进口有限公司",
        "overseas_consignor": "Vietnam Fabric Co., Ltd.",
        "trade_mode": "0110",
        "transport_mode": "海运",
        "bill_of_lading_no": "MOCK-TEXTILE-BL-001",
        "invoice_no": "TEXTILE-INV-001",
        "contract_no": "TEXTILE-CON-001",
        "packing_list_no": "TEXTILE-PL-001",
        "currency": "USD",
        "incoterm": "CIF",
        "freight": 600,
        "insurance": 80,
        "goods": [
            {
                "item_no": 1,
                "name": "涤纶针织染色布",
                "hs_code": "60063200",
                "quantity": 10000,
                "quantity_unit": "米",
                "unit_price": 2.5,
                "total_price": 25000,
                "currency": "USD",
                "gross_weight": 2200,
                "net_weight": 2100,
                "origin_country": "越南",
                "brand": "V-FABRIC",
                "model": "PF-150",
                "usage": "服装面料",
                "material": "100% 聚酯纤维",
            }
        ],
    }
    documents = [
        {"document_id": "CUSTOM-CON", "document_type": "contract"},
        {"document_id": "CUSTOM-INV", "document_type": "invoice"},
        {"document_id": "CUSTOM-PL", "document_type": "packing_list"},
        {"document_id": "CUSTOM-BL", "document_type": "bill_of_lading"},
    ]
    case = workflow.create_case_from_data(
        declaration,
        documents,
        "tenant-custom",
        "user-custom",
        "session-custom",
        "request-custom-textile",
        {"exchange_rate": 7.2, "duty_rate": 0.08, "vat_rate": 0.13},
    )
    while case.stage != CustomsStage.CLOSED:
        case = workflow.advance(case.business_case_id)

    assert case.stage == CustomsStage.CLOSED
    assert case.current_declaration.declaration.goods[0].hs_code == "60063200"
    assert case.mock_case_id == "custom_structured_case"
    assert case.tax_assessment.total_tax > 0


def test_authority_context_is_rebuilt_from_persisted_history(workflow):
    case = workflow.create_case(
        "returned_then_release", "tenant-001", "user-001", "session-context"
    )
    while case.stage != CustomsStage.ACCEPTED:
        case = workflow.advance(case.business_case_id)
    case = workflow.advance(case.business_case_id)
    case = workflow.advance(case.business_case_id)

    context_events = [
        event
        for event in case.timeline
        if event.event_type == "authority_context_rebuilt"
    ]
    assert len(context_events) >= 2
    assert context_events[-1].data["previous_receipt_count"] >= 2
    packet = workflow.authority.build_context_packet(
        case,
        [],
        [CustomsStage.TAX_ASSESSED],
        "VERIFY_PERSISTED_CONTEXT",
    )
    prompt = workflow.authority.render_system_prompt(packet)
    assert case.business_case_id in prompt
    assert case.current_declaration.version_id in prompt
    assert "previous_receipts" in prompt
    assert workflow.authority.prompt_version in prompt


def test_authority_model_output_is_schema_and_state_constrained(workflow):
    attempts = []

    def invalid_provider(prompt):
        attempts.append(prompt)
        return {
            "decision": "RELEASED",
            "window": "invalid",
            "message": "非法跳过流程",
        }

    authority = PersistentCustomsAuthority(
        decision_provider=invalid_provider,
        model_version="mock-provider-test",
    )
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-model-guard"
    )
    fallback = authority.decide_acceptance(case, [])
    resolution = authority.resolve_decision(
        case,
        [],
        [CustomsStage.ACCEPTED, CustomsStage.RETURNED],
        "PROCESS_ACCEPTANCE",
        fallback,
    )

    assert len(attempts) == 2
    assert resolution.decision.decision == CustomsStage.ACCEPTED
    assert resolution.fallback_used is True
    assert resolution.model_invoked is True
    assert case.business_case_id in attempts[0]


def test_langgraph_authority_accepts_valid_model_decision(workflow):
    def valid_provider(prompt):
        assert "allowed_decisions" in prompt
        return {
            "decision": "ACCEPTED",
            "window": "declaration_acceptance",
            "reason_codes": [],
            "message": "模型已审核当前案件并模拟受理。",
            "required_actions": [{"action": "START_REVIEW"}],
            "risk_level": "low",
            "next_stage": "ACCEPTED",
            "receipt_type": "CUSTOMS_ACCEPTANCE_NOTICE",
            "mock": True,
        }

    authority = PersistentCustomsAuthority(
        decision_provider=valid_provider,
        model_version="test-langgraph-model",
    )
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-valid-model"
    )
    fallback = authority.decide_acceptance(case, [])
    resolution = authority.resolve_decision(
        case,
        [],
        [CustomsStage.ACCEPTED],
        "PROCESS_ACCEPTANCE",
        fallback,
    )

    assert resolution.decision.message == "模型已审核当前案件并模拟受理。"
    assert resolution.model_invoked is True
    assert resolution.fallback_used is False
    assert resolution.attempt_count == 1


def test_goods_classifier_uses_model_semantics(workflow):
    class FakeResponse:
        content = json.dumps(
            {
                "candidates": [
                    {
                        "item_no": 1,
                        "candidate_hs_codes": ["85423100", "85423990"],
                        "confidence": 0.88,
                        "basis": "根据数字信号处理功能、硅基集成电路材质和工业控制用途判断。",
                        "required_declaration_elements": [
                            "品牌",
                            "型号",
                            "功能",
                            "用途",
                        ],
                        "regulatory_hints": [],
                        "ambiguity": ["需核实是否具有独立处理器功能"],
                    }
                ],
                "mock": True,
            },
            ensure_ascii=False,
        )

    class FakeLlm:
        def invoke(self, _messages):
            return FakeResponse()

    workflow.authority.llm = FakeLlm()
    workflow.authority.model_version = "test-classifier-model"
    workflow.classifier = GoodsClassificationAgent(workflow.authority)
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-classifier"
    )
    result = DeclarationAgentToolset(workflow).classify_goods(
        {"business_case_id": case.business_case_id}
    )

    assert result["model_invoked"] is True
    assert result["fallback_used"] is False
    assert result["candidates"][0]["candidate_hs_codes"] == [
        "85423100",
        "85423990",
    ]
    restored = workflow.get_case(case.business_case_id)
    assert "goods_classification" in restored.analysis_results


def test_normalized_audit_tables_are_populated(tmp_path):
    database = tmp_path / "normalized.db"
    service = MockCustomsWorkflowService(database, FIXTURE_DIR)
    case = service.run_full_workflow(
        "high_risk_inspection",
        "tenant-001",
        "user-001",
        "session-normalized",
    )

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "mock_customs_schema_migrations" in tables
        assert "mock_customs_declaration_versions" in tables
        assert "mock_customs_documents" in tables
        assert "mock_customs_receipts" in tables
        assert "mock_customs_timeline_events" in tables
        assert "mock_customs_tax_assessments" in tables
        assert "mock_customs_inspections" in tables
        assert "mock_customs_agent_decisions" in tables
        receipt_count = connection.execute(
            """
            SELECT COUNT(*) FROM mock_customs_receipts
            WHERE business_case_id = ?
            """,
            (case.business_case_id,),
        ).fetchone()[0]
        event_count = connection.execute(
            """
            SELECT COUNT(*) FROM mock_customs_timeline_events
            WHERE business_case_id = ?
            """,
            (case.business_case_id,),
        ).fetchone()[0]
        decision_count = connection.execute(
            """
            SELECT COUNT(*) FROM mock_customs_agent_decisions
            WHERE business_case_id = ?
            """,
            (case.business_case_id,),
        ).fetchone()[0]

    assert receipt_count == len(case.receipts)
    assert event_count == len(case.timeline)
    assert decision_count >= 2


def test_authority_timeout_retries_then_falls_back(workflow):
    attempts = []

    def timeout_provider(_prompt):
        attempts.append(1)
        raise TimeoutError("simulated model timeout")

    authority = PersistentCustomsAuthority(
        decision_provider=timeout_provider,
        model_version="timeout-model",
    )
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-timeout"
    )
    fallback = authority.decide_acceptance(case, [])
    resolution = authority.resolve_decision(
        case,
        [],
        [CustomsStage.ACCEPTED],
        "PROCESS_ACCEPTANCE",
        fallback,
    )

    assert len(attempts) == 2
    assert resolution.fallback_used is True
    assert resolution.model_invoked is True
    assert "TimeoutError" in resolution.error


def test_extended_rules_and_release_conditions(workflow):
    fixture = workflow.fixtures.load("normal_release")
    declaration = DeclarationData.model_validate(fixture["declaration"])
    declaration.goods[0].currency = "EUR"
    declaration.goods[0].total_price = 100_000
    declaration.goods[0].unit_price = 20
    declaration.goods[0].quantity = 5_000
    declaration.goods[0].net_weight = 5
    declaration.freight = 0

    findings = workflow.rules.review(declaration)
    codes = {finding.code for finding in findings}
    assert "CURRENCY_MISMATCH" in codes
    assert "HIGH_VALUE_LOW_WEIGHT" in codes
    assert "CIF_FREIGHT_MISSING" in codes
    assert workflow.rules.requires_inspection(findings) is True
    assert workflow.rules.deterministic_random_inspection("case-1", 1) is True
    assert workflow.rules.deterministic_random_inspection("case-1", 0) is False

    case = BusinessCaseSnapshot(
        business_case_id="MOCK-CASE-RELEASE",
        tenant_id="tenant",
        user_id="user",
        session_id="session",
        mock_case_id="normal_release",
        declaration_versions=[],
        stage=CustomsStage.TAX_PAID,
        tax_assessment=TaxAssessment(
            customs_value=100,
            duty_rate=0,
            duty_amount=0,
            vat_rate=0.13,
            vat_amount=13,
            total_tax=13,
            status="ASSESSED",
        ),
    )
    release_codes = {
        finding.code for finding in workflow.rules.validate_release(case)
    }
    assert "TAX_PAYMENT_REQUIRED" in release_codes


def _pen_declaration() -> dict:
    return {
        "entry_id": "TEST-005",
        "consignee": "中国进口商",
        "overseas_consignor": "越南文具出口公司",
        "trade_mode": "0110",
        "transport_mode": "海运",
        "bill_of_lading_no": "BOL-005",
        "invoice_no": "INV-005",
        "contract_no": "CONT-005",
        "packing_list_no": "PL-005",
        "currency": "USD",
        "incoterm": "CIF",
        "freight": 500,
        "insurance": 100,
        "goods": [
            {
                "item_no": 1,
                "name": "塑料圆珠笔",
                "hs_code": "96081000",
                "quantity": 5000,
                "quantity_unit": "支",
                "unit_price": 100,
                "total_price": 500000,
                "currency": "USD",
                "gross_weight": 150,
                "net_weight": 140,
                "origin_country": "越南",
                "brand": "无名",
                "model": "B-100",
                "usage": "办公用",
                "material": "塑料",
            }
        ],
    }


def test_create_tool_requires_explicit_source_and_preserves_custom_input(workflow):
    toolset = DeclarationAgentToolset(workflow)
    with pytest.raises(ValueError, match="CASE_SOURCE_MODE_REQUIRED"):
        toolset.create_import_case({})

    created = toolset.create_import_case(
        {
            "source_mode": "custom_declaration",
            "declaration": _pen_declaration(),
            "generate_mock_documents": True,
            "tenant_id": "tenant-pen",
            "user_id": "user-pen",
            "session_id": "session-pen",
        }
    )
    case = workflow.get_case(created["business_case_id"])

    assert case.case_source == "custom_declaration"
    assert case.mock_case_id == "custom_structured_case"
    assert case.current_declaration.declaration.entry_id == "TEST-005"
    assert case.current_declaration.declaration.goods[0].name == "塑料圆珠笔"
    assert case.current_declaration.declaration.goods[0].unit_price == 100
    assert {document.document_type for document in case.documents} == {
        "contract",
        "invoice",
        "packing_list",
        "bill_of_lading",
    }
    assert all(
        document.source == "generated_mock_from_custom_declaration"
        for document in case.documents
    )


def test_custom_case_analysis_tools_can_run_sequentially(workflow):
    toolset = DeclarationAgentToolset(workflow)
    created = toolset.create_import_case(
        {
            "source_mode": "custom_declaration",
            "declaration": _pen_declaration(),
            "generate_mock_documents": True,
            "tenant_id": "tenant-analysis",
            "user_id": "user-analysis",
            "session_id": "session-analysis",
        }
    )
    case_id = created["business_case_id"]

    elements = toolset.validate_declaration_elements(
        {"business_case_id": case_id}
    )
    tax = toolset.estimate_customs_tax({"business_case_id": case_id})

    assert elements["business_case_id"] == case_id
    assert elements["passed"] is True
    assert tax["total_tax"] > 0


def test_pen_price_risk_pack_drives_customs_price_query(workflow):
    toolset = DeclarationAgentToolset(workflow)
    created = toolset.create_import_case(
        {
            "source_mode": "custom_declaration",
            "declaration": _pen_declaration(),
            "generate_mock_documents": True,
            "tenant_id": "tenant-risk",
            "user_id": "user-risk",
            "session_id": "session-risk",
        }
    )
    case_id = created["business_case_id"]
    toolset.load_mock_documents({"business_case_id": case_id})
    toolset.validate_document_set({"business_case_id": case_id})
    pre_audit = toolset.pre_audit_declaration({"business_case_id": case_id})
    risk_codes = {
        finding["code"] for finding in pre_audit["review_findings"]
    }

    assert "PRICE_STATIONERY_UNIT_VALUE_OUTLIER" in risk_codes
    assert "PRICE_AML_TRADE_OVERSTATEMENT_RED_FLAG" in risk_codes
    assert pre_audit["risk_level"] == "high"
    assert pre_audit["requires_customs_review"] is True

    toolset.build_declaration_draft({"business_case_id": case_id})
    toolset.submit_customs_declaration({"business_case_id": case_id})
    toolset.process_customs_acceptance({"business_case_id": case_id})
    toolset.start_customs_review({"business_case_id": case_id})
    reviewed = toolset.process_customs_review({"business_case_id": case_id})

    assert reviewed["stage"] == CustomsStage.PRICE_QUERY.value


def test_knowledge_rule_pack_is_hot_pluggable(tmp_path):
    rule_dir = tmp_path / "customs-rules"
    rule_dir.mkdir()
    (rule_dir / "custom.json").write_text(
        json.dumps(
            {
                "pack_id": "custom-test",
                "version": "1.0",
                "rules": [
                    {
                        "code": "CUSTOM_ORIGIN_REVIEW",
                        "stage": "customs_review",
                        "severity": "medium",
                        "message": "测试原产国规则",
                        "scope": "goods",
                        "all": [
                            {
                                "field": "origin_country",
                                "operator": "eq",
                                "value": "越南",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loader = KnowledgeRulePackLoader(rule_dir)
    declaration = DeclarationData.model_validate(_pen_declaration())

    findings = loader.evaluate(declaration, "customs_review")

    assert [finding.code for finding in findings] == [
        "CUSTOM_ORIGIN_REVIEW"
    ]
    assert loader.version == "custom-test@1.0"


def test_tax_failure_does_not_fake_success(workflow, monkeypatch):
    case = workflow.create_case(
        "normal_release", "tenant-001", "user-001", "session-tax-failure"
    )
    while case.stage != CustomsStage.UNDER_REVIEW:
        case = workflow.advance(case.business_case_id)

    def fail_tax(*_args, **_kwargs):
        raise RuntimeError("simulated tax engine failure")

    monkeypatch.setattr(workflow, "_assess_tax", fail_tax)
    with pytest.raises(RuntimeError, match="simulated tax engine failure"):
        workflow.advance(case.business_case_id)
    restored = workflow.get_case(case.business_case_id)
    assert restored.stage == CustomsStage.UNDER_REVIEW
    assert restored.tax_assessment is None


@pytest.mark.parametrize(
    "mock_case_id",
    ["normal_release", "returned_then_release", "high_risk_inspection"],
)
def test_internal_api_can_drive_full_case(
    workflow, monkeypatch, mock_case_id
):
    monkeypatch.setattr(simulator_routes, "workflow_service", workflow)
    app = FastAPI()
    app.include_router(simulator_router, prefix="/internal/customs-simulator/v1")

    with TestClient(app) as client:
        case = client.post(
            "/internal/customs-simulator/v1/cases",
            json={
                "mock_case_id": mock_case_id,
                "tenant_id": "tenant-api",
                "user_id": "user-api",
                "session_id": f"session-{mock_case_id}",
            },
        ).json()
        for sequence in range(40):
            if case.get("stage") == CustomsStage.CLOSED.value:
                break
            action = case["allowed_actions"][0]
            response = client.post(
                (
                    "/internal/customs-simulator/v1/cases/"
                    f"{case['business_case_id']}/actions"
                ),
                json={
                    "request_id": f"{mock_case_id}-{sequence}",
                    "action": action,
                    "expected_case_version": case["case_version"],
                },
            )
            assert response.status_code == 200
            action_result = response.json()
            case = client.get(
                (
                    "/internal/customs-simulator/v1/cases/"
                    f"{case['business_case_id']}"
                )
            ).json()
            assert action_result["mock"] is True

        assert case["stage"] == CustomsStage.CLOSED.value
        assert case["mock"] is True


def test_agent_v1_adapter_emits_process_events(workflow):
    async def scenario():
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-mock-import-001",
                "session": {
                    "session_id": "session-001",
                    "user_id": "user-001",
                    "tenant_id": "tenant-001",
                },
                "message": {"content": "演示完整进口报关流程"},
                "business_context": {"mock_case_id": "returned_then_release"},
                "options": {"intent": "mock_import_declaration"},
            }
        )
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        result = await MockImportDeclarationAdapter(workflow).execute(
            request,
            FastAPI(),
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        events = await store.events_after(snapshot.run_id)

        assert result.structured_result["customs_stage"] == CustomsStage.CLOSED.value
        assert result.structured_result["declaration_version_count"] == 2
        assert any(
            event.event == EventType.CUSTOMS_PROCESS_UPDATED for event in events
        )
        process_events = [
            event for event in events
            if event.event == EventType.CUSTOMS_PROCESS_UPDATED
        ]
        for event in process_events:
            assert isinstance(event.data["stage_order"], int)
            assert event.data["total_stages"] >= event.data["stage_order"]
            assert 0 <= event.data["progress_percent"] <= 100
            assert isinstance(event.data["is_terminal"], bool)
            assert isinstance(event.data["risk_items"], list)
        assert any(event.data["stage"] == CustomsStage.RETURNED.value for event in process_events)
        assert process_events[-1].data["stage"] == CustomsStage.CLOSED.value
        assert process_events[-1].data["is_terminal"] is True

        tool_events = [
            event for event in events
            if event.event in {EventType.TOOL_STARTED, EventType.TOOL_FINISHED}
        ]
        customs_tool_finishes = [
            event for event in tool_events
            if event.event == EventType.TOOL_FINISHED
            and event.data["interaction_kind"] == "customs_authority"
        ]
        assert customs_tool_finishes
        assert all(event.data["auto_expand"] is True for event in customs_tool_finishes)
        assert any(event.data.get("customs_reply") for event in customs_tool_finishes)
        regular_tool_starts = [
            event for event in tool_events
            if event.event == EventType.TOOL_STARTED
            and event.data["interaction_kind"] == "declaration_operation"
        ]
        assert regular_tool_starts
        assert all(event.data["auto_expand"] is False for event in regular_tool_starts)

        output_events = [
            event for event in events
            if event.event == EventType.OUTPUT_CREATED
        ]
        assert output_events
        output = output_events[0].data["output"]
        assert {"output_id", "kind", "format", "name", "platform_file_id"} <= set(output)

    asyncio.run(scenario())


def test_agent_v1_accepts_custom_structured_declaration(workflow):
    async def scenario():
        declaration = {
            "consignee": "青岛食品进口有限公司",
            "overseas_consignor": "Thailand Foods Co., Ltd.",
            "trade_mode": "0110",
            "transport_mode": "海运",
            "bill_of_lading_no": "FOOD-BL-001",
            "invoice_no": "FOOD-INV-001",
            "contract_no": "FOOD-CON-001",
            "packing_list_no": "FOOD-PL-001",
            "currency": "USD",
            "incoterm": "CIF",
            "freight": 500,
            "insurance": 60,
            "goods": [
                {
                    "item_no": 1,
                    "name": "冷冻榴莲果肉",
                    "hs_code": "08119090",
                    "quantity": 1000,
                    "quantity_unit": "千克",
                    "unit_price": 6,
                    "total_price": 6000,
                    "currency": "USD",
                    "gross_weight": 1100,
                    "net_weight": 1000,
                    "origin_country": "泰国",
                    "brand": "TROPICAL",
                    "model": "FROZEN-PULP",
                    "usage": "食品加工原料",
                    "material": "榴莲果肉",
                }
            ],
        }
        documents = [
            {"document_id": "FOOD-CON", "document_type": "contract"},
            {"document_id": "FOOD-INV", "document_type": "invoice"},
            {"document_id": "FOOD-PL", "document_type": "packing_list"},
            {"document_id": "FOOD-BL", "document_type": "bill_of_lading"},
        ]
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-custom-food-001",
                "session": {
                    "session_id": "session-custom-food",
                    "user_id": "user-001",
                    "tenant_id": "tenant-001",
                },
                "message": {"content": "演示自定义食品进口申报"},
                "business_context": {
                    "declaration": declaration,
                    "documents": documents,
                    "workflow_config": {
                        "exchange_rate": 7.2,
                        "duty_rate": 0.1,
                        "vat_rate": 0.09,
                    },
                    "step_delay_ms": 0,
                },
                "options": {"intent": "mock_import_declaration"},
            }
        )
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        result = await MockImportDeclarationAdapter(workflow).execute(
            request,
            FastAPI(),
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )

        assert result.structured_result["customs_stage"] == "CLOSED"
        assert (
            result.structured_result["analysis_results"]
            ["goods_classification"]["candidates"][0]["declared_hs_code"]
            == "08119090"
        )

    asyncio.run(scenario())


def test_agent_run_cancel_stops_and_persists_customs_case(workflow):
    async def scenario():
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-mock-cancel-001",
                "session": {
                    "session_id": "session-cancel",
                    "user_id": "user-001",
                    "tenant_id": "tenant-001",
                },
                "message": {"content": "运行后取消"},
                "business_context": {
                    "mock_case_id": "high_risk_inspection",
                    "step_delay_ms": 200,
                },
                "options": {"intent": "mock_import_declaration"},
            }
        )
        service = AgentRunService(
            store=InMemoryRunStore(),
            adapters={
                "mock_import_declaration": MockImportDeclarationAdapter(workflow)
            },
            heartbeat_seconds=60,
        )
        created = await service.create_run(request, FastAPI())

        for _ in range(100):
            events = await service.store.events_after(created.run_id)
            if any(
                event.event == EventType.CUSTOMS_PROCESS_UPDATED
                for event in events
            ):
                break
            await asyncio.sleep(0.01)

        snapshot = await service.cancel_run(created.run_id)
        cases = workflow.repository.list_for_session(
            "tenant-001", "session-cancel"
        )

        assert snapshot.status == RunStatus.CANCELLED
        assert len(cases) == 1
        assert cases[0].stage == CustomsStage.CANCELLED
        assert cases[0].timeline[-1].event_type == "case_cancelled"

    asyncio.run(scenario())
