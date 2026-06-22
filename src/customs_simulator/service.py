from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .authority import (
    AuthorityDecision,
    AuthorityResolution,
    PersistentCustomsAuthority,
)
from .classifier import GoodsClassificationAgent
from .fixtures import MockCaseFixtureLoader
from .models import (
    BusinessCaseSnapshot,
    CustomsReceipt,
    CustomsStage,
    DeclarationData,
    DeclarationVersion,
    InspectionRecord,
    MockDocument,
    RuleFinding,
    TaxAssessment,
    TimelineEvent,
    utc_now_iso,
)
from .repository import SQLiteCustomsCaseRepository
from .rules import CustomsRuleEngine
from .state_machine import allowed_actions, ensure_transition


ProgressCallback = Callable[[BusinessCaseSnapshot, TimelineEvent], None]


class MockCustomsWorkflowService:
    """Persistent, deterministic end-to-end import declaration simulator."""

    def __init__(
        self,
        database_path: str | Path,
        fixture_dir: str | Path,
        repository: SQLiteCustomsCaseRepository | None = None,
        rule_engine: CustomsRuleEngine | None = None,
        authority: PersistentCustomsAuthority | None = None,
    ):
        self.repository = repository or SQLiteCustomsCaseRepository(database_path)
        self.fixtures = MockCaseFixtureLoader(fixture_dir)
        self.rules = rule_engine or CustomsRuleEngine()
        self.authority = authority or PersistentCustomsAuthority()
        self.classifier = GoodsClassificationAgent(self.authority)
        self._action_lock = threading.RLock()

    def configure_authority(self, llm_config: dict[str, Any]) -> None:
        self.authority = PersistentCustomsAuthority(llm_config=llm_config)
        self.classifier = GoodsClassificationAgent(self.authority)

    def record_analysis_result(
        self,
        business_case_id: str,
        key: str,
        result: dict[str, Any],
        summary: str,
    ) -> BusinessCaseSnapshot:
        case = self.repository.get(business_case_id)
        expected_version = case.case_version
        case.analysis_results[key] = result
        self._append_event(
            case,
            f"{key}_completed",
            "declaration_agent",
            summary,
            {
                "analysis_key": key,
                "model_version": result.get("model_version"),
                "prompt_version": result.get("prompt_version"),
                "model_invoked": result.get("model_invoked", False),
                "fallback_used": result.get("fallback_used", False),
            },
        )
        case.updated_at = utc_now_iso()
        return self.repository.save(case, expected_version)

    def create_case(
        self,
        mock_case_id: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        request_id: str | None = None,
    ) -> BusinessCaseSnapshot:
        if request_id:
            existing_case_id = self.repository.get_case_id_for_request(
                tenant_id, request_id
            )
            if existing_case_id:
                return self.repository.get(existing_case_id)
        fixture = self.fixtures.load(mock_case_id)
        declaration = DeclarationData.model_validate(fixture["declaration"])
        documents = [
            MockDocument.model_validate(document)
            for document in fixture.get("documents", [])
        ]
        case_id = f"MOCK-CASE-{uuid4().hex[:12].upper()}"
        snapshot = BusinessCaseSnapshot(
            business_case_id=case_id,
            customs_case_id=case_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            mock_case_id=mock_case_id,
            case_source="fixed_fixture",
            declaration_versions=[
                DeclarationVersion(
                    version_id=f"{case_id}-DECL-V1",
                    version_no=1,
                    declaration=declaration,
                    reason="加载结构化 Mock 单证生成初始申报版本",
                )
            ],
            documents=documents,
            case_summary=str(fixture.get("description") or ""),
            input_declaration_fingerprint=self._declaration_fingerprint(
                declaration
            ),
            input_declaration_summary=self._declaration_summary(declaration),
            workflow_config={
                key: fixture[key]
                for key in (
                    "automatic_corrections",
                    "acceptance_requires_supplement",
                    "license_review_passes",
                    "force_inspection",
                    "random_inspection_rate",
                    "price_evidence",
                    "inspection_result",
                    "inspection_differences",
                    "exchange_rate",
                    "duty_rate",
                    "vat_rate",
                )
                if key in fixture
            },
        )
        self._append_event(
            snapshot,
            "case_created",
            "declaration_agent",
            f"已创建一般贸易进口模拟业务 {case_id}",
            {"mock_case_id": mock_case_id},
        )
        snapshot.allowed_actions = allowed_actions(snapshot.stage)
        created = self.repository.create(snapshot)
        if request_id:
            self.repository.save_case_request(
                tenant_id, request_id, created.business_case_id
            )
        return created

    def create_case_from_data(
        self,
        declaration_data: dict[str, Any],
        documents_data: list[dict[str, Any]],
        tenant_id: str,
        user_id: str,
        session_id: str,
        request_id: str | None = None,
        workflow_config: dict[str, Any] | None = None,
    ) -> BusinessCaseSnapshot:
        if request_id:
            existing_case_id = self.repository.get_case_id_for_request(
                tenant_id, request_id
            )
            if existing_case_id:
                return self.repository.get(existing_case_id)
        declaration = DeclarationData.model_validate(declaration_data)
        documents = [
            MockDocument.model_validate(document)
            for document in documents_data
        ]
        case_id = f"MOCK-CASE-{uuid4().hex[:12].upper()}"
        snapshot = BusinessCaseSnapshot(
            business_case_id=case_id,
            customs_case_id=case_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            mock_case_id="custom_structured_case",
            case_source="custom_declaration",
            trade_mode=declaration.trade_mode,
            declaration_versions=[
                DeclarationVersion(
                    version_id=f"{case_id}-DECL-V1",
                    version_no=1,
                    declaration=declaration,
                    reason="使用平台提交的结构化单证生成初始申报版本",
                )
            ],
            documents=documents,
            case_summary="平台提交的自定义一般贸易进口结构化案件",
            input_declaration_fingerprint=self._declaration_fingerprint(
                declaration
            ),
            input_declaration_summary=self._declaration_summary(declaration),
            workflow_config=workflow_config or {},
        )
        self._append_event(
            snapshot,
            "case_created",
            "declaration_agent",
            f"已创建自定义一般贸易进口模拟业务 {case_id}",
            {"data_source": "structured_platform_input"},
        )
        snapshot.allowed_actions = allowed_actions(snapshot.stage)
        created = self.repository.create(snapshot)
        if request_id:
            self.repository.save_case_request(
                tenant_id, request_id, created.business_case_id
            )
        return created

    @staticmethod
    def _declaration_fingerprint(declaration: DeclarationData) -> str:
        canonical = declaration.model_dump_json(exclude_none=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _declaration_summary(declaration: DeclarationData) -> dict[str, Any]:
        return {
            "entry_id": declaration.entry_id,
            "goods": [
                {
                    "item_no": item.item_no,
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
        }

    def get_case(self, business_case_id: str) -> BusinessCaseSnapshot:
        return self.repository.get(business_case_id)

    def get_workflow_config(
        self, case: BusinessCaseSnapshot
    ) -> dict[str, Any]:
        try:
            return self.fixtures.load(case.mock_case_id)
        except FileNotFoundError:
            return dict(case.workflow_config)

    def run_full_workflow(
        self,
        mock_case_id: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        request_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BusinessCaseSnapshot:
        case = self.create_case(
            mock_case_id,
            tenant_id,
            user_id,
            session_id,
            request_id,
        )
        fixture = self.get_workflow_config(case)
        max_steps = 30
        for _ in range(max_steps):
            if case.stage in {
                CustomsStage.CLOSED,
                CustomsStage.REJECTED,
                CustomsStage.CANCELLED,
            }:
                return case
            case = self.advance(case.business_case_id, fixture, on_progress)
        raise RuntimeError("CUSTOMS_WORKFLOW_MAX_STEPS_EXCEEDED")

    def advance(
        self,
        business_case_id: str,
        fixture: dict[str, Any] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BusinessCaseSnapshot:
        case = self.repository.get(business_case_id)
        if fixture is None:
            fixture = self.get_workflow_config(case)
        expected_version = case.case_version

        if case.stage == CustomsStage.DRAFT:
            case = self._transition(
                case,
                CustomsStage.DOCUMENTS_READY,
                "documents_loaded",
                "declaration_agent",
                "合同、发票、装箱单和提运单结构化材料已加载",
            )
        elif case.stage == CustomsStage.DOCUMENTS_READY:
            document_types = {document.document_type for document in case.documents}
            findings = self.rules.validate_documents(
                case.current_declaration.declaration, document_types
            )
            case.findings.extend(findings)
            if any(finding.blocking for finding in findings):
                raise ValueError("DOCUMENT_SET_INCOMPLETE")
            case = self._transition(
                case,
                CustomsStage.PRECHECK_PASSED,
                "precheck_completed",
                "declaration_agent",
                "单证完整性和金额勾稽检查通过",
                {"rule_version": self.rules.effective_version},
            )
        elif case.stage == CustomsStage.PRECHECK_PASSED:
            case = self._transition(
                case,
                CustomsStage.READY_TO_SUBMIT,
                "declaration_built",
                "declaration_agent",
                f"已生成申报草稿 V{case.current_declaration.version_no}",
            )
        elif case.stage == CustomsStage.READY_TO_SUBMIT:
            case = self._transition(
                case,
                CustomsStage.SUBMITTED,
                "declaration_submitted",
                "declaration_agent",
                f"已向海关模拟窗口提交 {case.current_declaration.version_id}",
            )
        elif case.stage == CustomsStage.SUBMITTED:
            if (
                fixture.get("acceptance_requires_supplement", False)
                and "SUPPLEMENT_COMPLETED" not in case.resolved_reason_codes
            ):
                case = self._run_authority_transition(
                    case,
                    CustomsStage.SUPPLEMENT_REQUIRED,
                    "REQUEST_SUPPLEMENT",
                    "declaration_acceptance",
                    "海关模拟受理窗口要求补充结构化情况说明。",
                    reason_codes=["SUPPLEMENT_REQUIRED"],
                    required_actions=[{"action": "SUBMIT_SUPPLEMENT"}],
                    risk_level="medium",
                    receipt_type="CUSTOMS_SUPPLEMENT_NOTICE",
                )
            else:
                findings = self.rules.validate_acceptance(
                    case.current_declaration.declaration
                )
                case.findings.extend(findings)
                fallback = self.authority.decide_acceptance(case, findings)
                allowed_decisions = [fallback.decision]
                self._record_authority_context(
                    case,
                    findings,
                    allowed_decisions,
                    "PROCESS_ACCEPTANCE",
                )
                resolution = self.authority.resolve_decision(
                    case,
                    findings,
                    allowed_decisions,
                    "PROCESS_ACCEPTANCE",
                    fallback,
                )
                case = self._apply_decision(case, resolution)
        elif case.stage == CustomsStage.SUPPLEMENT_REQUIRED:
            case.resolved_reason_codes.append("SUPPLEMENT_COMPLETED")
            self._append_event(
                case,
                "supplement_submitted",
                "declaration_agent",
                "已提交商品用途和交易背景 Mock 补充说明",
            )
            case = self._run_authority_transition(
                case,
                CustomsStage.SUBMITTED,
                "RECEIVE_SUPPLEMENT",
                "declaration_acceptance",
                "补充材料已收悉，重新进入海关模拟受理。",
                reason_codes=["SUPPLEMENT_RECEIVED"],
                required_actions=[{"action": "PROCESS_ACCEPTANCE"}],
                risk_level="medium",
                receipt_type="CUSTOMS_SUPPLEMENT_RECEIPT",
            )
        elif case.stage == CustomsStage.RETURNED:
            corrections = fixture.get("automatic_corrections", {})
            if not corrections:
                raise ValueError("CUSTOMS_SUBMISSION_RETURNED")
            case = self._amend(case, corrections)
            case = self._transition(
                case,
                CustomsStage.READY_TO_SUBMIT,
                "declaration_amended",
                "declaration_agent",
                f"已根据退单回执生成申报版本 V{case.current_declaration.version_no}",
                {"corrections": corrections},
            )
        elif case.stage == CustomsStage.ACCEPTED:
            case = self._run_authority_transition(
                case,
                CustomsStage.UNDER_REVIEW,
                "START_CUSTOMS_REVIEW",
                "customs_review",
                "海关模拟审单岗位开始审核",
                required_actions=[{"action": "PROCESS_REVIEW"}],
                risk_level=case.risk_level if case.risk_level != "unknown" else "low",
                receipt_type="CUSTOMS_REVIEW_STARTED_NOTICE",
            )
        elif case.stage == CustomsStage.UNDER_REVIEW:
            findings = [
                finding
                for finding in self.rules.review(
                    case.current_declaration.declaration
                )
                if finding.code not in case.resolved_reason_codes
            ]
            if len(case.declaration_versions) >= 3:
                findings.append(
                    RuleFinding(
                        code="REPEATED_DECLARATION_AMENDMENT",
                        severity="medium",
                        stage="customs_review",
                        message="该票申报已多次修改，建议加强人工复核",
                    )
                )
            case.findings.extend(findings)
            force_inspection = self.rules.requires_inspection(
                findings,
                bool(fixture.get("force_inspection", False)),
            ) or self.rules.deterministic_random_inspection(
                case.business_case_id,
                float(fixture.get("random_inspection_rate", 0)),
            )
            fallback = self.authority.decide_review(
                case,
                findings,
                force_inspection,
            )
            allowed_decisions = [fallback.decision]
            self._record_authority_context(
                case,
                findings,
                allowed_decisions,
                "PROCESS_REVIEW",
            )
            resolution = self.authority.resolve_decision(
                case,
                findings,
                allowed_decisions,
                "PROCESS_REVIEW",
                fallback,
            )
            decision = resolution.decision
            if decision.decision == CustomsStage.TAX_ASSESSED:
                case.tax_assessment = self._assess_tax(case, fixture)
            case = self._apply_decision(case, resolution)
        elif case.stage == CustomsStage.PRICE_QUERY:
            case.resolved_reason_codes.extend(
                finding.code
                for finding in case.findings
                if finding.code.startswith("PRICE_")
                and finding.code not in case.resolved_reason_codes
            )
            self._append_event(
                case,
                "price_query_responded",
                "declaration_agent",
                "已提交合同、发票和折扣协议作为模拟价格说明",
                {"evidence": fixture.get("price_evidence", ["contract", "invoice"])},
            )
            if fixture.get("force_inspection", False):
                case = self._run_authority_transition(
                    case,
                    CustomsStage.INSPECTION_REQUIRED,
                    "REVIEW_PRICE_RESPONSE",
                    "price_review",
                    "价格说明已收悉，但该票仍命中查验布控。",
                    reason_codes=["PRICE_RISK_REQUIRES_INSPECTION"],
                    required_actions=[{"action": "SCHEDULE_INSPECTION"}],
                    risk_level="high",
                    receipt_type="CUSTOMS_INSPECTION_NOTICE",
                )
            else:
                case = self._run_authority_transition(
                    case,
                    CustomsStage.UNDER_REVIEW,
                    "REVIEW_PRICE_RESPONSE",
                    "price_review",
                    "模拟价格说明已接受，返回海关审单阶段。",
                    reason_codes=["PRICE_EXPLANATION_ACCEPTED"],
                    required_actions=[{"action": "PROCESS_REVIEW"}],
                    risk_level="medium",
                    receipt_type="CUSTOMS_PRICE_RESPONSE_RECEIPT",
                )
        elif case.stage == CustomsStage.LICENSE_REVIEW:
            if fixture.get("license_review_passes", False):
                if "LICENSE_REQUIRED" not in case.resolved_reason_codes:
                    case.resolved_reason_codes.append("LICENSE_REQUIRED")
                case = self._run_authority_transition(
                    case,
                    CustomsStage.UNDER_REVIEW,
                    "VERIFY_LICENSE",
                    "license_review",
                    "模拟许可证信息已补充并通过核验",
                    reason_codes=["LICENSE_VERIFIED"],
                    required_actions=[{"action": "PROCESS_REVIEW"}],
                    risk_level="medium",
                    receipt_type="CUSTOMS_LICENSE_VERIFICATION_RECEIPT",
                )
            else:
                case = self._run_authority_transition(
                    case,
                    CustomsStage.REJECTED,
                    "VERIFY_LICENSE",
                    "license_review",
                    "未能提供有效许可证，海关模拟案件拒绝放行",
                    reason_codes=["LICENSE_REQUIRED"],
                    risk_level="high",
                    receipt_type="CUSTOMS_REJECTION_NOTICE",
                )
        elif case.stage == CustomsStage.INSPECTION_REQUIRED:
            case.inspection = InspectionRecord(
                reason_codes=[
                    finding.code
                    for finding in case.findings
                    if finding.severity == "high"
                ]
                or ["SEEDED_INSPECTION"],
                directive="核对品名、型号、数量、重量和价格证据",
                inspection_items=[
                    "品名及规格型号",
                    "数量和包装",
                    "毛重及净重",
                    "价格证明材料",
                ],
                scheduled_at=utc_now_iso(),
            )
            case = self._transition(
                case,
                CustomsStage.INSPECTION_SCHEDULED,
                "inspection_scheduled",
                "declaration_agent",
                "已确认模拟查验安排",
            )
        elif case.stage == CustomsStage.INSPECTION_SCHEDULED:
            inspection_result = str(
                fixture.get("inspection_result", "MATCHED")
            ).upper()
            assert case.inspection is not None
            case.inspection.result = inspection_result
            case.inspection.differences = list(
                fixture.get("inspection_differences", [])
            )
            case = self._run_authority_transition(
                case,
                CustomsStage.INSPECTION_COMPLETED,
                "CONFIRM_INSPECTION_RESULT",
                "inspection",
                f"模拟查验完成，结果：{inspection_result}",
                reason_codes=case.inspection.reason_codes,
                required_actions=[{"action": "ASSESS_TAX"}],
                risk_level="medium",
                receipt_type="CUSTOMS_INSPECTION_RESULT_NOTICE",
            )
        elif case.stage == CustomsStage.INSPECTION_COMPLETED:
            if case.inspection and case.inspection.result == "REJECTED":
                case.inspection.disposition = CustomsStage.REJECTED.value
                case = self._run_authority_transition(
                    case,
                    CustomsStage.REJECTED,
                    "DISPOSE_INSPECTION",
                    "inspection",
                    "模拟查验发现重大不符，案件终止",
                    reason_codes=["INSPECTION_REJECTED"],
                    risk_level="high",
                    receipt_type="CUSTOMS_REJECTION_NOTICE",
                )
            else:
                if case.inspection:
                    case.inspection.disposition = CustomsStage.TAX_ASSESSED.value
                case.tax_assessment = self._assess_tax(case, fixture)
                case = self._run_authority_transition(
                    case,
                    CustomsStage.TAX_ASSESSED,
                    "DISPOSE_INSPECTION",
                    "inspection",
                    f"查验处置完成，核定税费 {case.tax_assessment.total_tax:.2f} CNY",
                    reason_codes=["INSPECTION_MATCHED"],
                    required_actions=[{"action": "ISSUE_TAX_BILL"}],
                    risk_level="low",
                    receipt_type="CUSTOMS_TAX_ASSESSMENT_NOTICE",
                )
        elif case.stage == CustomsStage.TAX_ASSESSED:
            case = self._run_authority_transition(
                case,
                CustomsStage.PAYMENT_PENDING,
                "ISSUE_TAX_BILL",
                "tax_collection",
                f"模拟税单已生成，应缴 {case.tax_assessment.total_tax:.2f} CNY",
                reason_codes=["TAX_BILL_ISSUED"],
                required_actions=[{"action": "PAY_TAX"}],
                risk_level=case.risk_level,
                receipt_type="CUSTOMS_TAX_BILL",
            )
        elif case.stage == CustomsStage.PAYMENT_PENDING:
            assert case.tax_assessment is not None
            case.tax_assessment.status = "PAID"
            case.tax_assessment.payment_reference = (
                f"MOCK-PAY-{uuid4().hex[:12].upper()}"
            )
            case = self._transition(
                case,
                CustomsStage.TAX_PAID,
                "tax_paid",
                "declaration_agent",
                f"模拟税费支付成功，流水 {case.tax_assessment.payment_reference}",
            )
        elif case.stage == CustomsStage.TAX_PAID:
            release_findings = self.rules.validate_release(case)
            if release_findings:
                case.findings.extend(release_findings)
                raise ValueError("RELEASE_CONDITIONS_NOT_MET")
            case = self._run_authority_transition(
                case,
                CustomsStage.RELEASED,
                "CONFIRM_RELEASE",
                "release",
                "全部模拟放行条件满足，海关已放行",
                reason_codes=["RELEASE_CONDITIONS_MET"],
                required_actions=[{"action": "PICK_UP"}],
                risk_level="low",
                receipt_type="CUSTOMS_RELEASE_NOTICE",
            )
        elif case.stage == CustomsStage.RELEASED:
            case = self._transition(
                case,
                CustomsStage.PICKED_UP,
                "goods_picked_up",
                "declaration_agent",
                "已完成模拟港区提货",
            )
        elif case.stage == CustomsStage.PICKED_UP:
            case = self._run_authority_transition(
                case,
                CustomsStage.CLOSED,
                "CLOSE_CASE",
                "clearance",
                "一般贸易进口模拟业务已结关归档",
                reason_codes=["CASE_ARCHIVED"],
                risk_level="low",
                receipt_type="CUSTOMS_CLEARANCE_NOTICE",
            )
        else:
            raise ValueError(f"CUSTOMS_ACTION_NOT_ALLOWED: {case.stage.value}")

        case.allowed_actions = allowed_actions(case.stage)
        case.updated_at = utc_now_iso()
        saved = self.repository.save(case, expected_version)
        if on_progress and saved.timeline:
            on_progress(saved, saved.timeline[-1])
        return saved

    def cancel(self, business_case_id: str) -> BusinessCaseSnapshot:
        case = self.repository.get(business_case_id)
        expected_version = case.case_version
        case = self._transition(
            case,
            CustomsStage.CANCELLED,
            "case_cancelled",
            "declaration_agent",
            "用户取消了模拟报关流程",
        )
        case.allowed_actions = []
        case.updated_at = utc_now_iso()
        return self.repository.save(case, expected_version)

    def execute_action(
        self,
        business_case_id: str,
        request_id: str,
        action: str,
        expected_case_version: int,
    ) -> dict[str, Any]:
        """Execute one idempotent protocol action under an optimistic lock."""
        with self._action_lock:
            existing = self.repository.get_action_result(
                business_case_id, request_id
            )
            if existing is not None:
                return existing
            case = self.get_case(business_case_id)
            if case.case_version != expected_case_version:
                from .repository import CaseVersionConflictError

                raise CaseVersionConflictError(business_case_id)
            if action == "CANCEL":
                updated = self.cancel(business_case_id)
            else:
                if action not in case.allowed_actions:
                    raise ValueError(
                        f"CUSTOMS_ACTION_NOT_ALLOWED: {action}; "
                        f"allowed={case.allowed_actions}"
                    )
                updated = self.advance(business_case_id)
            result = {
                "business_case_id": updated.business_case_id,
                "case_version": updated.case_version,
                "status": updated.stage.value,
                "allowed_actions": updated.allowed_actions,
                "latest_event": updated.timeline[-1].model_dump(mode="json"),
                "latest_receipt": (
                    updated.receipts[-1].model_dump(mode="json")
                    if updated.receipts
                    else None
                ),
                "mock": True,
            }
            return self.repository.save_action_result(
                business_case_id, request_id, result
            )

    def _record_authority_context(
        self,
        case: BusinessCaseSnapshot,
        findings: list[RuleFinding],
        allowed_decisions: list[CustomsStage],
        requested_action: str,
    ) -> None:
        packet = self.authority.build_context_packet(
            case, findings, allowed_decisions, requested_action
        )
        self._append_event(
            case,
            "authority_context_rebuilt",
            "system",
            "已从持久化案件事实重建海关模拟智能体上下文",
            {
                "requested_action": requested_action,
                "allowed_decisions": packet["allowed_decisions"],
                "previous_receipt_count": len(packet["previous_receipts"]),
                "prompt_version": self.authority.prompt_version,
                "model_version": self.authority.model_version,
            },
        )

    def _transition(
        self,
        case: BusinessCaseSnapshot,
        target: CustomsStage,
        event_type: str,
        actor: str,
        summary: str,
        data: dict[str, Any] | None = None,
    ) -> BusinessCaseSnapshot:
        ensure_transition(case.stage, target)
        case.stage = target
        self._append_event(case, event_type, actor, summary, data)
        return case

    def _run_authority_transition(
        self,
        case: BusinessCaseSnapshot,
        target: CustomsStage,
        requested_action: str,
        window: str,
        message: str,
        reason_codes: list[str] | None = None,
        required_actions: list[dict[str, Any]] | None = None,
        risk_level: str = "low",
        receipt_type: str = "CUSTOMS_STATUS_NOTICE",
        findings: list[RuleFinding] | None = None,
    ) -> BusinessCaseSnapshot:
        fallback = AuthorityDecision(
            decision=target,
            window=window,
            reason_codes=reason_codes or [],
            message=message,
            required_actions=required_actions or [],
            risk_level=risk_level,
            next_stage=target,
            receipt_type=receipt_type,
            mock=True,
        )
        active_findings = findings or []
        self._record_authority_context(
            case,
            active_findings,
            [target],
            requested_action,
        )
        resolution = self.authority.resolve_decision(
            case,
            active_findings,
            [target],
            requested_action,
            fallback,
        )
        case = self._apply_decision(case, resolution)
        event_types = {
            "REQUEST_SUPPLEMENT": "supplement_required",
            "RECEIVE_SUPPLEMENT": "supplement_received",
            "START_CUSTOMS_REVIEW": "customs_review_started",
            "REVIEW_PRICE_RESPONSE": "price_response_decided",
            "VERIFY_LICENSE": "license_review_decided",
            "CONFIRM_INSPECTION_RESULT": "inspection_completed",
            "DISPOSE_INSPECTION": "inspection_disposed",
            "ISSUE_TAX_BILL": "tax_bill_issued",
            "CONFIRM_RELEASE": "customs_released",
            "CLOSE_CASE": "case_closed",
        }
        semantic_event = event_types.get(requested_action)
        if semantic_event:
            self._append_event(
                case,
                semantic_event,
                "customs_authority",
                resolution.decision.message,
                {
                    "decision": resolution.decision.decision.value,
                    "receipt_type": resolution.decision.receipt_type,
                    "model_version": resolution.model_version,
                    "prompt_version": resolution.prompt_version,
                },
            )
        return case

    def _apply_decision(
        self,
        case: BusinessCaseSnapshot,
        resolution: AuthorityResolution,
    ) -> BusinessCaseSnapshot:
        decision = resolution.decision
        case = self._transition(
            case,
            decision.decision,
            "customs_decision",
            "customs_authority",
            decision.message,
            {
                "window": decision.window,
                "reason_codes": decision.reason_codes,
                "required_actions": decision.required_actions,
                "risk_level": decision.risk_level,
                "receipt_type": decision.receipt_type,
                "prompt_version": self.authority.prompt_version,
                "model_version": self.authority.model_version,
                "model_invoked": resolution.model_invoked,
                "fallback_used": resolution.fallback_used,
                "attempt_count": resolution.attempt_count,
                "model_error": resolution.error,
                "rule_version": self.rules.effective_version,
            },
        )
        case.case_summary = (
            f"当前阶段 {case.stage.value}；最新海关窗口 {decision.window}；"
            f"裁决 {decision.decision.value}；风险 {decision.risk_level}；"
            f"回执摘要：{decision.message}"
        )
        case.current_window = decision.window
        case.risk_level = decision.risk_level
        self._append_receipt(
            case,
            receipt_type=decision.receipt_type,
            window=decision.window,
            decision=decision.decision.value,
            message=decision.message,
            reason_codes=decision.reason_codes,
            required_actions=decision.required_actions,
            metadata={
                "model_invoked": resolution.model_invoked,
                "fallback_used": resolution.fallback_used,
                "attempt_count": resolution.attempt_count,
                "model_version": resolution.model_version,
                "prompt_version": resolution.prompt_version,
                "model_error": resolution.error,
            },
        )
        return case

    def _append_receipt(
        self,
        case: BusinessCaseSnapshot,
        receipt_type: str,
        window: str,
        decision: str,
        message: str,
        reason_codes: list[str] | None = None,
        required_actions: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        case.receipts.append(
            CustomsReceipt(
                receipt_id=f"MOCK-RECEIPT-{uuid4().hex[:12].upper()}",
                receipt_type=receipt_type,
                window=window,
                decision=decision,
                reason_codes=reason_codes or [],
                message=message,
                required_actions=required_actions or [],
                metadata=metadata or {},
                declaration_version_id=case.current_declaration.version_id,
            )
        )

    def _append_event(
        self,
        case: BusinessCaseSnapshot,
        event_type: str,
        actor: str,
        summary: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        case.timeline.append(
            TimelineEvent(
                business_case_id=case.business_case_id,
                customs_case_id=case.customs_case_id or case.business_case_id,
                sequence=len(case.timeline) + 1,
                stage=case.stage,
                event_type=event_type,
                actor=actor,
                summary=summary,
                data=data or {},
            )
        )

    def _amend(
        self, case: BusinessCaseSnapshot, corrections: dict[str, Any]
    ) -> BusinessCaseSnapshot:
        declaration_dict = case.current_declaration.declaration.model_dump()
        for path, value in corrections.items():
            self._set_path(declaration_dict, path, value)
        declaration = DeclarationData.model_validate(declaration_dict)
        version_no = case.current_declaration.version_no + 1
        case.declaration_versions.append(
            DeclarationVersion(
                version_id=f"{case.business_case_id}-DECL-V{version_no}",
                version_no=version_no,
                declaration=declaration,
                reason="根据海关模拟退单回执自动修改",
                source_version_id=case.current_declaration.version_id,
            )
        )
        return case

    @staticmethod
    def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
        if path.startswith("goods["):
            index_text, field_name = path[6:].split("].", 1)
            target["goods"][int(index_text)][field_name] = value
            return
        target[path] = value

    @staticmethod
    def _assess_tax(
        case: BusinessCaseSnapshot, fixture: dict[str, Any]
    ) -> TaxAssessment:
        declaration = case.current_declaration.declaration
        exchange_rate = float(fixture.get("exchange_rate", 7.2))
        customs_value = round(
            (
                sum(item.total_price for item in declaration.goods)
                + declaration.freight
                + declaration.insurance
            )
            * exchange_rate,
            2,
        )
        duty_rate = float(fixture.get("duty_rate", 0.05))
        vat_rate = float(fixture.get("vat_rate", 0.13))
        duty_amount = round(customs_value * duty_rate, 2)
        vat_amount = round((customs_value + duty_amount) * vat_rate, 2)
        return TaxAssessment(
            customs_value=customs_value,
            exchange_rate=exchange_rate,
            duty_rate=duty_rate,
            duty_amount=duty_amount,
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            total_tax=round(duty_amount + vat_amount, 2),
        )

    @staticmethod
    def _receipt_type(stage: CustomsStage) -> str:
        mapping = {
            CustomsStage.ACCEPTED: "CUSTOMS_ACCEPTANCE_NOTICE",
            CustomsStage.RETURNED: "CUSTOMS_RETURN_NOTICE",
            CustomsStage.SUPPLEMENT_REQUIRED: "CUSTOMS_SUPPLEMENT_NOTICE",
            CustomsStage.PRICE_QUERY: "CUSTOMS_PRICE_QUERY_NOTICE",
            CustomsStage.INSPECTION_REQUIRED: "CUSTOMS_INSPECTION_NOTICE",
            CustomsStage.LICENSE_REVIEW: "CUSTOMS_LICENSE_REVIEW_NOTICE",
            CustomsStage.TAX_ASSESSED: "CUSTOMS_TAX_ASSESSMENT_NOTICE",
            CustomsStage.REJECTED: "CUSTOMS_REJECTION_NOTICE",
        }
        return mapping.get(stage, "CUSTOMS_STATUS_NOTICE")

    @staticmethod
    def stable_case_seed(business_case_id: str) -> int:
        digest = hashlib.sha256(business_case_id.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)
