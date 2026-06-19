from __future__ import annotations

import json
from pathlib import Path

import httpx

from .outputs import PlatformFileRef


class HttpPlatformFilePublisher:
    """Uploads generated artifacts to a platform-owned file center."""

    def __init__(
        self,
        upload_url: str,
        *,
        api_key: str = "",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.upload_url = upload_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def publish(
        self,
        *,
        source_path: Path,
        name: str,
        mime_type: str | None,
        metadata: dict,
    ) -> PlatformFileRef:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        form_data = {
            "name": name,
            "metadata": json.dumps(metadata, ensure_ascii=False),
        }
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            with source_path.open("rb") as file_handle:
                response = await client.post(
                    self.upload_url,
                    headers=headers,
                    data=form_data,
                    files={
                        "file": (
                            name,
                            file_handle,
                            mime_type or "application/octet-stream",
                        )
                    },
                )
            response.raise_for_status()
            payload = response.json()

        file_id = payload.get("file_id") or payload.get("id")
        if not file_id:
            raise ValueError("platform file response missing file_id")
        return PlatformFileRef(
            file_id=str(file_id),
            preview_url=payload.get("preview_url"),
            download_url=payload.get("download_url"),
        )
