from pathlib import Path


def test_general_agent_prompt_contains_tool_governance_policy():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "services"
        / "chat_agent.py"
    ).read_text(encoding="utf-8")

    required_rules = [
        "工具是可选能力，不是固定流程",
        "数据内容不等于用户意图",
        "不得擅自计算具体税额",
        "不得作为普通审单后的固定步骤",
        "达到用户当前目标后立即停止调用工具",
        "固定工作流由专门的业务入口负责",
    ]

    assert "{AGENT_TASK_GOVERNANCE_PROMPT}" in source
    for rule in required_rules:
        assert rule in source
