import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_api.routes import router, run_service
from src.agent_api.store import InMemoryRunStore


class FakeToolCallingAgent:
    def __init__(self):
        self.received_messages = []

    async def chat_stream(self, message, session_id, language="zh"):
        self.received_messages.append((message, session_id, language))
        events = [
            {"type": "answer", "content": "正在按要求审单。"},
            {"type": "tool_start", "tool_name": "audit_declaration"},
            {
                "type": "tool_end",
                "tool_name": "audit_declaration",
                "tool_result": "未发现明显风险。",
            },
            {"type": "answer", "content": "未发现明显风险。"},
            {"type": "done"},
        ]
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def test_platform_general_agent_run_streams_tool_events_end_to_end():
    original_store = run_service.store
    original_tasks = run_service._tasks
    original_versions = run_service._session_versions
    original_locks = run_service._session_locks
    run_service.store = InMemoryRunStore()
    run_service._tasks = {}
    run_service._session_versions = {}
    run_service._session_locks = {}

    app = FastAPI()
    app.include_router(router, prefix="/api/agent/v1")
    agent = FakeToolCallingAgent()
    app.state.agent = agent

    unique_id = uuid4().hex
    request_body = {
        "request_id": f"req-general-smoke-{unique_id}",
        "session": {
            "session_id": f"session-{unique_id}",
            "user_id": "platform-user-001",
            "tenant_id": "tenant-001",
        },
        "message": {
            "content": "只审查以下报关单，不要计算税费：HS编码85423100"
        },
        "options": {
            "intent": "auto",
            "include_tool_trace": True,
            "timeout_seconds": 30,
        },
    }

    try:
        with TestClient(app) as client:
            created = client.post("/api/agent/v1/runs", json=request_body)
            assert created.status_code == 202
            created_body = created.json()
            run_id = created_body["run_id"]

            events_response = client.get(created_body["events_url"])
            assert events_response.status_code == 200
            event_names = []
            for line in events_response.text.splitlines():
                if line.startswith("event: "):
                    event_names.append(line[7:])

            assert event_names == [
                "agent_started",
                "status_changed",
                "message_delta",
                "tool_started",
                "tool_finished",
                "message_delta",
                "agent_completed",
            ]

            snapshot = client.get(f"/api/agent/v1/runs/{run_id}")
            assert snapshot.status_code == 200
            snapshot_body = snapshot.json()
            assert snapshot_body["status"] == "completed"
            assert snapshot_body["final_answer"] == (
                "正在按要求审单。未发现明显风险。"
            )
            assert agent.received_messages == [
                (
                    request_body["message"]["content"],
                    request_body["session"]["session_id"],
                    "zh",
                )
            ]
    finally:
        run_service.store = original_store
        run_service._tasks = original_tasks
        run_service._session_versions = original_versions
        run_service._session_locks = original_locks
