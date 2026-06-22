from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any
from typing_extensions import TypedDict

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from .models import BusinessCaseSnapshot, CustomsStage, RuleFinding


PROMPT_PATH = Path(__file__).parent / "prompts" / "customs_authority_v1.txt"
AUTHORITY_SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()


class AuthorityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: CustomsStage
    window: str
    reason_codes: list[str] = Field(default_factory=list)
    message: str
    required_actions: list[dict] = Field(default_factory=list)
    risk_level: str = "low"
    next_stage: CustomsStage
    receipt_type: str
    mock: bool = True


class AuthorityResolution(BaseModel):
    decision: AuthorityDecision
    model_invoked: bool
    fallback_used: bool
    attempt_count: int
    model_version: str
    prompt_version: str
    error: str | None = None


class AuthorityGraphState(TypedDict, total=False):
    prompt: str
    correction: str
    raw_response: Any
    decision: AuthorityDecision
    error: str
    attempts: int
    allowed_decisions: list[str]
    fallback: AuthorityDecision
    fallback_used: bool
    model_invoked: bool


class PersistentCustomsAuthority:
    """Persistent LangGraph authority agent constrained by deterministic rules."""

    prompt_version = "customs-authority-1.0"
    model_version = "deterministic-fallback-1.0"

    def __init__(
        self,
        decision_provider: Callable[[str], dict[str, Any]] | None = None,
        model_version: str | None = None,
        llm_config: dict[str, Any] | None = None,
    ):
        self.decision_provider = decision_provider
        self.llm = None
        if llm_config and llm_config.get("api_key"):
            self.model_version = str(llm_config.get("model") or "unknown")
            self._http_client = httpx.Client(verify=False, timeout=120.0)
            self.llm = ChatOpenAI(
                model=self.model_version,
                api_key=llm_config["api_key"],
                base_url=llm_config.get("base_url"),
                temperature=0,
                http_client=self._http_client,
                streaming=False,
            )
        elif model_version:
            self.model_version = model_version
        self.graph = self._build_graph()

    @property
    def is_llm_enabled(self) -> bool:
        return self.llm is not None or self.decision_provider is not None

    def _build_graph(self):
        graph = StateGraph(AuthorityGraphState)
        graph.add_node("call_model", self._call_model_node)
        graph.add_node("validate", self._validate_node)
        graph.add_node("fallback", self._fallback_node)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", "validate")
        graph.add_conditional_edges(
            "validate",
            self._route_after_validation,
            {
                "done": END,
                "retry": "call_model",
                "fallback": "fallback",
            },
        )
        graph.add_edge("fallback", END)
        return graph.compile()

    def _call_model_node(
        self, state: AuthorityGraphState
    ) -> AuthorityGraphState:
        attempts = int(state.get("attempts") or 0) + 1
        prompt = state["prompt"]
        correction = state.get("correction") or ""
        if correction:
            prompt = f"{prompt}\n\n纠错要求：{correction}"
        try:
            if self.decision_provider is not None:
                raw = self.decision_provider(prompt)
            elif self.llm is not None:
                response = self.llm.invoke(
                    [
                        SystemMessage(content=AUTHORITY_SYSTEM_PROMPT),
                        HumanMessage(content=prompt),
                    ]
                )
                raw = response.content
            else:
                raise RuntimeError("CUSTOMS_AGENT_UNAVAILABLE")
            return {
                "raw_response": raw,
                "attempts": attempts,
                "model_invoked": self.is_llm_enabled,
                "error": "",
            }
        except Exception as exc:
            return {
                "raw_response": None,
                "attempts": attempts,
                "model_invoked": self.is_llm_enabled,
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _extract_json(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("CUSTOMS_AGENT_INVALID_RESPONSE: JSON object missing")
        return json.loads(text[start : end + 1])

    def _validate_node(
        self, state: AuthorityGraphState
    ) -> AuthorityGraphState:
        if state.get("error"):
            return {
                "correction": "上次模型调用失败，请重新返回完整 JSON。",
            }
        try:
            decision = AuthorityDecision.model_validate(
                self._extract_json(state.get("raw_response"))
            )
            allowed = set(state["allowed_decisions"])
            if decision.decision.value not in allowed:
                raise ValueError("decision is outside allowed_decisions")
            if decision.next_stage != decision.decision:
                raise ValueError("next_stage must equal decision")
            if not decision.mock:
                raise ValueError("mock must be true")
            return {"decision": decision, "error": "", "correction": ""}
        except Exception as exc:
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "correction": (
                    "上次输出未通过 Schema 或状态约束。"
                    f"只能选择 {state['allowed_decisions']}，"
                    "next_stage 必须等于 decision，mock 必须为 true；"
                    "required_actions 必须是对象数组，例如 "
                    '[{"action":"START_REVIEW"}]，不能是字符串数组。'
                ),
            }

    @staticmethod
    def _route_after_validation(state: AuthorityGraphState) -> str:
        if state.get("decision") is not None:
            return "done"
        if int(state.get("attempts") or 0) < 2:
            return "retry"
        return "fallback"

    @staticmethod
    def _fallback_node(
        state: AuthorityGraphState,
    ) -> AuthorityGraphState:
        return {
            "decision": state["fallback"],
            "fallback_used": True,
        }

    def build_context_packet(
        self,
        case: BusinessCaseSnapshot,
        findings: list[RuleFinding],
        allowed_decisions: list[CustomsStage],
        requested_action: str,
    ) -> dict[str, Any]:
        """Rebuild the long-lived authority context from persisted case facts."""
        return {
            "business_case_id": case.business_case_id,
            "current_stage": case.stage.value,
            "requested_action": requested_action,
            "case_summary": case.case_summary,
            "context_version": case.context_version,
            "current_declaration": case.current_declaration.model_dump(mode="json"),
            "declaration_history": [
                version.model_dump(mode="json")
                for version in case.declaration_versions
            ],
            "documents": [
                document.model_dump(mode="json") for document in case.documents
            ],
            "analysis_results": case.analysis_results,
            "rule_findings": [
                finding.model_dump(mode="json") for finding in findings
            ],
            "all_rule_findings": [
                finding.model_dump(mode="json") for finding in case.findings
            ],
            "previous_receipts": [
                receipt.model_dump(mode="json") for receipt in case.receipts
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
            "recent_timeline": [
                event.model_dump(mode="json")
                for event in case.timeline[-30:]
            ],
            "resolved_reason_codes": case.resolved_reason_codes,
            "allowed_actions": case.allowed_actions,
            "allowed_decisions": [stage.value for stage in allowed_decisions],
            "forbidden_decisions": [
                stage.value
                for stage in CustomsStage
                if stage not in allowed_decisions
            ],
            "prompt_version": self.prompt_version,
            "mock": True,
        }

    def render_system_prompt(self, context_packet: dict[str, Any]) -> str:
        """Return the current action and persisted context for the graph."""
        return (
            "请根据系统身份和约束处理以下当前案件上下文包：\n"
            f"{json.dumps(context_packet, ensure_ascii=False, sort_keys=True)}"
        )

    def resolve_decision(
        self,
        case: BusinessCaseSnapshot,
        findings: list[RuleFinding],
        allowed_decisions: list[CustomsStage],
        requested_action: str,
        fallback: AuthorityDecision,
    ) -> AuthorityResolution:
        """Run the LangGraph authority workflow and return auditable metadata."""
        packet = self.build_context_packet(
            case, findings, allowed_decisions, requested_action
        )
        prompt = self.render_system_prompt(packet)
        result = self.graph.invoke(
            {
                "prompt": prompt,
                "allowed_decisions": [
                    decision.value for decision in allowed_decisions
                ],
                "fallback": fallback,
                "attempts": 0,
                "fallback_used": False,
                "model_invoked": False,
            }
        )
        return AuthorityResolution(
            decision=result["decision"],
            model_invoked=bool(result.get("model_invoked")),
            fallback_used=bool(result.get("fallback_used")),
            attempt_count=int(result.get("attempts") or 0),
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            error=result.get("error") or None,
        )

    def decide_acceptance(
        self, case: BusinessCaseSnapshot, findings: list[RuleFinding]
    ) -> AuthorityDecision:
        blocking = [finding for finding in findings if finding.blocking]
        if blocking:
            return AuthorityDecision(
                decision=CustomsStage.RETURNED,
                window="declaration_acceptance",
                reason_codes=sorted({finding.code for finding in blocking}),
                message="申报数据未通过受理校验，请按退单要求修改后重新申报。",
                required_actions=[
                    {
                        "action": "AMEND_DECLARATION",
                        "fields": [
                            finding.field for finding in blocking if finding.field
                        ],
                    }
                ],
                risk_level="high",
                next_stage=CustomsStage.RETURNED,
                receipt_type="CUSTOMS_RETURN_NOTICE",
            )
        return AuthorityDecision(
            decision=CustomsStage.ACCEPTED,
            window="declaration_acceptance",
            reason_codes=[],
            message="申报数据格式校验通过，海关已受理。",
            required_actions=[{"action": "START_REVIEW"}],
            risk_level="low",
            next_stage=CustomsStage.ACCEPTED,
            receipt_type="CUSTOMS_ACCEPTANCE_NOTICE",
        )

    def decide_review(
        self,
        case: BusinessCaseSnapshot,
        findings: list[RuleFinding],
        force_inspection: bool,
    ) -> AuthorityDecision:
        license_findings = [
            finding for finding in findings if finding.code == "LICENSE_REQUIRED"
        ]
        if license_findings:
            return AuthorityDecision(
                decision=CustomsStage.LICENSE_REVIEW,
                window="license_review",
                reason_codes=["LICENSE_REQUIRED"],
                message="商品涉及监管条件，需核验许可证信息。",
                required_actions=[{"action": "CONFIRM_LICENSE"}],
                risk_level="high",
                next_stage=CustomsStage.LICENSE_REVIEW,
                receipt_type="CUSTOMS_LICENSE_REVIEW_NOTICE",
            )
        price_findings = [
            finding
            for finding in findings
            if finding.code.startswith("PRICE_")
        ]
        if price_findings:
            return AuthorityDecision(
                decision=CustomsStage.PRICE_QUERY,
                window="price_review",
                reason_codes=sorted(
                    {finding.code for finding in price_findings}
                ),
                message="申报价格偏离 Mock 参考区间，请补充价格说明和折扣依据。",
                required_actions=[{"action": "RESPOND_PRICE_QUERY"}],
                risk_level="high",
                next_stage=CustomsStage.PRICE_QUERY,
                receipt_type="CUSTOMS_PRICE_QUERY_NOTICE",
            )
        if force_inspection:
            return AuthorityDecision(
                decision=CustomsStage.INSPECTION_REQUIRED,
                window="risk_control",
                reason_codes=["SEEDED_INSPECTION"],
                message="该票申报触发固定种子风险布控，需进入模拟查验。",
                required_actions=[{"action": "SCHEDULE_INSPECTION"}],
                risk_level="high",
                next_stage=CustomsStage.INSPECTION_REQUIRED,
                receipt_type="CUSTOMS_INSPECTION_NOTICE",
            )
        return AuthorityDecision(
            decision=CustomsStage.TAX_ASSESSED,
            window="customs_review",
            reason_codes=[],
            message="海关审单通过，进入税费核定。",
            required_actions=[{"action": "ISSUE_TAX_BILL"}],
            risk_level="low",
            next_stage=CustomsStage.TAX_ASSESSED,
            receipt_type="CUSTOMS_TAX_ASSESSMENT_NOTICE",
        )
