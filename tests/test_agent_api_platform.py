import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_api.auth import ServiceAuthenticator
from src.agent_api.models import CreateRunRequest, RunStatus
from src.agent_api.platform_files import HttpPlatformFilePublisher
from src.agent_api.service import AgentRunService
from src.agent_api.sqlite_store import SQLiteRunStore
from src.agent_api.adapters import AdapterResult


def test_platform_file_publisher_maps_platform_response(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer platform-key"
        return httpx.Response(
            200,
            json={
                "file_id": "platform-file-001",
                "preview_url": "https://platform.test/preview/001",
                "download_url": "https://platform.test/download/001",
            },
            request=request,
        )

    async def scenario():
        publisher = HttpPlatformFilePublisher(
            "https://platform.test/files",
            api_key="platform-key",
            transport=httpx.MockTransport(handler),
        )
        result = await publisher.publish(
            source_path=source,
            name="report.docx",
            mime_type="application/octet-stream",
            metadata={"tenant_id": "tenant-001"},
        )
        assert result.file_id == "platform-file-001"

    asyncio.run(scenario())


def test_service_authenticator_rejects_bad_key_and_cross_tenant():
    app = FastAPI()

    @app.get("/")
    def endpoint(request):
        return {}

    authenticator = ServiceAuthenticator(enabled=True, api_key="secret")
    with TestClient(app) as client:
        request = client.build_request(
            "GET",
            "/",
            headers={
                "X-Agent-Service-Key": "wrong",
                "X-Tenant-ID": "tenant-001",
            },
        )
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": request.headers.raw,
        }
        with pytest.raises(Exception) as exc_info:
            authenticator.authenticate(Request(scope))
        assert exc_info.value.error.error_code == "SERVICE_AUTH_FAILED"

    with pytest.raises(Exception) as exc_info:
        authenticator.require_tenant(
            type("Identity", (), {"tenant_id": "tenant-002"})(),
            "tenant-001",
        )
    assert exc_info.value.error.error_code == "TENANT_ACCESS_DENIED"


def test_sqlite_run_store_restores_completed_run(tmp_path):
    class FakeAdapter:
        async def execute(self, request, app, emitter, context):
            return AdapterResult(final_answer="done")

    async def scenario():
        path = tmp_path / "runs.db"
        service = AgentRunService(
            store=SQLiteRunStore(path),
            adapters={"chat": FakeAdapter()},
            heartbeat_seconds=60,
        )
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-persist-001",
                "session": {
                    "session_id": "session-001",
                    "user_id": "user-001",
                    "tenant_id": "tenant-001",
                    "context_version": 2,
                },
                "message": {"content": "persist"},
                "options": {"intent": "chat"},
            }
        )
        created = await service.create_run(request, FastAPI())
        for _ in range(200):
            snapshot = await service.store.get(created.run_id)
            if snapshot.status in {
                RunStatus.COMPLETED,
                RunStatus.PARTIALLY_COMPLETED,
                RunStatus.FAILED,
            }:
                break
            await asyncio.sleep(0.005)
        restored = await SQLiteRunStore(path).get(created.run_id)
        assert restored.final_answer == "done"
        assert restored.context_version == 3
        assert restored.usage["duration_ms"] >= 0

    asyncio.run(scenario())
