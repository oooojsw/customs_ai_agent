from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .document_models import DocumentResult
from .errors import AgentApiException
from .models import AgentError


@dataclass(frozen=True)
class VisionResult:
    text: str
    model: str
    format: str = "md"
    session_id: str | None = None
    document: DocumentResult | None = None


class VisionBackend(Protocol):
    async def extract(
        self,
        *,
        path: Path,
        name: str,
        mime_type: str | None,
        language: str,
    ) -> VisionResult: ...


class LegacyTableOcrBackend:
    """Adapter for the existing TABLE_OCR_URL service."""

    def __init__(
        self,
        service_url: str,
        *,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service_url = service_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def extract(
        self,
        *,
        path: Path,
        name: str,
        mime_type: str | None,
        language: str,
    ) -> VisionResult:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                with path.open("rb") as file_handle:
                    response = await client.post(
                        self.service_url,
                        files={
                            "file": (
                                name,
                                file_handle,
                                mime_type or "application/octet-stream",
                            )
                        },
                        data={"return_format": "md", "language": language},
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise AgentApiException(
                AgentError(
                    error_code="OCR_SERVICE_UNAVAILABLE",
                    message="图片表格识别服务不可用",
                    retryable=True,
                    stage="recognizing_image",
                    dependency="table_ocr",
                    details={"reason": str(exc)},
                )
            ) from exc
        except ValueError as exc:
            raise AgentApiException(
                AgentError(
                    error_code="OCR_RESPONSE_INVALID",
                    message="图片表格识别服务返回了无效 JSON",
                    retryable=True,
                    stage="recognizing_image",
                    dependency="table_ocr",
                )
            ) from exc

        if not payload.get("success", False):
            raise AgentApiException(
                AgentError(
                    error_code="OCR_SERVICE_FAILED",
                    message=str(
                        payload.get("message")
                        or payload.get("detail")
                        or "图片表格识别失败"
                    ),
                    retryable=True,
                    stage="recognizing_image",
                    dependency="table_ocr",
                )
            )

        text = str(payload.get("context") or payload.get("content") or "").strip()
        if not text:
            raise AgentApiException(
                AgentError(
                    error_code="OCR_EMPTY_RESULT",
                    message="图片表格识别结果为空",
                    retryable=True,
                    stage="recognizing_image",
                    dependency="table_ocr",
                )
            )

        return VisionResult(
            text=text,
            model=str(payload.get("model") or "table-ocr"),
            format=str(payload.get("format") or "md"),
            session_id=payload.get("session_id"),
        )
