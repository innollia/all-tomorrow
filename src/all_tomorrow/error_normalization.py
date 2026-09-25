from __future__ import annotations

import asyncio
from typing import Any

from all_tomorrow.domain.errors import (
    ActiveRunLimitExceededError,
    CanonicalError,
    ErrorCategory,
    InvalidStateTransitionError,
    InvariantViolationError,
    MissingCompletionEvidenceError,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
)


def normalize_exception(
    exc: BaseException,
    default_code: str = "internal_error",
    external_ref: str | None = None,
    evidence_refs: tuple[str, ...] = ()
) -> CanonicalError:
    """Normalizes arbitrary backend/vendor/python exceptions into a CanonicalError.

    CRITICAL INVARIANTS:
    - NOT_FOUND and UNAVAILABLE must never be merged.
    - TIMEOUT and AMBIGUOUS_EFFECT must be strictly distinguished.
    """
    msg = str(exc)
    exc_type_name = type(exc).__name__

    # 1. Invariant violations
    if isinstance(exc, (TerminalReviveError, WorkExecutionRefForbiddenError, ActiveRunLimitExceededError)):
        return CanonicalError(
            category=ErrorCategory.INVARIANT_VIOLATION,
            code=f"invariant_{exc_type_name.lower()}",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Architectural invariant violation",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )
    if isinstance(exc, InvariantViolationError):
        return CanonicalError(
            category=ErrorCategory.INVARIANT_VIOLATION,
            code="invariant_violation",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Invariant violation",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # 2. State & completion evidence
    if isinstance(exc, InvalidStateTransitionError):
        return CanonicalError(
            category=ErrorCategory.INVALID_STATE,
            code="invalid_state_transition",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Invalid state transition",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )
    if isinstance(exc, MissingCompletionEvidenceError):
        return CanonicalError(
            category=ErrorCategory.INVALID_STATE,
            code="missing_completion_evidence",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Missing completion evidence",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # 3. Timeouts (ambiguity is True because side effect may have been initiated)
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in exc_type_name.lower():
        return CanonicalError(
            category=ErrorCategory.TIMEOUT,
            code="operation_timeout",
            retryability=True,
            ambiguity=True,
            safe_message="Operation timed out before confirmation",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # 4. Connection / Availability issues (NOT NOT_FOUND)
    cause_msg = str(exc.__cause__) if exc.__cause__ else ""
    cause_name = type(exc.__cause__).__name__ if exc.__cause__ else ""
    if (
        isinstance(exc, (ConnectionRefusedError, ConnectionResetError, ConnectionError))
        or "connect" in exc_type_name.lower()
        or "connect" in msg.lower()
        or (exc.__cause__ is not None and (
            isinstance(exc.__cause__, (ConnectionRefusedError, ConnectionResetError, ConnectionError))
            or "connect" in cause_name.lower()
            or "connect" in cause_msg.lower()
        ))
    ):
        return CanonicalError(
            category=ErrorCategory.UNAVAILABLE,
            code="service_unavailable",
            retryability=True,
            ambiguity=False,
            safe_message="External service connection failed",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # 5. HTTP-like / Provider-like exceptions by attributes or messages
    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status_code is not None:
        if status_code == 404:
            return CanonicalError(
                category=ErrorCategory.NOT_FOUND,
                code="http_not_found",
                retryability=False,
                ambiguity=False,
                safe_message="Target resource was not found",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )
        if status_code == 429:
            return CanonicalError(
                category=ErrorCategory.RATE_LIMITED,
                code="rate_limited",
                retryability=True,
                ambiguity=False,
                safe_message="Upstream rate limit exceeded",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )
        if status_code == 401:
            return CanonicalError(
                category=ErrorCategory.AUTHENTICATION_FAILED,
                code="authentication_failed",
                retryability=False,
                ambiguity=False,
                authority_security_relevance=True,
                safe_message="Authentication credentials invalid or missing",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )
        if status_code == 403:
            return CanonicalError(
                category=ErrorCategory.PERMISSION_DENIED,
                code="permission_denied",
                retryability=False,
                ambiguity=False,
                authority_security_relevance=True,
                safe_message="Permission denied for requested action",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )
        if status_code == 409:
            return CanonicalError(
                category=ErrorCategory.CONFLICT,
                code="resource_conflict",
                retryability=False,
                ambiguity=False,
                safe_message="Conflict with existing resource state",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )
        if status_code in (502, 503, 504):
            return CanonicalError(
                category=ErrorCategory.UNAVAILABLE,
                code="service_unavailable",
                retryability=True,
                ambiguity=(status_code == 504),
                safe_message="Upstream gateway or service unavailable",
                external_ref=external_ref,
                evidence_refs=evidence_refs,
                caused_by=exc_type_name,
            )

    # 6. Key / Lookup not found (explicit NOT_FOUND, never UNAVAILABLE)
    if isinstance(exc, KeyError) or "not found" in msg.lower():
        return CanonicalError(
            category=ErrorCategory.NOT_FOUND,
            code="resource_not_found",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Resource not found",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # 7. Validation / Input errors
    if isinstance(exc, (ValueError, TypeError)):
        return CanonicalError(
            category=ErrorCategory.INVALID_INPUT,
            code="invalid_input",
            retryability=False,
            ambiguity=False,
            safe_message=msg or "Invalid input or argument",
            external_ref=external_ref,
            evidence_refs=evidence_refs,
            caused_by=exc_type_name,
        )

    # Default fallback
    return CanonicalError(
        category=ErrorCategory.UNAVAILABLE,
        code=default_code,
        retryability=False,
        ambiguity=True,
        safe_message=f"Unhandled exception: {exc_type_name}",
        external_ref=external_ref,
        evidence_refs=evidence_refs,
        caused_by=exc_type_name,
    )
