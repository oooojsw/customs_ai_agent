from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field


class SubagentTaskRequest(BaseModel):
    """Structured task envelope for a child agent invocation."""

    task_id: str = Field(default_factory=lambda: f"subtask-{uuid4().hex}")
    task: str = Field(min_length=1)
    agent: str = "build"
    model: str = ""
    context_summary: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    permission_profile: Literal["read_only", "project_write"] = "project_write"

    @classmethod
    def from_tool_input(cls, raw_input: str) -> "SubagentTaskRequest":
        raw_input = str(raw_input or "").strip()
        if not raw_input:
            raise ValueError("task is required")
        try:
            payload = json.loads(raw_input)
        except json.JSONDecodeError:
            return cls(task=raw_input)
        if not isinstance(payload, dict):
            return cls(task=raw_input)
        normalized = dict(payload)
        normalized["task"] = str(
            payload.get("task") or payload.get("prompt") or ""
        ).strip()
        return cls.model_validate(normalized)


class SubagentArtifact(BaseModel):
    path: str
    size_bytes: int
    mime_type: str
    sha256: str


class SubagentResult(BaseModel):
    ok: bool
    subagent: str
    task_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    session_id: str | None = None
    artifacts: list[SubagentArtifact] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_tool_observation(self) -> str:
        return self.model_dump_json()


class OpenCodeSubagentRunner:
    """Runs OpenCode inside the parent tool timeout and cancellation scope."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        command_resolver: Callable[[str], str | None] = shutil.which,
        connect_timeout_seconds: float = 10.0,
        write_timeout_seconds: float = 30.0,
        startup_timeout_seconds: float = 10.0,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.output_dir = self.project_root / "data" / "opencode_outputs"
        self.run_dir = self.project_root / "data" / "opencode_runs"
        self.command_resolver = command_resolver
        self.connect_timeout_seconds = max(1.0, connect_timeout_seconds)
        self.write_timeout_seconds = max(1.0, write_timeout_seconds)
        self.startup_timeout_seconds = max(1.0, startup_timeout_seconds)

    async def run(self, request: SubagentTaskRequest) -> SubagentResult:
        opencode_path = self.command_resolver("opencode")
        if not opencode_path:
            return self._failure(
                request,
                "OPENCODE_NOT_FOUND",
                "local opencode command was not found in PATH",
                retryable=False,
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        process: asyncio.subprocess.Process | None = None
        session_id: str | None = None
        try:
            process, base_url = await self._start_server(opencode_path)
            timeout = httpx.Timeout(
                connect=self.connect_timeout_seconds,
                read=None,
                write=self.write_timeout_seconds,
                pool=self.connect_timeout_seconds,
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                create_response = await client.post(
                    f"{base_url}/session",
                    params={"directory": str(self.project_root)},
                    json={
                        "title": f"Customs AI delegated task {request.task_id}",
                        "permission": self._permissions(request.permission_profile),
                    },
                )
                create_response.raise_for_status()
                session_payload = create_response.json()
                session_id = str(session_payload.get("id") or "").strip()
                if not session_id:
                    return self._failure(
                        request,
                        "OPENCODE_SESSION_INVALID",
                        f"opencode session creation returned no id: {session_payload}",
                        retryable=True,
                    )

                message_response = await client.post(
                    f"{base_url}/session/{session_id}/message",
                    params={"directory": str(self.project_root)},
                    json=self._message_body(request),
                )
                message_response.raise_for_status()
                summary = self._extract_text(message_response.json())

            if len(summary) > 6000:
                summary = summary[-6000:]
            artifacts, verification = self.verify_artifacts(summary)
            if not artifacts and self.expects_artifact(request.task):
                verification.append(
                    "主智能体验证失败：OpenCode 没有返回 OPENCODE_ARTIFACT_PATH，"
                    "无法证明请求的文件产物已创建。"
                )
            return SubagentResult(
                ok=True,
                subagent="opencode",
                task_id=request.task_id,
                status="completed",
                session_id=session_id,
                summary=summary,
                artifacts=artifacts,
                verification=verification,
            )
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            return self._failure(
                request,
                "OPENCODE_TRANSPORT_TIMEOUT",
                f"opencode transport timed out before the child task completed: {exc}",
                retryable=True,
                session_id=session_id,
            )
        except Exception as exc:
            return self._failure(
                request,
                "OPENCODE_EXECUTION_FAILED",
                f"failed to execute opencode child session: {exc}",
                retryable=False,
                session_id=session_id,
            )
        finally:
            await self._stop_process(process)

    async def _start_server(
        self, opencode_path: str
    ) -> tuple[asyncio.subprocess.Process, str]:
        last_error = ""
        attempts_per_port = max(1, int(self.startup_timeout_seconds / 0.25))
        for port in range(4096, 4110):
            process = await asyncio.create_subprocess_exec(
                opencode_path,
                "serve",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(port),
                cwd=str(self.project_root),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            base_url = f"http://127.0.0.1:{port}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    for _ in range(attempts_per_port):
                        if process.returncode is not None:
                            last_error = (
                                f"opencode serve exited early on port {port} "
                                f"with code {process.returncode}"
                            )
                            break
                        try:
                            response = await client.get(
                                f"{base_url}/session/status",
                                params={"directory": str(self.project_root)},
                            )
                            if response.status_code < 500:
                                return process, base_url
                        except httpx.HTTPError as exc:
                            last_error = str(exc)
                        await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                await self._stop_process(process)
                raise
            await self._stop_process(process)
        raise RuntimeError(f"failed to start opencode server: {last_error}")

    async def _stop_process(
        self, process: asyncio.subprocess.Process | None
    ) -> None:
        if not process or process.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/T",
                    "/F",
                    "/PID",
                    str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.communicate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except Exception:
                    pass
                return
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                if process.returncode is None:
                    process.kill()
        except Exception:
            # Cleanup is best-effort. Never let process cleanup mask the
            # structured child-agent result or the original execution error.
            return

    def _message_body(self, request: SubagentTaskRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "agent": request.agent,
            "system": self._background_prompt(request),
            "parts": [{"type": "text", "text": self._task_prompt(request)}],
        }
        if request.model and "/" in request.model:
            provider_id, model_id = request.model.split("/", 1)
            body["model"] = {"providerID": provider_id, "modelID": model_id}
        return body

    def _background_prompt(self, request: SubagentTaskRequest) -> str:
        return f"""
You are OpenCode, a local child coding agent invoked by the parent Customs AI assistant.
The parent assistant has already decided to delegate this task to you.

BACKGROUND CONTEXT
- Project: an automatic customs declaration assistant for audit, compliance research,
  local skills, MCP filesystem tools, and report/export workflows.
- Project root: {self.project_root}
- The parent agent is the user-facing customs AI. You are not the parent; you are a
  subordinate execution agent and must report results back to the parent.
- Permission profile: {request.permission_profile}
- You may inspect and edit files inside this project only.
- Do not modify the local OpenCode installation, OpenCode source package, global OpenCode
  configuration, files outside this project, or unrelated user files.
- Do not modify .opencode/, AGENTS.md, AGENTS-opencode.md, startup scripts, or source code
  unless the current task explicitly asks for that exact change.
- For proof/artifact tasks, write files only under: {self.output_dir}
- If you create a file, your final response must include exactly one line:
  OPENCODE_ARTIFACT_PATH: data/opencode_outputs/<filename>
- Do not ask what the task is. The task is supplied in the user message below.

PARENT CONTEXT SUMMARY
{request.context_summary or "No additional context was supplied."}
""".strip()

    @staticmethod
    def _task_prompt(request: SubagentTaskRequest) -> str:
        criteria_text = "\n".join(
            f"- {item}" for item in request.acceptance_criteria
        ) or "- Complete only the delegated task and report concrete evidence."
        return f"""
CURRENT TASK
{request.task}

ACCEPTANCE CRITERIA
{criteria_text}

Execute the task now. Do not merely say you are ready. Do not ask the parent to restate
this task. If the task asks you to create/write/save a file and does not specify content,
create a concise markdown note proving the OpenCode child agent wrote it, save it as
`data/opencode_outputs/opencode_child_note.md`, and return the OPENCODE_ARTIFACT_PATH line.
""".strip()

    @staticmethod
    def _permissions(profile: str) -> list[dict[str, str]]:
        if profile == "read_only":
            return [
                {"permission": "edit", "pattern": "*", "action": "deny"},
                {"permission": "bash", "pattern": "*", "action": "deny"},
            ]
        return [
            {"permission": "edit", "pattern": "*", "action": "allow"},
            {"permission": "bash", "pattern": "*", "action": "allow"},
        ]

    @staticmethod
    def _extract_text(response_json: Any) -> str:
        parts = response_json.get("parts") if isinstance(response_json, dict) else []
        text_parts = []
        if isinstance(parts, list):
            for part in parts:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and part.get("text")
                ):
                    text_parts.append(str(part["text"]).strip())
        if text_parts:
            return "\n".join([part for part in text_parts if part]).strip()
        return json.dumps(response_json, ensure_ascii=False)[-4000:]

    def verify_artifacts(
        self, opencode_result: str
    ) -> tuple[list[SubagentArtifact], list[str]]:
        artifacts: list[SubagentArtifact] = []
        verification: list[str] = []
        relative_paths = {
            match.strip().strip('"').strip("'").replace("\\", "/").lstrip("./")
            for match in re.findall(
                r"OPENCODE_ARTIFACT_PATH:\s*([^\r\n]+)",
                opencode_result or "",
            )
        }
        data_root = (self.project_root / "data").resolve()
        for relative_path in sorted(relative_paths):
            absolute_path = (self.project_root / relative_path).resolve()
            try:
                absolute_path.relative_to(data_root)
            except ValueError:
                verification.append(
                    f"主智能体验证失败：opencode 返回的路径不在 data/ 目录内：{relative_path}"
                )
                continue
            if not absolute_path.is_file():
                verification.append(
                    f"主智能体验证失败：没有找到 opencode 返回的文件：{relative_path}"
                )
                continue
            digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
            mime_type = (
                mimetypes.guess_type(absolute_path.name)[0]
                or "application/octet-stream"
            )
            artifacts.append(
                SubagentArtifact(
                    path=absolute_path.relative_to(self.project_root).as_posix(),
                    size_bytes=absolute_path.stat().st_size,
                    mime_type=mime_type,
                    sha256=digest,
                )
            )
            verification.append(
                f"主智能体已验证文件存在：{relative_path}（{absolute_path.stat().st_size} bytes）"
            )
        return artifacts, verification

    @staticmethod
    def expects_artifact(task: str) -> bool:
        markers = [
            "文件",
            "写入",
            "创建",
            "生成",
            "保存",
            "读取",
            "file",
            "artifact",
            "read",
            "write",
            "create",
            "generate",
            "save",
        ]
        text = (task or "").lower()
        return any(marker in text for marker in markers)

    @staticmethod
    def _failure(
        request: SubagentTaskRequest,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        session_id: str | None = None,
    ) -> SubagentResult:
        return SubagentResult(
            ok=False,
            subagent="opencode",
            task_id=request.task_id,
            status="failed",
            session_id=session_id,
            summary=message[:1000],
            error={
                "error_code": error_code,
                "message": message[:1000],
                "retryable": retryable,
            },
        )
