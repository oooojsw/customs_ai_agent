import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agent_api.adapters import parse_legacy_sse
from src.agent_api.adapters import AuditAdapter, ChatAdapter, ExecutionContext
from src.agent_api.events import EventEmitter, format_sse
from src.agent_api.models import (
    AgentEvent,
    AgentOutput,
    CreateRunRequest,
    EventType,
    OutputKind,
)
from src.agent_api import routes as agent_routes
from src.agent_api.routes import router
from src.agent_api.service import AgentRunService
from src.agent_api.store import InMemoryRunStore


def make_request(**overrides) -> CreateRunRequest:
    payload = {
        "request_id": "req-contract-001",
        "session": {
            "session_id": "session-001",
            "user_id": "user-001",
            "tenant_id": "tenant-001",
        },
        "message": {"role": "user", "content": "请检查这票报关数据"},
        "language": "zh",
    }
    payload.update(overrides)
    return CreateRunRequest.model_validate(payload)


def test_run_request_requires_message_or_attachment():
    with pytest.raises(ValidationError):
        make_request(message={"role": "user", "content": ""})


def test_run_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make_request(unknown_field=True)


def test_legacy_sse_parser_preserves_payload():
    event_text = 'data: {"type":"answer","content":"测试"}\n\n'
    assert parse_legacy_sse(event_text) == [
        {"type": "answer", "content": "测试"}
    ]


def test_legacy_sse_parser_rejects_invalid_json():
    with pytest.raises(Exception) as exc_info:
        parse_legacy_sse("data: not-json\n\n")
    assert getattr(exc_info.value, "error").error_code == "LEGACY_EVENT_INVALID"


def test_sse_formatter_has_id_event_and_json_data():
    event = AgentEvent(
        run_id="run-001",
        request_id="req-001",
        session_id="session-001",
        sequence=3,
        event=EventType.MESSAGE_DELTA,
        data={"content": "您好"},
    )
    rendered = format_sse(event)
    assert rendered.startswith("id: 3\nevent: message_delta\ndata: ")
    data_line = next(line for line in rendered.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    assert payload["sequence"] == 3
    assert payload["data"]["content"] == "您好"


def test_tool_event_display_contract_defaults():
    async def scenario():
        request = make_request(request_id="req-tool-display-001")
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        emitter = EventEmitter(store, snapshot.run_id)

        await emitter.tool_started("search_customs_regulations", "检索法规依据")
        await emitter.tool_finished(
            "process_customs_review",
            "海关综合审单",
            "审单通过",
            interaction_kind="customs_authority",
            auto_expand=True,
            customs_reply="【海关模拟回复】审单通过",
        )
        events = await store.events_after(snapshot.run_id)

        started = events[0].data
        assert started["status"] == "running"
        assert started["interaction_kind"] == "agent_tool"
        assert started["auto_expand"] is False
        assert started["started_at"]

        finished = events[1].data
        assert finished["status"] == "success"
        assert finished["interaction_kind"] == "customs_authority"
        assert finished["auto_expand"] is True
        assert finished["summary"] == "审单通过"
        assert finished["customs_reply"].startswith("【海关模拟回复】")
        assert finished["finished_at"]

    asyncio.run(scenario())


def test_run_service_emits_output_created_for_adapter_outputs():
    class OutputOnlyAdapter:
        async def execute(self, request, app, emitter, context):
            from src.agent_api.adapters import AdapterResult

            return AdapterResult(
                final_answer="已生成",
                outputs=[
                    AgentOutput(
                        output_id="out-contract-001",
                        kind=OutputKind.DOCUMENT,
                        format="docx",
                        name="报告.docx",
                        source_tool="report_generation",
                    )
                ],
            )

    async def scenario():
        request = make_request(request_id="req-output-fallback-001")
        service = AgentRunService(
            store=InMemoryRunStore(),
            adapters={"chat": OutputOnlyAdapter()},
            heartbeat_seconds=60,
        )
        created = await service.create_run(request, FastAPI())
        for _ in range(100):
            snapshot = await service.store.get(created.run_id)
            if snapshot.status.value == "completed":
                break
            await asyncio.sleep(0.005)
        events = await service.store.events_after(created.run_id)
        outputs = [
            event.data["output"]
            for event in events
            if event.event == EventType.OUTPUT_CREATED
        ]

        assert len(outputs) == 1
        assert outputs[0]["output_id"] == "out-contract-001"
        assert outputs[0]["kind"] == "document"
        assert "platform_file_id" in outputs[0]
        assert outputs[0]["platform_file_id"] is None

    asyncio.run(scenario())


def test_capabilities_and_health_contract():
    app = FastAPI()
    app.state.agent = object()
    app.state.kb = object()
    app.include_router(router, prefix="/api/agent/v1")

    with TestClient(app) as client:
        capabilities = client.get("/api/agent/v1/capabilities")
        health = client.get("/api/agent/v1/health")

    assert capabilities.status_code == 200
    names = {item["name"] for item in capabilities.json()["capabilities"]}
    assert {"customs_chat", "declaration_audit", "image_ocr"} <= names
    assert health.status_code == 200
    dependencies = health.json()["dependencies"]
    assert dependencies["chat_agent"] == "ready"
    assert dependencies["knowledge_base"] == "ready"
    assert dependencies["file_center"] in {"configured", "local_fallback"}
    assert dependencies["run_store"] in {
        "InMemoryRunStore",
        "SQLiteRunStore",
    }


def test_run_routes_end_to_end_with_standard_sse(monkeypatch):
    class RouteFakeAdapter:
        async def execute(self, request, app, emitter, context):
            await emitter.emit(EventType.MESSAGE_DELTA, content="路由测试完成")
            from src.agent_api.adapters import AdapterResult

            return AdapterResult(final_answer="路由测试完成")

    service = AgentRunService(
        adapters={"chat": RouteFakeAdapter()}, heartbeat_seconds=60
    )
    monkeypatch.setattr(agent_routes, "run_service", service)

    app = FastAPI()
    app.include_router(router, prefix="/api/agent/v1")
    payload = make_request(request_id="req-route-001").model_dump(mode="json")

    with TestClient(app) as client:
        created = client.post("/api/agent/v1/runs", json=payload)
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        snapshot = None
        for _ in range(100):
            response = client.get(f"/api/agent/v1/runs/{run_id}")
            snapshot = response.json()
            if snapshot["status"] == "completed":
                break
            time.sleep(0.005)

        assert snapshot["status"] == "completed"
        assert snapshot["final_answer"] == "路由测试完成"

        events = client.get(f"/api/agent/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: agent_started" in events.text
        assert "event: message_delta" in events.text
        assert "event: agent_completed" in events.text


def test_chat_adapter_maps_legacy_sse_without_exposing_thinking():
    class FakeLegacyAgent:
        async def chat_stream(self, message, session_id, language="zh"):
            yield 'data: {"type":"thinking","content":"private"}\n\n'
            yield 'data: {"type":"tool_start","tool_name":"audit_declaration"}\n\n'
            yield 'data: {"type":"tool_end","tool_name":"audit_declaration","tool_result":"通过"}\n\n'
            yield 'data: {"type":"answer","content":"审单完成"}\n\n'

    async def scenario():
        request = make_request(request_id="req-chat-adapter-001")
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        app = FastAPI()
        app.state.agent = FakeLegacyAgent()
        result = await ChatAdapter().execute(
            request,
            app,
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        events = await store.events_after(snapshot.run_id)

        assert result.final_answer == "审单完成"
        assert [event.event for event in events] == [
            EventType.STATUS_CHANGED,
            EventType.TOOL_STARTED,
            EventType.TOOL_FINISHED,
            EventType.MESSAGE_DELTA,
        ]
        assert "private" not in str([event.data for event in events])

    asyncio.run(scenario())


def test_chat_adapter_deduplicates_repeated_legacy_tool_start():
    class FakeLegacyAgent:
        async def chat_stream(self, message, session_id, language="zh"):
            yield 'data: {"type":"tool_start","tool_name":"create_import_case"}\n\n'
            yield 'data: {"type":"tool_start","tool_name":"create_import_case"}\n\n'
            yield 'data: {"type":"tool_start","tool_name":"create_import_case"}\n\n'
            yield 'data: {"type":"tool_end","tool_name":"create_import_case","tool_result":"已创建"}\n\n'
            yield 'data: {"type":"answer","content":"已创建一个案件"}\n\n'

    async def scenario():
        request = make_request(request_id="req-chat-dedupe-001")
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        app = FastAPI()
        app.state.agent = FakeLegacyAgent()
        result = await ChatAdapter().execute(
            request,
            app,
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        events = await store.events_after(snapshot.run_id)

        assert result.final_answer == "已创建一个案件"
        assert [
            event.event for event in events
            if event.event in {EventType.TOOL_STARTED, EventType.TOOL_FINISHED}
        ] == [
            EventType.TOOL_STARTED,
            EventType.TOOL_FINISHED,
        ]

    asyncio.run(scenario())


def test_chat_adapter_preserves_tool_display_metadata():
    class FakeLegacyAgent:
        async def chat_stream(self, message, session_id, language="zh"):
            yield (
                'data: {"type":"tool_start","tool_name":"process_customs_review",'
                '"display_name":"海关综合审单","interaction_kind":"customs_authority"}\n\n'
            )
            yield (
                'data: {"type":"tool_end","tool_name":"process_customs_review",'
                '"display_name":"海关综合审单","status":"error",'
                '"interaction_kind":"customs_authority","auto_expand":true,'
                '"customs_reply":"海关要求补充价格资料",'
                '"tool_result":"价格资料不足"}\n\n'
            )
            yield 'data: {"type":"answer","content":"已收到海关回复"}\n\n'

    async def scenario():
        request = make_request(request_id="req-chat-tool-metadata-001")
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        app = FastAPI()
        app.state.agent = FakeLegacyAgent()
        await ChatAdapter().execute(
            request,
            app,
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        events = await store.events_after(snapshot.run_id)
        started = next(event for event in events if event.event == EventType.TOOL_STARTED)
        finished = next(event for event in events if event.event == EventType.TOOL_FINISHED)

        assert started.data["display_name"] == "海关综合审单"
        assert started.data["interaction_kind"] == "customs_authority"
        assert finished.data["status"] == "error"
        assert finished.data["auto_expand"] is True
        assert finished.data["customs_reply"] == "海关要求补充价格资料"

    asyncio.run(scenario())


def test_audit_adapter_maps_rule_events(monkeypatch):
    class FakeOrchestrator:
        def __init__(self, llm_config=None):
            pass

        async def analyze_stream(self, raw_data, language="zh"):
            yield 'data: {"type":"init","total_steps":1}\n\n'
            yield 'data: {"type":"step_start","rule_id":"R01","loading_text":"检查要素"}\n\n'
            yield 'data: {"type":"step_result","rule_id":"R01","status":"pass","message":"要素完整"}\n\n'
            yield 'data: {"type":"complete","summary":"建议放行"}\n\n'

    monkeypatch.setattr(
        "src.agent_api.adapters.RiskAnalysisOrchestrator", FakeOrchestrator
    )

    async def scenario():
        request = make_request(request_id="req-audit-adapter-001")
        request.options.intent = "audit"
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        app = FastAPI()
        app.state.llm_config = {}
        result = await AuditAdapter().execute(
            request,
            app,
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        events = await store.events_after(snapshot.run_id)

        assert result.final_answer == "建议放行"
        assert result.structured_result["findings"] == [
            {"rule_id": "R01", "status": "pass", "message": "要素完整"}
        ]
        assert events[-1].event == EventType.MESSAGE_DELTA

    asyncio.run(scenario())
