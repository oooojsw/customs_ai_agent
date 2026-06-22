from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import DeclarationData, RuleFinding


class KnowledgeRuleCondition(BaseModel):
    field: str
    operator: Literal[
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "contains",
        "regex",
    ]
    value: Any


class KnowledgeRuleDefinition(BaseModel):
    code: str
    stage: str
    severity: str
    blocking: bool = False
    message: str
    field: str | None = None
    scope: Literal["declaration", "goods"] = "goods"
    all: list[KnowledgeRuleCondition] = Field(default_factory=list)
    any: list[KnowledgeRuleCondition] = Field(default_factory=list)


class KnowledgeRulePack(BaseModel):
    pack_id: str
    version: str
    enabled: bool = True
    rules: list[KnowledgeRuleDefinition] = Field(default_factory=list)


class KnowledgeRulePackLoader:
    """Load declarative customs risk rules from the knowledge directory."""

    def __init__(self, rule_dir: str | Path | None = None):
        self.rule_dir = Path(rule_dir or self.default_rule_dir())

    @staticmethod
    def default_rule_dir() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "data"
            / "knowledge"
            / "customs_rules"
        )

    def load(self) -> list[KnowledgeRulePack]:
        if not self.rule_dir.exists():
            return []
        packs: list[KnowledgeRulePack] = []
        for path in sorted(self.rule_dir.glob("*.json")):
            raw = path.read_text(encoding="utf-8-sig")
            pack = KnowledgeRulePack.model_validate(json.loads(raw))
            if pack.enabled:
                packs.append(pack)
        return packs

    @property
    def version(self) -> str:
        packs = self.load()
        return "+".join(
            f"{pack.pack_id}@{pack.version}" for pack in packs
        ) or "no-knowledge-rules"

    def evaluate(
        self,
        declaration: DeclarationData,
        stage: str,
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        for pack in self.load():
            for rule in pack.rules:
                if rule.stage != stage:
                    continue
                targets: list[Any] = (
                    list(declaration.goods)
                    if rule.scope == "goods"
                    else [declaration]
                )
                for index, target in enumerate(targets):
                    if not self._matches(rule, target, declaration):
                        continue
                    field = rule.field
                    if field and rule.scope == "goods":
                        field = f"goods[{index}].{field}"
                    findings.append(
                        RuleFinding(
                            code=rule.code,
                            severity=rule.severity,
                            stage=rule.stage,
                            message=rule.message,
                            field=field,
                            blocking=rule.blocking,
                        )
                    )
        return findings

    def _matches(
        self,
        rule: KnowledgeRuleDefinition,
        target: Any,
        declaration: DeclarationData,
    ) -> bool:
        all_matches = all(
            self._condition_matches(condition, target, declaration)
            for condition in rule.all
        )
        any_matches = (
            not rule.any
            or any(
                self._condition_matches(condition, target, declaration)
                for condition in rule.any
            )
        )
        return all_matches and any_matches

    def _condition_matches(
        self,
        condition: KnowledgeRuleCondition,
        target: Any,
        declaration: DeclarationData,
    ) -> bool:
        source = declaration if condition.field.startswith("declaration.") else target
        field = condition.field.removeprefix("declaration.")
        actual = self._read_field(source, field)
        expected = condition.value
        operator = condition.operator
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        if operator in {"gt", "gte", "lt", "lte"}:
            try:
                left = float(actual)
                right = float(expected)
            except (TypeError, ValueError):
                return False
            return {
                "gt": left > right,
                "gte": left >= right,
                "lt": left < right,
                "lte": left <= right,
            }[operator]
        if operator == "in":
            return actual in expected if isinstance(expected, list) else False
        if operator == "contains":
            if isinstance(actual, list):
                return expected in actual
            return str(expected).lower() in str(actual or "").lower()
        if operator == "regex":
            return bool(re.search(str(expected), str(actual or ""), re.IGNORECASE))
        return False

    @staticmethod
    def _read_field(source: Any, field: str) -> Any:
        current = source
        for part in field.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                break
        return current
