from __future__ import annotations

import json
import re


def format_agent_tool_error(error: Exception) -> str:
    """Convert tool exceptions into a safe observation for the ReAct loop."""
    message = str(error).strip() or error.__class__.__name__
    code = (
        message
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", message)
        else "TOOL_EXECUTION_ERROR"
    )
    retryable = code in {
        "CUSTOMS_CASE_VERSION_CONFLICT",
        "CUSTOMS_AGENT_UNAVAILABLE",
        "CUSTOMS_AGENT_INVALID_RESPONSE",
    }
    recovery_hint = (
        "先调用 get_case_snapshot 读取当前 stage 和 allowed_actions，纠正一次后再决定是否重试。"
        if retryable
        else "停止当前工具链，保留已有案件，向用户说明失败步骤和需要补充或修正的数据。"
    )
    return json.dumps(
        {
            "ok": False,
            "tool_error": {
                "error_code": code,
                "message": message[:500],
                "retryable": retryable,
            },
            "recovery_hint": recovery_hint,
        },
        ensure_ascii=False,
    )


def format_agent_tool_timeout(
    tool_name: str,
    timeout_seconds: float,
    *,
    level: str | None = None,
) -> str:
    """Return the same safe observation shape for a tool timeout."""
    return json.dumps(
        {
            "ok": False,
            "tool_error": {
                "error_code": "TOOL_TIMEOUT",
                "message": (
                    f"工具 {tool_name} 执行超过 {timeout_seconds:g} 秒，"
                    "已自动中止等待并保留当前案件状态。"
                ),
                "retryable": True,
                "timeout_level": level,
                "timeout_seconds": timeout_seconds,
            },
            "recovery_hint": (
                "先调用 get_case_snapshot 读取当前 stage 和 allowed_actions，"
                "确认案件状态后再决定是否重试或改走下一步。"
            ),
        },
        ensure_ascii=False,
    )
