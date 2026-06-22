from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .authority import PersistentCustomsAuthority
from .models import DeclarationData


PROMPT_PATH = Path(__file__).parent / "prompts" / "goods_classifier_v1.txt"
CLASSIFIER_SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()


class GoodsCandidate(BaseModel):
    item_no: int
    candidate_hs_codes: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0, le=1)
    basis: str
    required_declaration_elements: list[str] = Field(default_factory=list)
    regulatory_hints: list[str] = Field(default_factory=list)
    ambiguity: list[str] = Field(default_factory=list)


class GoodsClassification(BaseModel):
    candidates: list[GoodsCandidate]
    mock: bool = True


class ClassificationState(TypedDict, total=False):
    prompt: str
    raw_response: Any
    result: GoodsClassification
    error: str
    attempts: int


class GoodsClassificationAgent:
    prompt_version = "goods-classifier-1.0"

    def __init__(self, authority: PersistentCustomsAuthority):
        self.authority = authority
        graph = StateGraph(ClassificationState)
        graph.add_node("call_model", self._call_model)
        graph.add_node("validate", self._validate)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", "validate")
        graph.add_conditional_edges(
            "validate",
            self._route,
            {"done": END, "retry": "call_model", "failed": END},
        )
        self.graph = graph.compile()

    def _call_model(self, state: ClassificationState) -> ClassificationState:
        attempts = int(state.get("attempts") or 0) + 1
        if self.authority.llm is None:
            return {
                "attempts": attempts,
                "error": "GOODS_CLASSIFIER_UNAVAILABLE",
            }
        prompt = state["prompt"]
        if state.get("error"):
            prompt += (
                "\n\n上次输出未通过 Schema，请严格返回 candidates 对象数组。"
            )
        try:
            response = self.authority.llm.invoke(
                [
                    SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            return {
                "raw_response": response.content,
                "attempts": attempts,
                "error": "",
            }
        except Exception as exc:
            return {
                "attempts": attempts,
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _validate(state: ClassificationState) -> ClassificationState:
        if not state.get("raw_response"):
            return {}
        try:
            payload = PersistentCustomsAuthority._extract_json(
                state["raw_response"]
            )
            result = GoodsClassification.model_validate(payload)
            return {"result": result, "error": ""}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _route(state: ClassificationState) -> str:
        if state.get("result") is not None:
            return "done"
        if int(state.get("attempts") or 0) < 2:
            return "retry"
        return "failed"

    def classify(self, declaration: DeclarationData) -> dict[str, Any]:
        goods_payload = [
            {
                "item_no": item.item_no,
                "name": item.name,
                "declared_hs_code": item.hs_code,
                "brand": item.brand,
                "model": item.model,
                "material": item.material,
                "usage": item.usage,
                "quantity_unit": item.quantity_unit,
                "origin_country": item.origin_country,
                "declaration_elements": item.declaration_elements,
            }
            for item in declaration.goods
        ]
        state = self.graph.invoke(
            {
                "prompt": json.dumps(
                    {"goods": goods_payload}, ensure_ascii=False
                ),
                "attempts": 0,
                "error": "",
            }
        )
        if state.get("result") is not None:
            return {
                **state["result"].model_dump(mode="json"),
                "model_invoked": True,
                "fallback_used": False,
                "attempt_count": state.get("attempts", 1),
                "model_version": self.authority.model_version,
                "prompt_version": self.prompt_version,
            }
        return {
            "candidates": [
                {
                    "item_no": item.item_no,
                    "candidate_hs_codes": [item.hs_code or "UNDETERMINED"],
                    "confidence": 0.5 if item.hs_code else 0,
                    "basis": "大模型不可用，保留企业申报码作为待复核候选。",
                    "required_declaration_elements": ["品牌", "型号", "用途", "材质"],
                    "regulatory_hints": item.regulatory_codes,
                    "ambiguity": ["需要人工复核正式税则和归类决定"],
                }
                for item in declaration.goods
            ],
            "mock": True,
            "model_invoked": self.authority.is_llm_enabled,
            "fallback_used": True,
            "attempt_count": state.get("attempts", 0),
            "model_version": self.authority.model_version,
            "prompt_version": self.prompt_version,
            "error": state.get("error"),
        }
