from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Request

from .errors import AgentApiException
from .models import AgentError


@dataclass(frozen=True)
class CallerIdentity:
    tenant_id: str | None
    service_name: str | None = None


class ServiceAuthenticator:
    def __init__(self, *, enabled: bool, api_key: str) -> None:
        self.enabled = enabled
        self.api_key = api_key

    def authenticate(self, request: Request) -> CallerIdentity:
        tenant_id = request.headers.get("X-Tenant-ID")
        service_name = request.headers.get("X-Service-Name")
        if not self.enabled:
            return CallerIdentity(tenant_id=tenant_id, service_name=service_name)

        provided = request.headers.get("X-Agent-Service-Key", "")
        if not provided or not secrets.compare_digest(provided, self.api_key):
            raise AgentApiException(
                AgentError(
                    error_code="SERVICE_AUTH_FAILED",
                    message="平台服务凭证无效",
                    retryable=False,
                    stage="authentication",
                ),
                http_status=401,
            )
        if not tenant_id:
            raise AgentApiException(
                AgentError(
                    error_code="TENANT_HEADER_REQUIRED",
                    message="缺少 X-Tenant-ID",
                    retryable=False,
                    stage="authentication",
                ),
                http_status=400,
            )
        return CallerIdentity(tenant_id=tenant_id, service_name=service_name)

    @staticmethod
    def require_tenant(identity: CallerIdentity, tenant_id: str) -> None:
        if identity.tenant_id and identity.tenant_id != tenant_id:
            raise AgentApiException(
                AgentError(
                    error_code="TENANT_ACCESS_DENIED",
                    message="无权访问其他租户资源",
                    retryable=False,
                    stage="authorization",
                ),
                http_status=403,
            )
