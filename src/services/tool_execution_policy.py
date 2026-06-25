from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ToolTimeoutLevel(str, Enum):
    FAST = "L1"
    STANDARD = "L2"
    LONG = "L3"
    DEEP = "L4"
    SUBAGENT = "L5"


@dataclass(frozen=True)
class ToolExecutionPolicy:
    level: ToolTimeoutLevel
    timeout_seconds: float
    retry_limit: int
    description: str


LEVEL_POLICIES = {
    ToolTimeoutLevel.FAST: ToolExecutionPolicy(
        ToolTimeoutLevel.FAST, 30.0, 1, "本地查询、校验、计算和文件操作"
    ),
    ToolTimeoutLevel.STANDARD: ToolExecutionPolicy(
        ToolTimeoutLevel.STANDARD, 120.0, 1, "检索、归类和单次模型决策"
    ),
    ToolTimeoutLevel.LONG: ToolExecutionPolicy(
        ToolTimeoutLevel.LONG, 300.0, 0, "智能审单和完整业务流程"
    ),
    ToolTimeoutLevel.DEEP: ToolExecutionPolicy(
        ToolTimeoutLevel.DEEP, 1200.0, 0, "深度报告和复杂文件生成"
    ),
    ToolTimeoutLevel.SUBAGENT: ToolExecutionPolicy(
        ToolTimeoutLevel.SUBAGENT, 3600.0, 0, "外部子代理和复杂仓库任务"
    ),
}


TOOL_LEVELS: dict[str, ToolTimeoutLevel] = {
    "audit_declaration": ToolTimeoutLevel.LONG,
    "search_customs_regulations": ToolTimeoutLevel.STANDARD,
    "classify_goods": ToolTimeoutLevel.STANDARD,
    "process_customs_acceptance": ToolTimeoutLevel.STANDARD,
    "start_customs_review": ToolTimeoutLevel.STANDARD,
    "process_customs_review": ToolTimeoutLevel.STANDARD,
    "respond_to_price_query": ToolTimeoutLevel.STANDARD,
    "confirm_license_information": ToolTimeoutLevel.STANDARD,
    "submit_inspection_result": ToolTimeoutLevel.STANDARD,
    "assess_mock_customs_tax": ToolTimeoutLevel.STANDARD,
    "release_mock_goods": ToolTimeoutLevel.STANDARD,
    "close_import_case": ToolTimeoutLevel.STANDARD,
    "run_mock_import_workflow": ToolTimeoutLevel.LONG,
    "generate_compliance_report": ToolTimeoutLevel.DEEP,
    "export_document_file": ToolTimeoutLevel.DEEP,
    "delegate_to_opencode": ToolTimeoutLevel.SUBAGENT,
}


RUN_TIMEOUT_BY_INTENT: dict[str, int] = {
    "chat": 600,
    "audit": 600,
    "ocr": 300,
    "report": 1200,
    "declaration_query": 120,
    "regulation_search": 180,
    "batch_audit": 600,
    "full_review": 600,
    "mock_import_declaration": 300,
    # The unified auto entrypoint may select any registered capability,
    # including an L5 child agent. Individual tools still keep their own
    # shorter tier deadlines, so this is only the parent run ceiling.
    "auto": 3600,
}


def get_tool_policy(tool_name: str) -> ToolExecutionPolicy:
    level = TOOL_LEVELS.get(tool_name, ToolTimeoutLevel.FAST)
    return LEVEL_POLICIES[level]


def get_default_run_timeout(intent: str) -> int:
    return RUN_TIMEOUT_BY_INTENT.get(intent, RUN_TIMEOUT_BY_INTENT["auto"])
