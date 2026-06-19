from __future__ import annotations

import json
from typing import Any

from .models import AgentEvent, EventType
from .store import InMemoryRunStore


class EventEmitter:
    def __init__(self, store: InMemoryRunStore, run_id: str):
        self._store = store
        self.run_id = run_id

    async def emit(self, event_type: EventType, **data: Any) -> AgentEvent:
        return await self._store.append_event(self.run_id, event_type, data)

    async def status(self, phase: str, message: str | None = None) -> AgentEvent:
        data: dict[str, Any] = {"phase": phase}
        if message:
            data["message"] = message
        return await self.emit(EventType.STATUS_CHANGED, **data)

    async def tool_started(self, tool: str, display_name: str) -> AgentEvent:
        return await self.emit(
            EventType.TOOL_STARTED,
            tool=tool,
            display_name=display_name,
        )

    async def tool_finished(
        self, tool: str, display_name: str, summary: str = ""
    ) -> AgentEvent:
        return await self.emit(
            EventType.TOOL_FINISHED,
            tool=tool,
            display_name=display_name,
            summary=summary,
        )


def format_sse(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json", exclude_none=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event.value}\ndata: {data}\n\n"
