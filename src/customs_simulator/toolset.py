from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BusinessCaseSnapshot, CustomsStage, RuleFinding
from .service import MockCustomsWorkflowService


class DeclarationAgentToolset:
    """Business-facing operations used by the declaration agent."""

    def __init__(self, workflow: MockCustomsWorkflowService):
        self.workflow = workflow

    def create_import_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_mode = str(payload.get("source_mode") or "").strip()
        if source_mode == "custom_declaration":
            declaration = payload.get("declaration")
            if not isinstance(declaration, dict):
                raise ValueError("CUSTOM_DECLARATION_REQUIRED")
            documents = list(payload.get("documents") or [])
            if payload.get("generate_mock_documents"):
                documents = self._generate_mock_documents(declaration)
            document_types = {
                str(document.get("document_type") or "")
                for document in documents
                if isinstance(document, dict)
            }
            required = {
                "contract",
                "invoice",
                "packing_list",
                "bill_of_lading",
            }
            if missing := sorted(required - document_types):
                raise ValueError(
                    "CUSTOM_DOCUMENT_SET_INCOMPLETE: " + ",".join(missing)
                )
            case = self.workflow.create_case_from_data(
                declaration,
                documents,
                str(payload.get("tenant_id") or "default"),
                str(payload.get("user_id") or "agent-user"),
                str(payload.get("session_id") or "agent-session"),
                str(payload.get("request_id") or "") or None,
                dict(payload.get("workflow_config") or {}),
            )
        elif source_mode == "fixed_fixture":
            mock_case_id = str(payload.get("mock_case_id") or "").strip()
            if not mock_case_id:
                raise ValueError("MOCK_CASE_ID_REQUIRED")
            if payload.get("declaration"):
                raise ValueError("FIXED_FIXTURE_REJECTS_CUSTOM_DECLARATION")
            case = self.workflow.create_case(
                mock_case_id,
                str(payload.get("tenant_id") or "default"),
                str(payload.get("user_id") or "agent-user"),
                str(payload.get("session_id") or "agent-session"),
                str(payload.get("request_id") or "") or None,
            )
        else:
            raise ValueError(
                "CASE_SOURCE_MODE_REQUIRED: fixed_fixture or custom_declaration"
            )
        return self._summary(case)

    def get_case_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        return case.model_dump(mode="json")

    def load_mock_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.DRAFT)

    def validate_document_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.DOCUMENTS_READY)

    def normalize_declaration_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        result = case.current_declaration.declaration.model_dump(mode="json")
        self.workflow.record_analysis_result(
            case.business_case_id,
            "normalization",
            {"declaration": result, "mock": True},
            "已将结构化单证映射为统一申报数据模型",
        )
        return result

    def classify_goods(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        result = {
            "business_case_id": case.business_case_id,
            **self.workflow.classifier.classify(
                case.current_declaration.declaration
            ),
        }
        declared_codes = {
            item.item_no: item.hs_code
            for item in case.current_declaration.declaration.goods
        }
        for candidate in result["candidates"]:
            candidate["declared_hs_code"] = declared_codes.get(
                candidate["item_no"], ""
            )
        candidate_codes_by_item: dict[int, set[str]] = {}
        for candidate in result["candidates"]:
            candidate_codes_by_item.setdefault(
                int(candidate["item_no"]), set()
            ).update(str(code) for code in candidate["candidate_hs_codes"])
        consistency_findings = [
            RuleFinding(
                code="HS_CLASSIFICATION_CONFLICT",
                severity="high",
                stage="pre_audit",
                field=f"goods[{item.item_no - 1}].hs_code",
                message=(
                    f"企业申报码 {item.hs_code} 未出现在模型候选中，"
                    "必须人工复核后才能继续申报"
                ),
                blocking=True,
            ).model_dump(mode="json")
            for item in case.current_declaration.declaration.goods
            if case.case_source == "custom_declaration"
            and item.hs_code
            and item.hs_code
            not in candidate_codes_by_item.get(item.item_no, set())
        ]
        result["consistency_findings"] = consistency_findings
        result["consistent_with_declaration"] = not consistency_findings
        self.workflow.record_analysis_result(
            case.business_case_id,
            "goods_classification",
            result,
            "已完成商品语义理解和 HS 候选归类",
        )
        return result

    def validate_declaration_elements(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        findings = self.workflow.rules.validate_acceptance(
            case.current_declaration.declaration
        )
        result = {
            "business_case_id": case.business_case_id,
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "passed": not any(finding.blocking for finding in findings),
            "mock": True,
        }
        self.workflow.record_analysis_result(
            case.business_case_id,
            "declaration_elements",
            result,
            "已完成 HS 格式和申报要素检查",
        )
        return result

    def check_regulatory_requirements(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        declaration = case.current_declaration.declaration
        requirements = [
            {
                "item_no": item.item_no,
                "regulatory_codes": item.regulatory_codes,
                "license_provided": bool(declaration.licenses),
            }
            for item in declaration.goods
        ]
        result = {
            "business_case_id": case.business_case_id,
            "requirements": requirements,
            "mock": True,
        }
        self.workflow.record_analysis_result(
            case.business_case_id,
            "regulatory_requirements",
            result,
            "已完成监管条件和许可证要求检查",
        )
        return result

    def estimate_customs_tax(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        fixture = self.workflow.get_workflow_config(case)
        assessment = self.workflow._assess_tax(case, fixture)
        result = assessment.model_dump(mode="json")
        self.workflow.record_analysis_result(
            case.business_case_id,
            "tax_estimate",
            result,
            f"已估算进口税费 {assessment.total_tax:.2f} CNY",
        )
        return result

    def pre_audit_declaration(self, payload: dict[str, Any]) -> dict[str, Any]:
        elements = self.validate_declaration_elements(payload)
        case = self.workflow.get_case(self._case_id(payload))
        review = self.workflow.rules.review(case.current_declaration.declaration)
        classification_findings = list(
            case.analysis_results.get("goods_classification", {}).get(
                "consistency_findings", []
            )
        )
        review_findings = [
            finding.model_dump(mode="json") for finding in review
        ]
        all_findings = [
            *elements["findings"],
            *classification_findings,
            *review_findings,
        ]
        blocking = any(finding.get("blocking", False) for finding in all_findings)
        risk_level = (
            "high"
            if any(finding.get("severity") == "high" for finding in all_findings)
            else "medium"
            if all_findings
            else "low"
        )
        result = {
            "business_case_id": case.business_case_id,
            "acceptance_findings": elements["findings"],
            "classification_findings": classification_findings,
            "review_findings": review_findings,
            "blocking": blocking,
            "passed": not blocking,
            "risk_detected": bool(all_findings),
            "risk_level": risk_level,
            "requires_customs_review": bool(review_findings),
            "rule_version": self.workflow.rules.effective_version,
            "mock": True,
        }
        self.workflow.record_analysis_result(
            case.business_case_id,
            "pre_audit",
            result,
            "已完成申报前智能审单",
        )
        return result

    def build_declaration_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        pre_audit = case.analysis_results.get("pre_audit", {})
        if (
            case.case_source == "custom_declaration"
            and pre_audit.get("blocking")
        ):
            raise ValueError("DECLARATION_PRE_AUDIT_BLOCKED")
        return self._advance_expected(payload, CustomsStage.PRECHECK_PASSED)

    def amend_declaration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.RETURNED)

    def compare_declaration_versions(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        if len(case.declaration_versions) < 2:
            return {"differences": [], "message": "当前只有一个申报版本"}
        previous = case.declaration_versions[-2].declaration.model_dump()
        current = case.declaration_versions[-1].declaration.model_dump()
        return {
            "business_case_id": case.business_case_id,
            "from_version": case.declaration_versions[-2].version_id,
            "to_version": case.declaration_versions[-1].version_id,
            "differences": self._diff(previous, current),
            "mock": True,
        }

    def submit_customs_declaration(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.READY_TO_SUBMIT)

    def process_customs_acceptance(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.SUBMITTED)

    def query_customs_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._summary(self.workflow.get_case(self._case_id(payload)))

    def start_customs_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.ACCEPTED)

    def process_customs_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.UNDER_REVIEW)

    def submit_supplementary_materials(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(
            payload, CustomsStage.SUPPLEMENT_REQUIRED
        )

    def respond_to_price_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.PRICE_QUERY)

    def confirm_license_information(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.LICENSE_REVIEW)

    def schedule_mock_inspection(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.INSPECTION_REQUIRED)

    def submit_inspection_result(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.INSPECTION_SCHEDULED)

    def assess_mock_customs_tax(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.INSPECTION_COMPLETED)

    def issue_mock_tax_bill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.TAX_ASSESSED)

    def pay_mock_customs_tax(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.PAYMENT_PENDING)

    def query_release_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        return {
            "business_case_id": case.business_case_id,
            "stage": case.stage.value,
            "released": case.stage
            in {
                CustomsStage.RELEASED,
                CustomsStage.PICKED_UP,
                CustomsStage.CLOSED,
            },
            "latest_receipt": (
                case.receipts[-1].model_dump(mode="json")
                if case.receipts
                else None
            ),
            "mock": True,
        }

    def release_mock_goods(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.TAX_PAID)

    def confirm_mock_pickup(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.RELEASED)

    def close_import_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advance_expected(payload, CustomsStage.PICKED_UP)

    def get_customs_process_timeline(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        return {
            "business_case_id": case.business_case_id,
            "stage": case.stage.value,
            "timeline": [
                event.model_dump(mode="json") for event in case.timeline
            ],
            "mock": True,
        }

    def generate_case_archive(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.get_case_snapshot(payload)

    def generate_customs_demo_report(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        return {
            "business_case_id": case.business_case_id,
            "title": "一般贸易进口模拟报关全过程报告",
            "summary": (
                f"案件 {case.business_case_id} 当前状态 {case.stage.value}，"
                f"共 {len(case.declaration_versions)} 个申报版本、"
                f"{len(case.receipts)} 份海关模拟回执。"
            ),
            "timeline": [
                {
                    "sequence": event.sequence,
                    "stage": event.stage.value,
                    "summary": event.summary,
                }
                for event in case.timeline
            ],
            "mock": True,
        }

    def run_mock_import_workflow(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.workflow.run_full_workflow(
            str(payload.get("mock_case_id") or "normal_release"),
            str(payload.get("tenant_id") or "default"),
            str(payload.get("user_id") or "agent-user"),
            str(payload.get("session_id") or "agent-session"),
            str(payload.get("request_id") or "") or None,
        )
        return self._summary(case)

    @staticmethod
    def _generate_mock_documents(
        declaration: dict[str, Any],
    ) -> list[dict[str, Any]]:
        identifiers = {
            "contract": str(declaration.get("contract_no") or "MOCK-CONTRACT"),
            "invoice": str(declaration.get("invoice_no") or "MOCK-INVOICE"),
            "packing_list": str(
                declaration.get("packing_list_no") or "MOCK-PACKING"
            ),
            "bill_of_lading": str(
                declaration.get("bill_of_lading_no") or "MOCK-BL"
            ),
        }
        return [
            {
                "document_id": identifier,
                "document_type": document_type,
                "structured_data": {
                    "linked_entry_id": declaration.get("entry_id", ""),
                    "linked_goods": declaration.get("goods", []),
                },
                "source": "generated_mock_from_custom_declaration",
                "validation_status": "pending",
                "mock": True,
            }
            for document_type, identifier in identifiers.items()
        ]

    def invoke(self, operation: str, raw_payload: str | dict[str, Any]) -> str:
        payload = (
            json.loads(raw_payload)
            if isinstance(raw_payload, str) and raw_payload.strip()
            else raw_payload
        )
        if not isinstance(payload, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        handler = getattr(self, operation, None)
        if handler is None or operation.startswith("_"):
            raise ValueError(f"未知报关流程工具: {operation}")
        return json.dumps(handler(payload), ensure_ascii=False, indent=2)

    def _advance_expected(
        self, payload: dict[str, Any], expected: CustomsStage
    ) -> dict[str, Any]:
        case = self.workflow.get_case(self._case_id(payload))
        if case.stage != expected:
            raise ValueError(
                f"CUSTOMS_ACTION_NOT_ALLOWED: expected={expected.value}, "
                f"actual={case.stage.value}"
            )
        action = next(
            (
                candidate
                for candidate in case.allowed_actions
                if candidate != "CANCEL"
            ),
            None,
        )
        if not action:
            raise ValueError(
                f"CUSTOMS_ACTION_NOT_ALLOWED: {case.stage.value}"
            )
        request_id = str(
            payload.get("request_id")
            or (
                f"tool-{action.lower()}-{case.business_case_id}-"
                f"v{case.case_version}"
            )
        )
        self.workflow.execute_action(
            case.business_case_id,
            request_id,
            action,
            case.case_version,
        )
        return self._summary(
            self.workflow.get_case(case.business_case_id)
        )

    def _advance_current(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._summary(self.workflow.advance(self._case_id(payload)))

    @staticmethod
    def _case_id(payload: dict[str, Any]) -> str:
        case_id = str(payload.get("business_case_id") or "").strip()
        if not case_id:
            raise ValueError("business_case_id is required")
        return case_id

    @staticmethod
    def _summary(case: BusinessCaseSnapshot) -> dict[str, Any]:
        return {
            "business_case_id": case.business_case_id,
            "stage": case.stage.value,
            "case_version": case.case_version,
            "declaration_version_count": len(case.declaration_versions),
            "receipt_count": len(case.receipts),
            "allowed_actions": case.allowed_actions,
            "case_source": case.case_source,
            "input_declaration_fingerprint": (
                case.input_declaration_fingerprint
            ),
            "input_declaration_summary": case.input_declaration_summary,
            "latest_event": (
                case.timeline[-1].model_dump(mode="json")
                if case.timeline
                else None
            ),
            "mock": True,
        }

    @staticmethod
    def _diff(left: Any, right: Any, prefix: str = "") -> list[dict[str, Any]]:
        if isinstance(left, dict) and isinstance(right, dict):
            differences: list[dict[str, Any]] = []
            for key in sorted(set(left) | set(right)):
                path = f"{prefix}.{key}" if prefix else key
                differences.extend(
                    DeclarationAgentToolset._diff(
                        left.get(key), right.get(key), path
                    )
                )
            return differences
        if isinstance(left, list) and isinstance(right, list):
            differences = []
            for index in range(max(len(left), len(right))):
                l_value = left[index] if index < len(left) else None
                r_value = right[index] if index < len(right) else None
                differences.extend(
                    DeclarationAgentToolset._diff(
                        l_value, r_value, f"{prefix}[{index}]"
                    )
                )
            return differences
        if left != right:
            return [{"field": prefix, "before": left, "after": right}]
        return []
