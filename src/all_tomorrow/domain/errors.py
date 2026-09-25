from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_STATE = "INVALID_STATE"
    CONFLICT = "CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class CanonicalError:
    """Normalized cross-plane error contract."""
    category: ErrorCategory
    code: str
    retryability: bool
    ambiguity: bool
    authority_security_relevance: bool = False
    safe_message: str = ""
    external_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    caused_by: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.category, ErrorCategory):
            raise ValueError(f"category must be an ErrorCategory enum, got {self.category!r}")
        if not self.code or not self.code.strip():
            raise ValueError("code must be a non-empty string")


class DomainError(Exception):
    """Base exception for domain contract violations."""


class InvariantViolationError(DomainError):
    """Raised when an architectural or control-plane invariant is violated."""


class TerminalReviveError(InvariantViolationError):
    """Raised when attempting to revive or transition an already terminal entity."""


class ActiveRunLimitExceededError(InvariantViolationError):
    """Raised when a Work attempts to run more active Runs than permitted by policy."""


class WorkExecutionRefForbiddenError(InvariantViolationError):
    """Raised when an ExecutionRef is attached to Work instead of Run."""


class MissingCompletionEvidenceError(DomainError):
    """Raised when Work or Goal is marked SUCCEEDED without verified CompletionEvidence."""


class InvalidStateTransitionError(DomainError):
    """Raised when an illegal state transition is requested."""
