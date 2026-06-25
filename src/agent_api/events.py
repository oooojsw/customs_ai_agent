from __future__ import annotations

import json
from typing import Any

from .errors import AgentApiException
from .models import AgentEvent, EventType, utc_now
from .store import InMemoryRunStore


class EventEmitter:
    def __init__(self, store: InMemoryRunStore, run_id: str):
        self._store = store
        self.run_id = run_id
        self._active_tools: dict[str, dict[str, Any]] = {}

    async def emit(self, event_type: EventType, **data: Any) -> AgentEvent:
        return await self._store.append_event(self.run_id, event_type, data)

    async def status(self, phase: str, message: str | None = None) -> AgentEvent:
        data: dict[str, Any] = {"phase": phase}
        if message:
            data["message"] = message
        return await self.emit(EventType.STATUS_CHANGED, **data)

    async def tool_started(
        self,
        tool: str,
        display_name: str,
        **metadata: Any,
    ) -> AgentEvent:
        payload = {
            "tool": tool,
            "display_name": display_name,
            "status": metadata.pop("status", "running"),
            "interaction_kind": metadata.pop("interaction_kind", "agent_tool"),
            "auto_expand": metadata.pop("auto_expand", False),
            "started_at": metadata.pop("started_at", utc_now().isoformat()),
            **metadata,
        }
        self._active_tools[tool] = {
            "display_name": display_name,
            "interaction_kind": payload["interaction_kind"],
            "auto_expand": payload["auto_expand"],
        }
        return await self.emit(
            EventType.TOOL_STARTED,
            **payload,
        )

    async def tool_finished(
        self,
        tool: str,
        display_name: str,
        summary: str = "",
        **metadata: Any,
    ) -> AgentEvent:
        payload = {
            "tool": tool,
            "display_name": display_name,
            "status": metadata.pop("status", "success"),
            "interaction_kind": metadata.pop("interaction_kind", "agent_tool"),
            "auto_expand": metadata.pop("auto_expand", False),
            "summary": summary,
            "finished_at": metadata.pop("finished_at", utc_now().isoformat()),
            **metadata,
        }
        self._active_tools.pop(tool, None)
        return await self.emit(
            EventType.TOOL_FINISHED,
            **payload,
        )

    async def close_active_tools_as_failed(
        self,
        summary: str,
    ) -> None:
        active_tools = list(self._active_tools.items())
        for tool, details in active_tools:
            try:
                await self.tool_finished(
                    tool,
                    str(details.get("display_name") or tool),
                    summary,
                    status="error",
                    interaction_kind=str(
                        details.get("interaction_kind") or "agent_tool"
                    ),
                    auto_expand=bool(details.get("auto_expand", False)),
                )
            except AgentApiException as exc:
                if exc.error.error_code == "RUN_ALREADY_TERMINAL":
                    return
                raise


def format_sse(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json", exclude_none=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event.value}\ndata: {data}\n\n"
