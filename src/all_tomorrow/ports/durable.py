from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, RunId, utc_now


class DurableExecutionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CancelOutcome(StrEnum):
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class SignalOutcome(StrEnum):
    DELIVERED = "DELIVERED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"


@dataclass(frozen=True, slots=True)
class CancelResult:
    outcome: CancelOutcome
    ref: ExecutionRef
    details: str = ""
    error: CanonicalError | None = None


@dataclass(frozen=True, slots=True)
class SignalResult:
    outcome: SignalOutcome
    signal_id: str
    ref: ExecutionRef
    delivered_at: datetime = field(default_factory=utc_now)
    error: CanonicalError | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusResult:
    ref: ExecutionRef
    state: DurableExecutionState
    updated_at: datetime = field(default_factory=utc_now)
    error: CanonicalError | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Distinctly separates pending execution from empty completed result."""
    ref: ExecutionRef
    is_pending: bool
    payload: Any = None
    state: DurableExecutionState = DurableExecutionState.PENDING
    error: CanonicalError | None = None


class DurableExecutionPort(Protocol):
    """Port interface for durable workflow backends (e.g. DBOS, Restate, Fake)."""

    async def start(
        self,
        run_id: RunId,
        workflow_name: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ExecutionRef:
        """Starts a durable execution.

        Must be idempotent for the same run_id / idempotency_key.
        """
        ...

    async def get_status(self, ref: ExecutionRef) -> ExecutionStatusResult:
        """Returns the current status of the external execution."""
        ...

    async def find_by_run_id(self, run_id: RunId) -> ExecutionRef | None:
        """Discovers existing execution ref from the external engine without guessing IDs."""
        ...

    async def cancel(self, ref: ExecutionRef) -> CancelResult:
        """Requests cancellation of external execution.

        Must distinguish ALREADY_TERMINAL, NOT_FOUND, and UNAVAILABLE.
        """
        ...

    async def signal(
        self,
        ref: ExecutionRef,
        signal_name: str,
        signal_id: str,
        payload: dict[str, Any],
    ) -> SignalResult:
        """Delivers a durable signal.

        Must be idempotent for duplicate signal_id.
        """
        ...

    async def result(
        self,
        ref: ExecutionRef,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Retrieves the result of the execution.

        Must distinctly separate PENDING from an empty completed result.
        """
        ...
