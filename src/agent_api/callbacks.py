from __future__ import annotations

from urllib.parse import urlparse

import httpx

from .models import RunSnapshot


class CompletionCallbackClient:
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        service_key: str = "",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.allowed_hosts = {
            host.lower() for host in allowed_hosts if host
        }
        self.service_key = service_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def notify(self, url: str, snapshot: RunSnapshot) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise ValueError("completion callback must use https")
        if not self.allowed_hosts or host not in self.allowed_hosts:
            raise ValueError("completion callback host is not allowed")

        headers = {}
        if self.service_key:
            headers["X-Agent-Service-Key"] = self.service_key
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=snapshot.model_dump(mode="json", exclude_none=True),
            )
            response.raise_for_status()
