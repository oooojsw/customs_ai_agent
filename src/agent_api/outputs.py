from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .errors import AgentApiException
from .models import AgentError, AgentOutput, OutputKind, utc_now


@dataclass(frozen=True)
class PlatformFileRef:
    file_id: str
    preview_url: str | None = None
    download_url: str | None = None


class PlatformFilePublisher(Protocol):
    async def publish(
        self,
        *,
        source_path: Path,
        name: str,
        mime_type: str | None,
        metadata: dict,
    ) -> PlatformFileRef: ...


@dataclass
class _StoredOutput:
    output: AgentOutput
    path: Path
    tenant_id: str


class LocalOutputRegistry:
    def __init__(
        self,
        root_dir: str | Path,
        *,
        base_url: str = "/api/agent/v1/outputs",
        ttl_seconds: int = 86400,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._outputs: dict[str, _StoredOutput] = {}
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def register_file(
        self,
        *,
        source_path: str | Path,
        tenant_id: str,
        kind: OutputKind,
        format: str,
        name: str,
        mime_type: str | None = None,
        source_tool: str | None = None,
        metadata: dict | None = None,
    ) -> AgentOutput:
        source = Path(source_path).resolve()
        if not source.is_file():
            raise self._error("OUTPUT_SOURCE_NOT_FOUND", f"输出文件不存在: {name}")

        output_id = f"out-{uuid4().hex}"
        output_dir = (self.root_dir / output_id).resolve()
        self._ensure_within(output_dir, self.root_dir)
        output_dir.mkdir(parents=True, exist_ok=False)

        suffix = source.suffix.lower()[:16]
        destination = (output_dir / f"content{suffix}").resolve()
        self._ensure_within(destination, output_dir)
        temp_path = destination.with_suffix(destination.suffix + ".tmp")
        try:
            shutil.copyfile(source, temp_path)
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)

        digest = hashlib.sha256()
        with destination.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(chunk)

        now = utc_now()
        output = AgentOutput(
            output_id=output_id,
            kind=kind,
            format=format,
            name=name,
            mime_type=mime_type,
            size=destination.stat().st_size,
            sha256=digest.hexdigest(),
            source_tool=source_tool,
            agent_output_url=f"{self.base_url}/{output_id}/content",
            metadata={"storage": "agent_temporary", **(metadata or {})},
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        self._outputs[output_id] = _StoredOutput(
            output=output,
            path=destination,
            tenant_id=tenant_id,
        )
        return output.model_copy(deep=True)

    def get(self, output_id: str, tenant_id: str | None = None) -> AgentOutput:
        return self._get_stored(output_id, tenant_id).output.model_copy(deep=True)

    def get_path(self, output_id: str, tenant_id: str | None = None) -> Path:
        stored = self._get_stored(output_id, tenant_id)
        if not stored.path.is_file():
            raise self._error("OUTPUT_NOT_FOUND", f"输出文件不存在: {output_id}", 404)
        return stored.path

    def _get_stored(
        self, output_id: str, tenant_id: str | None = None
    ) -> _StoredOutput:
        try:
            stored = self._outputs[output_id]
        except KeyError as exc:
            raise self._error(
                "OUTPUT_NOT_FOUND", f"Output 不存在: {output_id}", 404
            ) from exc
        if stored.output.expires_at and stored.output.expires_at <= utc_now():
            raise self._error(
                "OUTPUT_EXPIRED", f"Output 已过期: {output_id}", 410
            )
        if tenant_id and stored.tenant_id != tenant_id:
            raise self._error(
                "TENANT_ACCESS_DENIED",
                "无权访问其他租户的 Output",
                403,
            )
        return stored

    @staticmethod
    def _ensure_within(path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError(f"path escapes configured root: {path}")

    @staticmethod
    def _error(code: str, message: str, http_status: int = 500) -> AgentApiException:
        return AgentApiException(
            AgentError(
                error_code=code,
                message=message,
                retryable=False,
                stage="output_storage",
            ),
            http_status=http_status,
        )


class OutputManager:
    def __init__(
        self,
        local_registry: LocalOutputRegistry,
        platform_publisher: PlatformFilePublisher | None = None,
    ) -> None:
        self.local_registry = local_registry
        self.platform_publisher = platform_publisher

    async def publish_file(
        self,
        *,
        source_path: str | Path,
        tenant_id: str,
        kind: OutputKind,
        format: str,
        name: str,
        mime_type: str | None = None,
        source_tool: str | None = None,
        metadata: dict | None = None,
        prefer_platform: bool = True,
    ) -> tuple[AgentOutput, AgentError | None]:
        source = Path(source_path).resolve()
        if prefer_platform and self.platform_publisher:
            try:
                published = await self.platform_publisher.publish(
                    source_path=source,
                    name=name,
                    mime_type=mime_type,
                    metadata=metadata or {},
                )
                output = AgentOutput(
                    output_id=f"out-{uuid4().hex}",
                    kind=kind,
                    format=format,
                    name=name,
                    mime_type=mime_type,
                    size=source.stat().st_size,
                    source_tool=source_tool,
                    platform_file_id=published.file_id,
                    preview_url=published.preview_url,
                    download_url=published.download_url,
                    metadata={"storage": "platform", **(metadata or {})},
                )
                return output, None
            except Exception as exc:
                warning = AgentError(
                    error_code="OUTPUT_UPLOAD_FAILED",
                    message=f"平台文件上传失败，已切换为智能体临时托管: {name}",
                    retryable=True,
                    stage="output_upload",
                    details={"reason": str(exc)},
                )
                local = self.local_registry.register_file(
                    source_path=source,
                    tenant_id=tenant_id,
                    kind=kind,
                    format=format,
                    name=name,
                    mime_type=mime_type,
                    source_tool=source_tool,
                    metadata=metadata,
                )
                return local, warning

        local = self.local_registry.register_file(
            source_path=source,
            tenant_id=tenant_id,
            kind=kind,
            format=format,
            name=name,
            mime_type=mime_type,
            source_tool=source_tool,
            metadata=metadata,
        )
        return local, None
