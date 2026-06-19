import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_api import routes as agent_routes
from src.agent_api.routes import router
from src.agent_api.models import RunStatus


def test_platform_can_call_demo_full_review_end_to_end(tmp_path, monkeypatch):
    from src.agent_api.outputs import LocalOutputRegistry

    registry = LocalOutputRegistry(tmp_path / "outputs")
    monkeypatch.setattr(agent_routes, "local_output_registry", registry)
    monkeypatch.setattr(agent_routes.output_manager, "local_registry", registry)

    app = FastAPI()
    app.include_router(router, prefix="/api/agent/v1")
    payload = {
        "request_id": f"req-platform-demo-{uuid4().hex}",
        "session": {
            "session_id": f"platform-session-{uuid4().hex}",
            "user_id": "platform-user-001",
            "tenant_id": "tenant-001",
        },
        "message": {"content": ""},
        "business_context": {
            "entry_id": "530120250001",
            "mock_mode": True,
        },
        "options": {
            "intent": "full_review",
            "output_file_policy": "agent_temporary",
            "timeout_seconds": 30,
        },
    }

    with TestClient(app) as client:
        created = client.post("/api/agent/v1/runs", json=payload)
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        snapshot = None
        for _ in range(200):
            response = client.get(f"/api/agent/v1/runs/{run_id}")
            snapshot = response.json()
            if snapshot["status"] in {
                RunStatus.COMPLETED.value,
                RunStatus.PARTIALLY_COMPLETED.value,
                RunStatus.FAILED.value,
            }:
                break
            time.sleep(0.01)

        assert snapshot["status"] == RunStatus.COMPLETED.value
        assert "演示审单完成" in snapshot["final_answer"]
        assert snapshot["structured_result"]["process"]["state"] == (
            "review_recommended"
        )
        document_outputs = [
            output
            for output in snapshot["outputs"]
            if output["kind"] == "document"
        ]
        assert document_outputs

        events = client.get(f"/api/agent/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: agent_started" in events.text
        assert "event: output_created" in events.text
        assert "event: agent_completed" in events.text

        content = client.get(document_outputs[0]["agent_output_url"])
        assert content.status_code == 200
        assert len(content.content) > 1000
