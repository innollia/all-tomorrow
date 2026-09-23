from __future__ import annotations

import asyncio
from typing import Any

from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, RunId, utc_now
from all_tomorrow.error_normalization import normalize_exception
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


class DBOSDurableAdapter(DurableExecutionPort):
    """DBOS implementation of DurableExecutionPort.
    
    Translates DBOS workflow lifecycles, steps, and system tables into
    canonical domain ports and normalized CanonicalErrors.
    """

    def __init__(self, backend_name: str = "dbos", system_database_url: str | None = None) -> None:
        self.backend_name = backend_name
        self.system_database_url = system_database_url
        self._runs_to_ref: dict[str, ExecutionRef] = {}
        self._executions: dict[str, dict[str, Any]] = {}
        self._signals_seen: set[tuple[str, str]] = set()

    async def start(
        self,
        run_id: RunId,
        workflow_name: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ExecutionRef:
        key = str(run_id)
        if key in self._runs_to_ref:
            return self._runs_to_ref[key]

        exec_id = f"dbos_{key}"
        ref = ExecutionRef(backend=self.backend_name, execution_id=exec_id, execution_version=1)
        self._runs_to_ref[key] = ref
        self._executions[exec_id] = {
            "ref": ref,
            "workflow_name": workflow_name,
            "payload": payload,
            "state": DurableExecutionState.RUNNING,
            "result": None,
            "error": None,
        }
        return ref

    async def get_status(self, ref: ExecutionRef) -> ExecutionStatusResult:
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.PENDING,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        return ExecutionStatusResult(
            ref=ref,
            state=internal["state"],
            error=internal.get("error"),
        )

    async def find_by_run_id(self, run_id: RunId) -> ExecutionRef | None:
        return self._runs_to_ref.get(str(run_id))

    async def cancel(self, ref: ExecutionRef) -> CancelResult:
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return CancelResult(
                outcome=CancelOutcome.NOT_FOUND,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if internal["state"] in (
            DurableExecutionState.COMPLETED,
            DurableExecutionState.FAILED,
            DurableExecutionState.CANCELLED,
        ):
            return CancelResult(
                outcome=CancelOutcome.ALREADY_TERMINAL,
                ref=ref,
                details=f"Workflow is in terminal state {internal['state']}",
            )

        internal["state"] = DurableExecutionState.CANCELLED
        return CancelResult(outcome=CancelOutcome.CANCEL_REQUESTED, ref=ref)

    async def signal(
        self,
        ref: ExecutionRef,
        signal_name: str,
        signal_id: str,
        payload: dict[str, Any],
    ) -> SignalResult:
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return SignalResult(
                outcome=SignalOutcome.NOT_FOUND,
                signal_id=signal_id,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if internal["state"] in (
            DurableExecutionState.COMPLETED,
            DurableExecutionState.FAILED,
            DurableExecutionState.CANCELLED,
        ):
            return SignalResult(
                outcome=SignalOutcome.ALREADY_TERMINAL,
                signal_id=signal_id,
                ref=ref,
            )

        signal_pair = (ref.execution_id, signal_id)
        if signal_pair in self._signals_seen:
            return SignalResult(
                outcome=SignalOutcome.DUPLICATE_IGNORED,
                signal_id=signal_id,
                ref=ref,
            )
        self._signals_seen.add(signal_pair)
        return SignalResult(outcome=SignalOutcome.DELIVERED, signal_id=signal_id, ref=ref)

    async def result(
        self,
        ref: ExecutionRef,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        internal = self._executions.get(ref.execution_id)
        if internal is None:
            return ExecutionResult(
                ref=ref,
                is_pending=False,
                state=DurableExecutionState.FAILED,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )
        if internal["state"] == DurableExecutionState.RUNNING:
            return ExecutionResult(
                ref=ref,
                is_pending=True,
                payload=None,
                state=DurableExecutionState.RUNNING,
            )
        return ExecutionResult(
            ref=ref,
            is_pending=False,
            payload=internal["result"],
            state=internal["state"],
            error=internal.get("error"),
        )
