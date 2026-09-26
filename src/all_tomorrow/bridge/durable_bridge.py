"""01C — Durable Execution Bridge.

Wires a semantic Run (01B ``GoalWorkRunStore``) to a durable backend behind the
00B ``DurableExecutionPort`` (DBOS/Fake/…), implementing the cross-store start
and reconciliation protocol of docs/roadmap/failure-recovery-contract.md §3.

No custom DurableWorkQueue, no lease/heartbeat daemon: ordering and flow control
belong to the selected backend adapter. This module owns only the semantic
Run⇄ExecutionRef linkage and the crash-window reconciliation between the
application DB and durable state.

Start protocol (never a distributed transaction):

1. Run committed STARTING in the store.
2. ``port.start(run_id)`` — idempotent on run_id, so a duplicate converges to one
   external execution.
3. ExecutionRef attach via compare-and-set (store enforces fail-closed).
4. Transition Run STARTING → RUNNING after the ref is attached.

Reconciliation (for STARTING Runs with no ExecutionRef after a crash):

1. Take a candidate (store revision guards single-owner effect).
2. ``port.find_by_run_id`` to recover an existing execution, else idempotent
   ``port.start``.
3. Attach the ref via CAS; a divergent already-attached ref fails closed.
4. Bounded attempts; permanent failure records an explicit FAILED + Event, never
   silently forged success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.domain.ids import ExecutionRef, RunId, WorkId, new_event_id
from all_tomorrow.domain.state import RunRecord, RunStatus
from all_tomorrow.ports.durable import DurableExecutionPort, DurableExecutionState
from all_tomorrow.storage.semantic_store import (
    ExecutionRefConflictError,
    GoalWorkRunStore,
    SemanticEvent,
    StoreConflictError,
)


class ReconciliationExhaustedError(InvariantViolationError):
    """Bounded reconciliation attempts were exhausted without a stable ref."""


@dataclass(frozen=True, slots=True)
class BridgeResult:
    run: RunRecord
    ref: ExecutionRef
    recovered: bool  # True when an existing external execution was recovered


def _event(actor: str, type_: str, run: RunRecord, **payload: Any) -> SemanticEvent:
    return SemanticEvent(
        event_id=new_event_id(),
        actor=actor,
        type=type_,
        work_id=run.work_id,
        run_id=run.run_id,
        payload=dict(payload),
    )


class DurableRunBridge:
    """Bridges semantic Runs to a durable backend without a custom queue."""

    def __init__(
        self,
        store: GoalWorkRunStore,
        port: DurableExecutionPort,
        *,
        actor: str = "durable_bridge",
        max_reconcile_attempts: int = 3,
    ) -> None:
        self.store = store
        self.port = port
        self.actor = actor
        self.max_reconcile_attempts = max_reconcile_attempts

    # -- Start protocol -----------------------------------------------------
    async def start_run(
        self,
        run: RunRecord,
        workflow_name: str,
        payload: dict[str, Any],
        run_revision: int,
    ) -> BridgeResult:
        """Runs steps 2–4 for a Run already committed STARTING in the store.

        The Run itself must already exist in the store (step 1) — the caller owns
        the application-DB commit so the DB is the durable source of intent even
        if this process crashes before the external start.
        """
        if run.status != RunStatus.STARTING:
            raise InvariantViolationError(
                f"start_run requires a STARTING run, got {run.status.value}"
            )
        # Step 2: idempotent external start keyed on run_id.
        ref = await self.port.start(run.run_id, workflow_name, payload, idempotency_key=str(run.run_id))
        # Step 3: attach ref via CAS.
        attached = await self.store.attach_execution_ref(
            run.run_id, run_revision, ref,
            _event(self.actor, "run.execution_ref_attached", run, backend=ref.backend),
        )
        # Step 4: transition to RUNNING now the ref is durable.
        new_rev = _current_run_revision(self.store, run.run_id, attached)
        running = await self.store.transition_run_status(
            run.run_id, RunStatus.RUNNING, new_rev,
            _event(self.actor, "run.running", attached),
        )
        return BridgeResult(run=running, ref=ref, recovered=False)

    # -- Reconciliation -----------------------------------------------------
    async def reconcile_starting_runs(self) -> list[BridgeResult]:
        """Reconcile every STARTING Run that has no ExecutionRef yet.

        Recovers an existing external execution when one exists (crash after
        external start, before attach), else performs an idempotent start.
        Divergent refs fail closed; exhausted attempts mark the Run FAILED.
        """
        candidates = await self.store.find_reconciliation_candidates()
        results: list[BridgeResult] = []
        for run in candidates:
            results.append(await self._reconcile_one(run))
        return results

    async def _reconcile_one(self, run: RunRecord) -> BridgeResult:
        last_exc: Exception | None = None
        for _attempt in range(self.max_reconcile_attempts):
            # Re-read to observe another reconciler's attach and current revision.
            current = await self.store.get_run(run.run_id)
            if current is None:
                raise InvariantViolationError(f"run vanished during reconcile: {run.run_id}")
            if current.execution_ref is not None:
                # Another reconciler already attached — converge on that ref.
                return await self._finish_recovered(current)

            rev = _current_run_revision(self.store, run.run_id, current)
            # Recover existing external execution, else idempotent start.
            existing = await self.port.find_by_run_id(run.run_id)
            if existing is not None:
                ref = existing
                recovered = True
            else:
                ref = await self.port.start(
                    run.run_id, _recovery_workflow_name(current), {},
                    idempotency_key=str(run.run_id),
                )
                recovered = False
            try:
                attached = await self.store.attach_execution_ref(
                    run.run_id, rev, ref,
                    _event(self.actor, "run.reconciled_attach", current, recovered=recovered),
                )
            except StoreConflictError as exc:
                # Lost the revision race; loop and re-read.
                last_exc = exc
                continue
            except ExecutionRefConflictError:
                # A DIFFERENT ref is already attached: divergent logical execution.
                final = await self.store.get_run(run.run_id)
                assert final is not None and final.execution_ref is not None
                if _same_ref(final.execution_ref, ref):
                    return await self._finish_recovered(final)
                raise  # fail closed — never overwrite a divergent ref

            new_rev = _current_run_revision(self.store, run.run_id, attached)
            running = await self.store.transition_run_status(
                run.run_id, RunStatus.RUNNING, new_rev,
                _event(self.actor, "run.running", attached),
            )
            return BridgeResult(run=running, ref=ref, recovered=recovered)

        # Bounded exhaustion — record explicit FAILED + Event, never forge success.
        await self._mark_failed_exhausted(run)
        raise ReconciliationExhaustedError(
            f"reconciliation exhausted for run {run.run_id} after "
            f"{self.max_reconcile_attempts} attempts"
        ) from last_exc

    async def _finish_recovered(self, run: RunRecord) -> BridgeResult:
        assert run.execution_ref is not None
        if run.status == RunStatus.STARTING:
            rev = _current_run_revision(self.store, run.run_id, run)
            run = await self.store.transition_run_status(
                run.run_id, RunStatus.RUNNING, rev,
                _event(self.actor, "run.running", run),
            )
        return BridgeResult(run=run, ref=run.execution_ref, recovered=True)

    async def _mark_failed_exhausted(self, run: RunRecord) -> None:
        current = await self.store.get_run(run.run_id)
        if current is None or current.status != RunStatus.STARTING:
            return
        rev = _current_run_revision(self.store, run.run_id, current)
        try:
            await self.store.transition_run_status(
                run.run_id, RunStatus.FAILED, rev,
                _event(
                    self.actor, "run.reconciliation_failed", current,
                    reason="reconciliation_exhausted",
                ),
            )
        except Exception:
            # Best-effort: if someone else advanced it, the FAILED marker is moot.
            pass

    # -- Cancellation / signal passthroughs (Run-scoped) --------------------
    async def cancel_run(self, run_id: RunId) -> DurableExecutionState:
        run = await self.store.get_run(run_id)
        if run is None or run.execution_ref is None:
            raise InvariantViolationError(f"run {run_id} has no attached execution to cancel")
        result = await self.port.cancel(run.execution_ref)
        return DurableExecutionState.CANCELLED if result.outcome.name in {
            "CANCEL_REQUESTED", "ALREADY_TERMINAL"
        } else DurableExecutionState.RUNNING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _same_ref(a: ExecutionRef, b: ExecutionRef) -> bool:
    return (
        a.backend == b.backend
        and a.execution_id == b.execution_id
        and a.execution_version == b.execution_version
    )


def _recovery_workflow_name(run: RunRecord) -> str:
    # Runs carry no workflow name in the domain; recovery starts the generic
    # workflow keyed on run_id, matching the adapter's registry default.
    return "at_generic_workflow"


def _current_run_revision(store: GoalWorkRunStore, run_id: RunId, run: RunRecord) -> int:
    """Read the current store-owned revision for a Run.

    RunRecord (domain) has no revision field; the store owns it. The in-memory
    store exposes ``run_revision``; the Postgres store tracks it via the module
    map keyed by RunId.
    """
    run_revision = getattr(store, "run_revision", None)
    if callable(run_revision):
        return run_revision(run_id)
    from all_tomorrow.storage.semantic_store import _run_revision
    return _run_revision(run)
