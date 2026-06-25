import asyncio
import inspect
import json

from src.services import subagent_runtime
from src.services.subagent_runtime import (
    OpenCodeSubagentRunner,
    SubagentTaskRequest,
)


def test_subagent_task_request_accepts_prompt_alias_and_limits_fields():
    request = SubagentTaskRequest.from_tool_input(
        json.dumps(
            {
                "prompt": "读取项目并生成说明",
                "agent": "build",
                "permission_profile": "read_only",
                "acceptance_criteria": ["只读", "返回证据"],
            },
            ensure_ascii=False,
        )
    )

    assert request.task == "读取项目并生成说明"
    assert request.permission_profile == "read_only"
    assert request.acceptance_criteria == ["只读", "返回证据"]


def test_opencode_runner_verifies_artifacts_inside_data(tmp_path):
    artifact = tmp_path / "data" / "opencode_outputs" / "proof.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("proof", encoding="utf-8")
    runner = OpenCodeSubagentRunner(tmp_path)

    artifacts, verification = runner.verify_artifacts(
        "OPENCODE_ARTIFACT_PATH: data/opencode_outputs/proof.md"
    )

    assert len(artifacts) == 1
    assert artifacts[0].path == "data/opencode_outputs/proof.md"
    assert artifacts[0].sha256
    assert verification[0].startswith("主智能体已验证文件存在")


def test_opencode_runner_rejects_artifacts_outside_data(tmp_path):
    runner = OpenCodeSubagentRunner(tmp_path)

    artifacts, verification = runner.verify_artifacts(
        "OPENCODE_ARTIFACT_PATH: ../outside.txt"
    )

    assert artifacts == []
    assert "不在 data/ 目录内" in verification[0]


def test_opencode_not_found_returns_structured_failure(tmp_path):
    async def scenario():
        runner = OpenCodeSubagentRunner(tmp_path, command_resolver=lambda _: None)
        result = await runner.run(SubagentTaskRequest(task="测试"))

        assert result.ok is False
        assert result.error["error_code"] == "OPENCODE_NOT_FOUND"
        assert result.to_tool_observation().startswith("{")

    asyncio.run(scenario())


def test_opencode_server_does_not_use_unconsumed_pipes():
    source = inspect.getsource(OpenCodeSubagentRunner._start_server)

    assert "asyncio.subprocess.PIPE" not in source
    assert "asyncio.subprocess.DEVNULL" in source


def test_opencode_process_cleanup_is_best_effort(tmp_path, monkeypatch):
    class BrokenProcess:
        pid = 12345
        returncode = None

        def terminate(self):
            raise RuntimeError("terminate failed")

        def kill(self):
            raise RuntimeError("kill failed")

    async def scenario():
        monkeypatch.setattr(subagent_runtime.sys, "platform", "linux")
        runner = OpenCodeSubagentRunner(tmp_path)
        await runner._stop_process(BrokenProcess())

    asyncio.run(scenario())
