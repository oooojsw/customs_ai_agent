import asyncio

import pytest
from fastapi import FastAPI

from src.agent_api.adapters import AdapterResult
from src.agent_api.errors import AgentApiException
from src.agent_api.models import CreateRunRequest, EventType, RunStatus
from src.agent_api.service import AgentRunService
from src.agent_api.store import InMemoryRunStore


def make_request(
    *, request_id: str = "req-service-001", content: str = "测试智能体"
) -> CreateRunRequest:
    return CreateRunRequest.model_validate(
        {
            "request_id": request_id,
            "session": {
                "session_id": "session-001",
                "user_id": "user-001",
                "tenant_id": "tenant-001",
            },
            "message": {"role": "user", "content": content},
            "options": {"intent": "chat", "timeout_seconds": 30},
        }
    )


class FakeAdapter:
    async def execute(self, request, app, emitter, context):
        await emitter.status("fake_processing")
        await emitter.emit(EventType.MESSAGE_DELTA, content="完成")
        return AdapterResult(
            final_answer="完成",
            structured_result={"source": "fake"},
        )


class SlowAdapter:
    async def execute(self, request, app, emitter, context):
        await emitter.status("waiting")
        await asyncio.sleep(60)
        return AdapterResult(final_answer="不应完成")


class CleanupAwareAdapter:
    def __init__(self):
        self.cleaned = False

    async def execute(self, request, app, emitter, context):
        try:
            await asyncio.sleep(60)
            return AdapterResult(final_answer="不应完成")
        finally:
            await asyncio.sleep(0)
            self.cleaned = True


async def wait_for_terminal(service: AgentRunService, run_id: str):
    for _ in range(200):
        snapshot = await service.store.get(run_id)
        if snapshot.status in {
            RunStatus.COMPLETED,
            RunStatus.PARTIALLY_COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return snapshot
        await asyncio.sleep(0.005)
    raise AssertionError("Run did not reach a terminal state")


def test_run_service_completes_with_ordered_terminal_event():
    async def scenario():
        store = InMemoryRunStore()
        service = AgentRunService(
            store=store,
            adapters={"chat": FakeAdapter()},
            heartbeat_seconds=60,
        )
        response = await service.create_run(make_request(), FastAPI())
        snapshot = await wait_for_terminal(service, response.run_id)
        events = await store.events_after(response.run_id)

        assert snapshot.status == RunStatus.COMPLETED
        assert snapshot.final_answer == "完成"
        assert snapshot.structured_result == {"source": "fake"}
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert events[0].event == EventType.AGENT_STARTED
        assert events[-1].event == EventType.AGENT_COMPLETED
        assert snapshot.last_sequence == events[-1].sequence

    asyncio.run(scenario())


def test_request_id_is_idempotent_and_conflicts_on_changed_body():
    async def scenario():
        service = AgentRunService(
            adapters={"chat": FakeAdapter()}, heartbeat_seconds=60
        )
        app = FastAPI()
        first = await service.create_run(make_request(), app)
        second = await service.create_run(make_request(), app)
        assert first.run_id == second.run_id

        with pytest.raises(AgentApiException) as exc_info:
            await service.create_run(
                make_request(content="相同 request_id 的不同内容"), app
            )
        assert exc_info.value.error.error_code == "IDEMPOTENCY_CONFLICT"
        await wait_for_terminal(service, first.run_id)

    asyncio.run(scenario())


def test_cancel_emits_single_terminal_event():
    async def scenario():
        store = InMemoryRunStore()
        service = AgentRunService(
            store=store,
            adapters={"chat": SlowAdapter()},
            heartbeat_seconds=60,
        )
        response = await service.create_run(
            make_request(request_id="req-cancel-001"), FastAPI()
        )
        await asyncio.sleep(0.01)
        snapshot = await service.cancel_run(response.run_id)
        await asyncio.sleep(0)
        events = await store.events_after(response.run_id)

        assert snapshot.status == RunStatus.CANCELLED
        terminal_events = [
            event
            for event in events
            if event.event
            in {
                EventType.AGENT_COMPLETED,
                EventType.AGENT_FAILED,
                EventType.AGENT_CANCELLED,
            }
        ]
        assert [event.event for event in terminal_events] == [
            EventType.AGENT_CANCELLED
        ]

    asyncio.run(scenario())


def test_cancel_waits_for_adapter_cleanup():
    async def scenario():
        adapter = CleanupAwareAdapter()
        service = AgentRunService(
            adapters={"chat": adapter},
            heartbeat_seconds=60,
            cancel_grace_seconds=1,
        )
        response = await service.create_run(
            make_request(request_id="req-cancel-cleanup-001"), FastAPI()
        )
        await asyncio.sleep(0.01)

        snapshot = await service.cancel_run(response.run_id)

        assert snapshot.status == RunStatus.CANCELLED
        assert adapter.cleaned is True

    asyncio.run(scenario())


def test_complete_and_cancel_race_has_only_one_terminal_event():
    async def scenario():
        store = InMemoryRunStore()
        request = make_request(request_id="req-race-001")
        snapshot, _ = await store.create(request)
        await store.set_status(snapshot.run_id, RunStatus.RUNNING)

        await asyncio.gather(
            store.complete_with_event(snapshot.run_id, final_answer="完成"),
            store.cancel_with_event(snapshot.run_id),
        )
        events = await store.events_after(snapshot.run_id)
        terminal_events = [
            event
            for event in events
            if event.event
            in {
                EventType.AGENT_COMPLETED,
                EventType.AGENT_FAILED,
                EventType.AGENT_CANCELLED,
            }
        ]
        assert len(terminal_events) == 1

    asyncio.run(scenario())


def test_attachment_request_fails_explicitly_in_first_iteration():
    async def scenario():
        service = AgentRunService(
            adapters={"chat": FakeAdapter()}, heartbeat_seconds=60
        )
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-attachment-001",
                "session": {
                    "session_id": "session-001",
                    "user_id": "user-001",
                },
                "message": {"role": "user", "content": "处理附件"},
                "attachments": [
                    {
                        "file_id": "file-001",
                        "kind": "image",
                        "name": "declaration.png",
                    }
                ],
            }
        )
        response = await service.create_run(request, FastAPI())
        snapshot = await wait_for_terminal(service, response.run_id)
        assert snapshot.status == RunStatus.FAILED
        assert snapshot.error.error_code == "ATTACHMENT_SUPPORT_PENDING"

    asyncio.run(scenario())


def test_stale_context_version_is_rejected():
    async def scenario():
        service = AgentRunService(
            adapters={"chat": FakeAdapter()}, heartbeat_seconds=60
        )
        first = make_request(request_id="req-context-001")
        first.session.context_version = 3
        created = await service.create_run(first, FastAPI())
        await wait_for_terminal(service, created.run_id)

        stale = make_request(request_id="req-context-002")
        stale.session.context_version = 2
        with pytest.raises(AgentApiException) as exc_info:
            await service.create_run(stale, FastAPI())
        assert exc_info.value.error.error_code == "SESSION_CONTEXT_CONFLICT"

    asyncio.run(scenario())


def test_auto_with_declaration_data_stays_on_general_agent():
    request = CreateRunRequest.model_validate(
        {
            "request_id": "req-auto-declaration-001",
            "session": {
                "session_id": "session-001",
                "user_id": "user-001",
                "tenant_id": "tenant-001",
            },
            "message": {"content": "只审查这份报关单，不要计算税费"},
            "business_context": {
                "declaration_text": "HS编码 85423100，CIF价格 10000 美元",
            },
            "options": {"intent": "auto"},
        }
    )

    assert AgentRunService._select_adapter(request) == "chat"


def test_full_review_requires_explicit_intent():
    request = CreateRunRequest.model_validate(
        {
            "request_id": "req-explicit-full-review-001",
            "session": {
                "session_id": "session-001",
                "user_id": "user-001",
                "tenant_id": "tenant-001",
            },
            "message": {"content": "执行完整审查流程"},
            "business_context": {"declaration_text": "HS编码 85423100"},
            "options": {"intent": "full_review"},
        }
    )

    assert AgentRunService._select_adapter(request) == "full_review"
