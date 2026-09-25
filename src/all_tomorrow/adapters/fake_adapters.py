from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, RunId, utc_now
from all_tomorrow.ports.agent import (
    AgentExecutionPort,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentUsage,
)
from all_tomorrow.ports.durable import (
    CancelOutcome,
    CancelResult,
    DurableExecutionPort,
    DurableExecutionState,
    ExecutionResult,
    ExecutionStatusResult,
    SignalOutcome,
    SignalResult,
)
from all_tomorrow.ports.tools import (
    SideEffectClass,
    ToolDescriptor,
    ToolExecutionPort,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from all_tomorrow.ports.workers import (
    WorkerDescriptor,
    WorkerExecutionPort,
    WorkerExecutionRequest,
    WorkerExecutionResult,
)


@dataclass
class _ExecutionStateInternal:
    ref: ExecutionRef
    workflow_name: str
    payload: dict[str, Any]
    state: DurableExecutionState
    signals: set[str] = field(default_factory=set)
    result_payload: Any = None
    is_completed: bool = False
    updated_at: datetime = field(default_factory=utc_now)


class FakeDurableAdapter(DurableExecutionPort):
    """Fake durable execution adapter implementing all required port semantics."""

    def __init__(self, backend_name: str = "fake_durable") -> None:
        self.backend_name = backend_name
        self._runs_to_ref: dict[str, ExecutionRef] = {}
        self._executions: dict[str, _ExecutionStateInternal] = {}
        self.simulate_unavailable: bool = False

    async def start(
        self,
        run_id: RunId,
        workflow_name: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ExecutionRef:
        if self.simulate_unavailable:
            raise ConnectionError("Simulated backend unavailable")

        run_key = str(run_id)
        # S0-00B2-01: Same run_id start idempotency
        if run_key in self._runs_to_ref:
            return self._runs_to_ref[run_key]

        ref = ExecutionRef(
            backend=self.backend_name,
            execution_id=f"exec_{run_key}",
            execution_version=1,
        )
        self._runs_to_ref[run_key] = ref
        self._executions[ref.execution_id] = _ExecutionStateInternal(
            ref=ref,
            workflow_name=workflow_name,
            payload=payload,
            state=DurableExecutionState.RUNNING,
        )
        return ref

    async def get_status(self, ref: ExecutionRef) -> ExecutionStatusResult:
        if self.simulate_unavailable:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.PENDING,
                error=CanonicalError(
                    category=ErrorCategory.UNAVAILABLE,
                    code="backend_unavailable",
                    retryability=True,
                    ambiguity=False,
                ),
            )
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.PENDING,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="execution_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        return ExecutionStatusResult(ref=ref, state=internal.state, updated_at=internal.updated_at)

    async def find_by_run_id(self, run_id: RunId) -> ExecutionRef | None:
        if self.simulate_unavailable:
            raise ConnectionError("Simulated backend unavailable")
        return self._runs_to_ref.get(str(run_id))

    async def cancel(self, ref: ExecutionRef) -> CancelResult:
        # S0-00B2-02: cancel terminal/missing/unavailable 분리
        if self.simulate_unavailable:
            return CancelResult(
                outcome=CancelOutcome.UNAVAILABLE,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.UNAVAILABLE,
                    code="backend_unavailable",
                    retryability=True,
                    ambiguity=False,
                ),
            )
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return CancelResult(
                outcome=CancelOutcome.NOT_FOUND,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="execution_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if internal.state in (
            DurableExecutionState.COMPLETED,
            DurableExecutionState.FAILED,
            DurableExecutionState.CANCELLED,
        ):
            return CancelResult(
                outcome=CancelOutcome.ALREADY_TERMINAL,
                ref=ref,
                details=f"Execution already in terminal state {internal.state.value}",
            )
        internal.state = DurableExecutionState.CANCELLED
        internal.updated_at = utc_now()
        return CancelResult(outcome=CancelOutcome.CANCEL_REQUESTED, ref=ref)

    async def signal(
        self,
        ref: ExecutionRef,
        signal_name: str,
        signal_id: str,
        payload: dict[str, Any],
    ) -> SignalResult:
        # S0-00B2-03: duplicate signal_id idempotency
        if self.simulate_unavailable:
            return SignalResult(
                outcome=SignalOutcome.NOT_FOUND,
                signal_id=signal_id,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.UNAVAILABLE,
                    code="backend_unavailable",
                    retryability=True,
                    ambiguity=False,
                ),
            )
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return SignalResult(
                outcome=SignalOutcome.NOT_FOUND,
                signal_id=signal_id,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="execution_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if signal_id in internal.signals:
            return SignalResult(
                outcome=SignalOutcome.DUPLICATE_IGNORED,
                signal_id=signal_id,
                ref=ref,
            )
        if internal.state in (
            DurableExecutionState.COMPLETED,
            DurableExecutionState.FAILED,
            DurableExecutionState.CANCELLED,
        ):
            return SignalResult(
                outcome=SignalOutcome.ALREADY_TERMINAL,
                signal_id=signal_id,
                ref=ref,
            )
        internal.signals.add(signal_id)
        return SignalResult(outcome=SignalOutcome.DELIVERED, signal_id=signal_id, ref=ref)

    async def complete_execution(self, ref: ExecutionRef, result_payload: Any) -> None:
        """Helper to mark execution as completed with a payload (including empty dict)."""
        internal = self._executions[ref.execution_id]
        internal.result_payload = result_payload
        internal.is_completed = True
        internal.state = DurableExecutionState.COMPLETED
        internal.updated_at = utc_now()

    async def result(
        self,
        ref: ExecutionRef,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        # S0-00B2-04: Pending vs empty result 분리
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return ExecutionResult(
                ref=ref,
                is_pending=False,
                state=DurableExecutionState.FAILED,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="execution_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if not internal.is_completed:
            return ExecutionResult(
                ref=ref,
                is_pending=True,
                payload=None,
                state=internal.state,
            )
        return ExecutionResult(
            ref=ref,
            is_pending=False,
            payload=internal.result_payload,
            state=DurableExecutionState.COMPLETED,
        )


class FakeAgentAdapter(AgentExecutionPort):
    """Fake agent execution adapter verifying malformed output handling."""

    def __init__(self) -> None:
        self.mock_response: dict[str, Any] | None = None
        self.fail_with_malformed_output: bool = False

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        if self.fail_with_malformed_output:
            # Malformed structured output MUST NOT be coerced to success
            return AgentExecutionResult(
                success=False,
                error=CanonicalError(
                    category=ErrorCategory.INVALID_INPUT,
                    code="malformed_structured_output",
                    retryability=False,
                    ambiguity=False,
                    safe_message="Structured output failed schema validation",
                ),
            )
        return AgentExecutionResult(
            success=True,
            output="Agent succeeded",
            structured_data=self.mock_response or {"status": "ok"},
            usage=AgentUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            provenance_ref=f"agent_inv_{request.model_route_ref}",
        )
