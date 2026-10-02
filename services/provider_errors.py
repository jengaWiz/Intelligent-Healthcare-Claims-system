"""Safe integration failures: workers own retries, providers never return fake success."""

import math
from enum import StrEnum

import httpx
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from openai import APIConnectionError, APITimeoutError

from config.settings import ConfigurationError


class FailureCode(StrEnum):
    CONFIGURATION = "provider_configuration"
    TIMEOUT = "provider_timeout"
    RATE_LIMITED = "provider_rate_limited"
    UNAVAILABLE = "provider_unavailable"
    REJECTED = "provider_rejected"
    INVALID_RESPONSE = "invalid_provider_response"
    EMPTY_OCR = "empty_ocr"
    EMPTY_INPUT = "empty_extraction_input"
    DOCUMENT_READ = "document_read_failed"


class ProviderFailure(Exception):
    def __init__(self, stage: str, code: FailureCode, retryable=False, retry_after=None):
        self.stage = stage
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(f"{stage}: {code.value}")

    def as_dict(self):
        return {
            "stage": self.stage,
            "code": self.code.value,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
        }


def classify_failure(exc: Exception, stage: str) -> ProviderFailure:
    if isinstance(exc, ProviderFailure):
        return exc
    if isinstance(exc, ConfigurationError):
        return ProviderFailure(stage, FailureCode.CONFIGURATION)
    # LangChain wraps Google failures; inspect types/status only, never their text.
    cause = exc
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
            return ProviderFailure(stage, FailureCode.TIMEOUT, True)
        response = getattr(cause, "response", None)
        status = getattr(cause, "status_code", None) or getattr(cause, "code", None)
        status = status or getattr(response, "status_code", None)
        if status == 429:
            headers = getattr(response, "headers", {}) or {}
            try:
                delay = float(headers.get("Retry-After", "0"))
                delay = min(60.0, max(0.0, delay)) if math.isfinite(delay) else None
            except (ValueError, TypeError):
                delay = None
            return ProviderFailure(stage, FailureCode.RATE_LIMITED, True, delay)
        if status in {408, 500, 502, 503, 504}:
            return ProviderFailure(stage, FailureCode.UNAVAILABLE, True)
        if isinstance(status, int) and 400 <= status < 500:
            return ProviderFailure(stage, FailureCode.REJECTED)
        if isinstance(
            cause,
            (
                ServiceRequestError,
                ServiceResponseError,
                httpx.NetworkError,
                APIConnectionError,
                ConnectionError,
            ),
        ):
            return ProviderFailure(stage, FailureCode.UNAVAILABLE, True)
        cause = cause.__cause__
    return ProviderFailure(stage, FailureCode.UNAVAILABLE)
