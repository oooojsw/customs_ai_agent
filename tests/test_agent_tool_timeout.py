import asyncio
import inspect
import json
import time

import pytest
from langchain_core.tools import StructuredTool, Tool

from src.services.agent_tool_errors import (
    format_agent_tool_error,
    format_agent_tool_timeout,
)
from src.services.chat_agent import CustomsChatAgent
from src.services.subagent_runtime import OpenCodeSubagentRunner
from src.services.tool_execution_policy import (
    ToolTimeoutLevel,
    get_default_run_timeout,
    get_tool_policy,
)


def test_format_agent_tool_timeout_returns_structured_error():
    payload = json.loads(format_agent_tool_timeout("slow_tool", 2.5))

    assert payload["ok"] is False
    assert payload["tool_error"]["error_code"] == "TOOL_TIMEOUT"
    assert payload["tool_error"]["retryable"] is True
    assert "slow_tool" in payload["tool_error"]["message"]


def test_format_agent_tool_error_returns_structured_error():
    payload = json.loads(format_agent_tool_error(ValueError("bad input")))

    assert payload["ok"] is False
    assert payload["tool_error"]["error_code"] == "TOOL_EXECUTION_ERROR"
    assert payload["tool_error"]["retryable"] is False


@pytest.mark.asyncio
async def test_policy_wrapper_times_out_fast_tool():
    agent = CustomsChatAgent.__new__(CustomsChatAgent)
    agent._customs_tool_locks = {}
    agent._customs_tool_names = set()
    agent._tool_timeout_seconds = lambda _level: 0.05

    def slow_tool(value: str):
        time.sleep(0.3)
        return value

    tool = Tool(name="slow_tool", func=slow_tool, description="slow")
    agent.tools = [tool]
    agent._apply_tool_execution_policies()
    wrapped_tool = agent.tools[0]
    result = await wrapped_tool.ainvoke("late result")
    payload = json.loads(result)

    assert payload["tool_error"]["error_code"] == "TOOL_TIMEOUT"
    assert payload["tool_error"]["timeout_level"] == "L1"
    assert wrapped_tool.metadata["timeout_seconds"] == 0.05


@pytest.mark.asyncio
async def test_policy_wrapper_returns_fast_result():
    agent = CustomsChatAgent.__new__(CustomsChatAgent)
    agent._customs_tool_locks = {}
    agent._customs_tool_names = set()
    tool = Tool(
        name="fast_tool",
        func=lambda value: value,
        description="fast",
    )
    agent.tools = [tool]
    agent._apply_tool_execution_policies()

    assert await agent.tools[0].ainvoke("ok") == "ok"


@pytest.mark.asyncio
async def test_customs_tools_for_same_case_are_serialized():
    agent = CustomsChatAgent.__new__(CustomsChatAgent)
    agent._customs_tool_locks = {}
    agent._customs_tool_names = {"first", "second"}
    active = 0
    max_active = 0

    def tracked_tool(value: str, business_case_id: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.05)
        active -= 1
        return value

    first_tool = StructuredTool.from_function(
        name="first", func=tracked_tool, description="first"
    )
    second_tool = StructuredTool.from_function(
        name="second", func=tracked_tool, description="second"
    )
    agent.tools = [first_tool, second_tool]
    agent._apply_tool_execution_policies()
    first_tool, second_tool = agent.tools

    first, second = await asyncio.gather(
        first_tool.ainvoke(
            {"value": "one", "business_case_id": "CASE-1"}
        ),
        second_tool.ainvoke(
            {"value": "two", "business_case_id": "CASE-1"}
        ),
    )

    assert (first, second) == ("one", "two")
    assert max_active == 1


def test_timeout_policy_levels_and_run_defaults():
    assert get_tool_policy("get_case_snapshot").level == ToolTimeoutLevel.FAST
    assert get_tool_policy("classify_goods").level == ToolTimeoutLevel.STANDARD
    assert get_tool_policy("audit_declaration").level == ToolTimeoutLevel.LONG
    assert get_tool_policy("generate_compliance_report").level == ToolTimeoutLevel.DEEP
    assert get_tool_policy("delegate_to_opencode").level == ToolTimeoutLevel.SUBAGENT
    assert get_default_run_timeout("mock_import_declaration") == 300
    assert get_default_run_timeout("audit") == 600
    assert get_default_run_timeout("report") == 1200
    assert get_default_run_timeout("auto") == 3600


def test_opencode_delegation_has_one_managed_timeout_path():
    chat_agent_source = inspect.getsource(CustomsChatAgent)
    runner_source = inspect.getsource(OpenCodeSubagentRunner)

    assert "_should_delegate_to_opencode" not in chat_agent_source
    assert "httpx.Timeout(240.0" not in chat_agent_source
    assert "httpx.Timeout(240.0" not in runner_source
    assert "read=None" in runner_source
    assert "OpenCodeSubagentRunner" in chat_agent_source
