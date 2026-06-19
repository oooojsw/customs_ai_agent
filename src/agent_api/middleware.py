from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AgentTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Request-ID") or f"trace-{uuid4().hex}"
        request.state.agent_trace_id = trace_id
        response = await call_next(request)
        if request.url.path.startswith("/api/agent/v1"):
            response.headers["X-Request-ID"] = trace_id
        return response
