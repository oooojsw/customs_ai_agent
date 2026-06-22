from __future__ import annotations

from .models import AgentError


class AgentApiException(Exception):
    def __init__(self, error: AgentError, http_status: int = 500):
        super().__init__(error.message)
        self.error = error
        self.http_status = http_status


def error_from_exception(
    exc: Exception,
    *,
    error_code: str = "INTERNAL_ERROR",
    stage: str | None = None,
    retryable: bool = False,
) -> AgentError:
    return AgentError(
        error_code=error_code,
        message=str(exc) or exc.__class__.__name__,
        retryable=retryable,
        stage=stage,
        details={"exception_type": exc.__class__.__name__},
    )
