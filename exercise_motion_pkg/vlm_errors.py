from __future__ import annotations

import subprocess
from typing import Any

import httpx


class CriticalVlmInteractionError(RuntimeError):
    """Raised when a VLM infrastructure failure must abort the current run."""

    def __init__(
        self,
        message: str,
        *,
        interaction: str,
        recoverable: bool = False,
        timeout_seconds: float | None = None,
        cause_type: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.interaction = interaction
        self.recoverable = recoverable
        self.timeout_seconds = timeout_seconds
        self.cause_type = cause_type
        self.details = dict(details or {})

    def add_details(self, **details: Any) -> "CriticalVlmInteractionError":
        self.details.update({key: value for key, value in details.items() if value is not None})
        return self


def is_critical_vlm_interaction_error(exc: BaseException) -> bool:
    return critical_vlm_interaction_error(exc) is not None


def critical_vlm_interaction_error(exc: BaseException) -> CriticalVlmInteractionError | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, CriticalVlmInteractionError):
            return current
        current = current.__cause__ or current.__context__
    return None


def add_vlm_context(exc: BaseException, **details: Any) -> CriticalVlmInteractionError | None:
    critical = critical_vlm_interaction_error(exc)
    if critical is not None:
        critical.add_details(**details)
    return critical


def wrap_vlm_infrastructure_error(
    exc: BaseException,
    *,
    interaction: str,
    timeout_seconds: float | None = None,
) -> CriticalVlmInteractionError | None:
    existing = critical_vlm_interaction_error(exc)
    if existing is not None:
        return existing
    if isinstance(exc, httpx.TimeoutException):
        return CriticalVlmInteractionError(
            f"Critical VLM timeout during {interaction}: {exc}",
            interaction=interaction,
            recoverable=True,
            timeout_seconds=timeout_seconds,
            cause_type=type(exc).__name__,
            details={"originalError": str(exc)},
        )
    if isinstance(exc, (httpx.TransportError, TimeoutError, subprocess.TimeoutExpired)):
        return CriticalVlmInteractionError(
            f"Critical VLM transport failure during {interaction}: {type(exc).__name__}: {exc}",
            interaction=interaction,
            recoverable=True,
            timeout_seconds=timeout_seconds,
            cause_type=type(exc).__name__,
            details={"originalError": str(exc)},
        )
    return None


def critical_vlm_http_status_error(
    *,
    interaction: str,
    status_code: int,
    body: str,
    image_count: int,
    image_bytes: int,
    prompt_chars: int,
) -> CriticalVlmInteractionError:
    recoverable = status_code >= 500 or status_code in {408, 409, 425, 429}
    return CriticalVlmInteractionError(
        "Critical VLM HTTP failure during "
        f"{interaction}: status={status_code} images={image_count} "
        f"imageBytes={image_bytes} promptChars={prompt_chars} body={body}",
        interaction=interaction,
        recoverable=recoverable,
        cause_type=f"HTTP{status_code}",
        details={
            "statusCode": status_code,
            "body": body,
            "imageCount": image_count,
            "imageBytes": image_bytes,
            "promptChars": prompt_chars,
        },
    )


def vlm_error_payload(exc: BaseException) -> dict[str, Any]:
    critical = critical_vlm_interaction_error(exc)
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "critical": critical is not None,
        **(
            {
                "interaction": critical.interaction,
                "recoverable": critical.recoverable,
                "timeoutSeconds": critical.timeout_seconds,
                "causeType": critical.cause_type,
                "details": critical.details,
            }
            if critical is not None
            else {}
        ),
    }
