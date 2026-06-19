import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_api import routes as agent_routes
from src.agent_api.adapters import OcrAdapter
from src.agent_api.attachments import (
    AttachmentDownloadManager,
    DownloadedAttachment,
)
from src.agent_api.errors import AgentApiException
from src.agent_api.document_models import DocumentResult
from src.agent_api.models import (
    Attachment,
    CreateRunRequest,
    EventType,
    OutputKind,
    RunStatus,
)
from src.agent_api.outputs import LocalOutputRegistry, OutputManager
from src.agent_api.service import AgentRunService
from src.agent_api.vision import VisionResult


def make_attachment(
    *,
    download_url: str = "https://files.example.test/declaration.png",
    sha256: str | None = None,
) -> Attachment:
    return Attachment.model_validate(
        {
            "file_id": "file-001",
            "kind": "image",
            "name": "declaration.png",
            "mime_type": "image/png",
            "download_url": download_url,
            "sha256": sha256,
        }
    )


def test_attachment_download_validates_host_checksum_and_cleanup(tmp_path):
    content = b"fake-png-content"
    digest = hashlib.sha256(content).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    async def scenario():
        manager = AttachmentDownloadManager(
            tmp_path / "runs",
            allowed_hosts=("files.example.test",),
            transport=httpx.MockTransport(handler),
        )
        downloaded = await manager.prepare(
            "run-001", [make_attachment(sha256=digest)]
        )
        assert len(downloaded) == 1
        assert downloaded[0].path.read_bytes() == content
        assert downloaded[0].sha256 == digest
        manager.cleanup("run-001")
        assert not (tmp_path / "runs" / "run-001").exists()

    asyncio.run(scenario())


def test_attachment_download_blocks_unapproved_host(tmp_path):
    async def scenario():
        manager = AttachmentDownloadManager(
            tmp_path / "runs",
            allowed_hosts=("files.example.test",),
        )
        with pytest.raises(AgentApiException) as exc_info:
            await manager.prepare(
                "run-001",
                [make_attachment(download_url="https://evil.example.test/file.png")],
            )
        assert exc_info.value.error.error_code == "ATTACHMENT_HOST_NOT_ALLOWED"

    asyncio.run(scenario())


def test_attachment_download_enforces_max_size(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"0123456789",
            headers={"content-length": "10"},
            request=request,
        )

    async def scenario():
        manager = AttachmentDownloadManager(
            tmp_path / "runs",
            allowed_hosts=("files.example.test",),
            max_bytes=5,
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(AgentApiException) as exc_info:
            await manager.prepare("run-001", [make_attachment()])
        assert exc_info.value.error.error_code == "ATTACHMENT_TOO_LARGE"

    asyncio.run(scenario())


def test_local_output_registry_copies_and_hashes_file(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"report-content")
    registry = LocalOutputRegistry(tmp_path / "outputs", ttl_seconds=60)

    output = registry.register_file(
        source_path=source,
        tenant_id="tenant-001",
        kind=OutputKind.DOCUMENT,
        format="docx",
        name="合规建议书.docx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    assert output.metadata["storage"] == "agent_temporary"
    assert output.agent_output_url.endswith(f"/{output.output_id}/content")
    assert registry.get_path(output.output_id).read_bytes() == b"report-content"
    assert output.sha256 == hashlib.sha256(b"report-content").hexdigest()


def test_output_manager_falls_back_when_platform_upload_fails(tmp_path):
    class FailingPublisher:
        async def publish(self, **kwargs):
            raise RuntimeError("platform unavailable")

    async def scenario():
        source = tmp_path / "report.pdf"
        source.write_bytes(b"pdf")
        manager = OutputManager(
            LocalOutputRegistry(tmp_path / "outputs"),
            platform_publisher=FailingPublisher(),
        )
        output, warning = await manager.publish_file(
            source_path=source,
            tenant_id="tenant-001",
            kind=OutputKind.DOCUMENT,
            format="pdf",
            name="report.pdf",
            prefer_platform=True,
        )
        assert output.metadata["storage"] == "agent_temporary"
        assert warning.error_code == "OUTPUT_UPLOAD_FAILED"

    asyncio.run(scenario())


def test_output_routes_return_metadata_and_content(tmp_path, monkeypatch):
    source = tmp_path / "preview.png"
    source.write_bytes(b"png-content")
    registry = LocalOutputRegistry(tmp_path / "outputs")
    output = registry.register_file(
        source_path=source,
        tenant_id="tenant-001",
        kind=OutputKind.IMAGE,
        format="png",
        name="预览图.png",
        mime_type="image/png",
    )
    monkeypatch.setattr(agent_routes, "local_output_registry", registry)

    app = FastAPI()
    app.include_router(agent_routes.router, prefix="/api/agent/v1")
    with TestClient(app) as client:
        metadata = client.get(f"/api/agent/v1/outputs/{output.output_id}")
        content = client.get(
            f"/api/agent/v1/outputs/{output.output_id}/content"
        )

    assert metadata.status_code == 200
    assert metadata.json()["name"] == "预览图.png"
    assert content.status_code == 200
    assert content.content == b"png-content"
    assert content.headers["content-type"] == "image/png"


def test_ocr_run_downloads_attachment_and_creates_output(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"image")

    class FakeAttachmentManager:
        cleaned = False

        async def prepare(self, run_id, attachments):
            return [
                DownloadedAttachment(
                    file_id=attachments[0].file_id,
                    name=attachments[0].name,
                    purpose=attachments[0].purpose,
                    mime_type=attachments[0].mime_type,
                    path=source,
                    size=source.stat().st_size,
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )
            ]

        def cleanup(self, run_id):
            self.cleaned = True

    class FakeVisionBackend:
        async def extract(self, **kwargs):
            return VisionResult(
                text="报关单号：TEST-001",
                model="fake-vision",
                format="md",
            )

    async def scenario():
        attachment_manager = FakeAttachmentManager()
        service = AgentRunService(
            adapters={"ocr": OcrAdapter(FakeVisionBackend())},
            attachment_manager=attachment_manager,
            heartbeat_seconds=60,
        )
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-ocr-001",
                "session": {
                    "session_id": "session-001",
                    "user_id": "user-001",
                },
                "message": {"role": "user", "content": "识别这张报关单"},
                "attachments": [
                    {
                        "file_id": "file-001",
                        "kind": "image",
                        "name": "declaration.png",
                        "download_url": "https://files.example.test/declaration.png",
                    }
                ],
                "options": {"intent": "ocr"},
            }
        )
        response = await service.create_run(request, FastAPI())

        for _ in range(200):
            snapshot = await service.store.get(response.run_id)
            if snapshot.status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                break
            await asyncio.sleep(0.005)

        events = await service.store.events_after(response.run_id)
        assert snapshot.status == RunStatus.COMPLETED
        assert snapshot.outputs[0].data["full_text"] == "报关单号：TEST-001"
        assert snapshot.outputs[0].data["model_used"] == "fake-vision"
        assert EventType.OUTPUT_CREATED in [event.event for event in events]
        assert events[-1].event == EventType.AGENT_COMPLETED
        assert attachment_manager.cleaned is True

    asyncio.run(scenario())


def test_ocr_run_with_structured_table_publishes_xlsx(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"image")

    class FakeAttachmentManager:
        async def prepare(self, run_id, attachments):
            return [
                DownloadedAttachment(
                    file_id=attachments[0].file_id,
                    name=attachments[0].name,
                    purpose=attachments[0].purpose,
                    mime_type=attachments[0].mime_type,
                    path=source,
                    size=source.stat().st_size,
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )
            ]

        def cleanup(self, run_id):
            pass

    class FakeTableVisionBackend:
        async def extract(self, **kwargs):
            return VisionResult(
                text="HS编码 85423100",
                model="fake-table-vision",
                document=DocumentResult.model_validate(
                    {
                        "source_file_id": "placeholder",
                        "source_name": "placeholder.png",
                        "document_type": "table",
                        "tables": [
                            {
                                "rows": 1,
                                "columns": 2,
                                "cells": [
                                    {"row": 0, "column": 0, "text": "HS编码"},
                                    {"row": 0, "column": 1, "text": "85423100"},
                                ],
                            }
                        ],
                    }
                ),
            )

    async def scenario():
        registry = LocalOutputRegistry(tmp_path / "outputs")
        service = AgentRunService(
            adapters={"ocr": OcrAdapter(FakeTableVisionBackend())},
            attachment_manager=FakeAttachmentManager(),
            output_manager=OutputManager(registry),
            heartbeat_seconds=60,
        )
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-ocr-table-001",
                "session": {
                    "session_id": "session-001",
                    "user_id": "user-001",
                    "tenant_id": "tenant-001",
                },
                "message": {"role": "user", "content": "转成 Excel"},
                "attachments": [
                    {
                        "file_id": "file-001",
                        "kind": "image",
                        "name": "declaration.png",
                        "download_url": "https://files.example.test/declaration.png",
                    }
                ],
                "options": {
                    "intent": "ocr",
                    "output_file_policy": "agent_temporary",
                },
            }
        )
        response = await service.create_run(request, FastAPI())

        for _ in range(200):
            snapshot = await service.store.get(response.run_id)
            if snapshot.status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                break
            await asyncio.sleep(0.005)

        spreadsheet = next(
            item for item in snapshot.outputs
            if item.kind == OutputKind.SPREADSHEET
        )
        assert snapshot.status == RunStatus.COMPLETED
        assert snapshot.final_answer == (
            "已完成 1 个附件的图片文字识别。 已生成 1 个可编辑 Excel 文件。"
        )
        assert spreadsheet.format == "xlsx"
        assert spreadsheet.metadata["table_count"] == 1
        assert registry.get_path(spreadsheet.output_id).is_file()

    asyncio.run(scenario())
