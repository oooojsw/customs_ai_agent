from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .errors import AgentApiException
from .models import AgentError, Attachment


@dataclass(frozen=True)
class DownloadedAttachment:
    file_id: str
    name: str
    purpose: str
    mime_type: str | None
    path: Path
    size: int
    sha256: str


class AttachmentDownloadManager:
    def __init__(
        self,
        root_dir: str | Path,
        *,
        allowed_hosts: tuple[str, ...] = (),
        max_bytes: int = 20 * 1024 * 1024,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.allowed_hosts = {host.lower() for host in allowed_hosts if host}
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def prepare(
        self, run_id: str, attachments: list[Attachment]
    ) -> list[DownloadedAttachment]:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[DownloadedAttachment] = []

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                for attachment in attachments:
                    downloaded.append(
                        await self._download_one(client, run_dir, attachment)
                    )
            return downloaded
        except Exception:
            self.cleanup(run_id)
            raise

    def cleanup(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir)

    async def _download_one(
        self,
        client: httpx.AsyncClient,
        run_dir: Path,
        attachment: Attachment,
    ) -> DownloadedAttachment:
        if attachment.download_url is None:
            raise self._error(
                "ATTACHMENT_URL_REQUIRED",
                f"附件缺少 download_url: {attachment.file_id}",
                retryable=False,
            )
        if attachment.expires_at and self._is_expired(attachment.expires_at):
            raise self._error(
                "ATTACHMENT_EXPIRED",
                f"附件下载地址已过期: {attachment.file_id}",
                retryable=True,
            )

        url = str(attachment.download_url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"}:
            raise self._error(
                "ATTACHMENT_URL_NOT_ALLOWED",
                "附件下载地址只允许 http/https",
                retryable=False,
            )
        if not self.allowed_hosts or host not in self.allowed_hosts:
            raise self._error(
                "ATTACHMENT_HOST_NOT_ALLOWED",
                f"附件主机未加入允许列表: {host or 'unknown'}",
                retryable=False,
            )

        suffix = Path(attachment.name).suffix.lower()[:16]
        safe_id = hashlib.sha256(attachment.file_id.encode("utf-8")).hexdigest()[:24]
        final_path = (run_dir / f"{safe_id}{suffix}").resolve()
        self._ensure_within(final_path, run_dir)
        temp_path = final_path.with_suffix(final_path.suffix + ".tmp")

        digest = hashlib.sha256()
        size = 0
        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_bytes:
                    raise self._error(
                        "ATTACHMENT_TOO_LARGE",
                        f"附件超过大小限制: {attachment.name}",
                        retryable=False,
                    )

                with temp_path.open("xb") as file_handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise self._error(
                                "ATTACHMENT_TOO_LARGE",
                                f"附件超过大小限制: {attachment.name}",
                                retryable=False,
                            )
                        digest.update(chunk)
                        file_handle.write(chunk)
            os.replace(temp_path, final_path)
        except httpx.HTTPError as exc:
            raise self._error(
                "ATTACHMENT_DOWNLOAD_FAILED",
                f"附件下载失败: {attachment.name}",
                retryable=True,
                details={"reason": str(exc)},
            ) from exc
        finally:
            if temp_path.exists():
                temp_path.unlink()

        actual_sha256 = digest.hexdigest()
        if attachment.sha256 and attachment.sha256.lower() != actual_sha256:
            final_path.unlink(missing_ok=True)
            raise self._error(
                "ATTACHMENT_CHECKSUM_MISMATCH",
                f"附件校验失败: {attachment.name}",
                retryable=True,
            )

        return DownloadedAttachment(
            file_id=attachment.file_id,
            name=attachment.name,
            purpose=attachment.purpose,
            mime_type=attachment.mime_type,
            path=final_path,
            size=size,
            sha256=actual_sha256,
        )

    def _run_dir(self, run_id: str) -> Path:
        safe_run_id = "".join(char for char in run_id if char.isalnum() or char in "-_")
        if not safe_run_id:
            raise ValueError("invalid run_id")
        run_dir = (self.root_dir / safe_run_id).resolve()
        self._ensure_within(run_dir, self.root_dir)
        return run_dir

    @staticmethod
    def _ensure_within(path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError(f"path escapes configured root: {path}")

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        retryable: bool,
        details: dict | None = None,
    ) -> AgentApiException:
        return AgentApiException(
            AgentError(
                error_code=code,
                message=message,
                retryable=retryable,
                stage="attachment_download",
                details=details or {},
            ),
            http_status=422,
        )
