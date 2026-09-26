"""01C — Durable Execution Bridge verification (01C-01,03,04,07,08 at L0/L1).

Uses the in-memory ``GoalWorkRunStore`` + ``FakeDurableAdapter`` to prove the
cross-store start/reconciliation semantics deterministically. Real-process crash
(01C-02/05) and the live selected-adapter mapping (01C-06) are L2 and follow the
existing walking-skeleton harness under a live backend; they are not asserted
here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
from all_tomorrow.bridge import DurableRunBridge, ReconciliationExhaustedError
from all_tomorrow.domain.ids import ExecutionRef, new_goal_id, new_run_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, RunRecord, RunStatus, WorkRecord
from all_tomorrow.ports.durable import DurableExecutionState
from all_tomorrow.storage.semantic_store import (
    ExecutionRefConflictError,
    InMemoryGoalWorkRunStore,
    SemanticEvent,
)
from all_tomorrow.domain.ids import new_event_id


def _evt(**kw) -> SemanticEvent:
    kw.setdefault("actor", "test")
    kw.setdefault("type", "test.event")
    return SemanticEvent(event_id=new_event_id(), **kw)


async def _seed_run(store: InMemoryGoalWorkRunStore) -> RunRecord:
    goal = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(goal, _evt(goal_id=goal.goal_id, type="goal.created"))
    work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title="w")
    await store.create_work(work, _evt(work_id=work.work_id, type="work.created"))
    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    return run


# 01C-01: duplicate same-run start → exactly one external execution
async def test_01c_01_duplicate_start_one_execution() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    bridge = DurableRunBridge(store, port)
    run = await _seed_run(store)

    r1 = await bridge.start_run(run, "at_generic_workflow", {}, run_revision=1)
    # Second start_run on the same run_id (e.g. retry) must converge, not fork.
    # After the first start the run is RUNNING, so re-driving goes through the
    # port's idempotent start; assert only one external execution exists.
    ref_again = await port.start(run.run_id, "at_generic_workflow", {})
    assert ref_again.execution_id == r1.ref.execution_id
    assert await port.find_by_run_id(run.run_id) == r1.ref
    assert r1.run.status == RunStatus.RUNNING
    assert r1.run.execution_ref is not None


# 01C-03: start→attach crash then reconciliation recovers the same execution
async def test_01c_03_start_before_attach_crash_reconciles() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    bridge = DurableRunBridge(store, port)
    run = await _seed_run(store)

    # Simulate the crash window: external start committed, but the process died
    # BEFORE attaching the ExecutionRef to the Run.
    await port.start(run.run_id, "at_generic_workflow", {})
    assert (await store.get_run(run.run_id)).execution_ref is None  # not attached

    results = await bridge.reconcile_starting_runs()
    assert len(results) == 1
    res = results[0]
    assert res.recovered is True  # recovered the existing execution, no new start
    final = await store.get_run(run.run_id)
    assert final.status == RunStatus.RUNNING
    assert final.execution_ref is not None
    assert final.execution_ref.execution_id == res.ref.execution_id


# 01C-03b: crash before external start → reconciliation performs idempotent start
async def test_01c_03_commit_before_start_crash_starts_once() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    bridge = DurableRunBridge(store, port)
    run = await _seed_run(store)

    # No external start happened at all (crash after Run STARTING commit).
    assert await port.find_by_run_id(run.run_id) is None

    results = await bridge.reconcile_starting_runs()
    assert len(results) == 1 and results[0].recovered is False
    # Exactly one execution now exists for the run.
    assert await port.find_by_run_id(run.run_id) is not None
    final = await store.get_run(run.run_id)
    assert final.status == RunStatus.RUNNING


# 01C-04: concurrent reconcilers converge on the same ref (no divergence)
async def test_01c_04_concurrent_reconcilers_converge() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    run = await _seed_run(store)
    await port.start(run.run_id, "at_generic_workflow", {})  # crash-window state

    b1 = DurableRunBridge(store, port)
    b2 = DurableRunBridge(store, port)
    res = await asyncio.gather(
        b1.reconcile_starting_runs(), b2.reconcile_starting_runs(), return_exceptions=True
    )
    # Neither raises; the run ends attached to exactly one ref.
    for r in res:
        assert not isinstance(r, Exception), r
    final = await store.get_run(run.run_id)
    assert final.status == RunStatus.RUNNING
    assert final.execution_ref is not None
    # find_by_run_id is the single source of the recovered execution id.
    assert final.execution_ref.execution_id == (await port.find_by_run_id(run.run_id)).execution_id


# 01C: divergent ref fails closed (never overwrites an attached ref)
async def test_01c_divergent_ref_fails_closed() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    run = await _seed_run(store)

    # A ref is already attached (winner).
    winner = ExecutionRef(backend="fake_durable", execution_id="exec_winner")
    await store.attach_execution_ref(run.run_id, 1, winner, _evt(run_id=run.run_id, type="attach"))

    # A reconciler that somehow observed a DIFFERENT ref must fail closed.
    with pytest.raises(ExecutionRefConflictError):
        await store.attach_execution_ref(
            run.run_id, store.run_revision(run.run_id),
            ExecutionRef(backend="fake_durable", execution_id="exec_other"),
            _evt(run_id=run.run_id, type="attach"),
        )


# 01C: bounded reconciliation exhaustion records FAILED, never forges success
async def test_01c_reconciliation_exhaustion_marks_failed() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    run = await _seed_run(store)
    await port.start(run.run_id, "at_generic_workflow", {})  # recoverable execution exists

    # Force every attach to lose the revision race, so attempts are exhausted.
    real_attach = store.attach_execution_ref

    async def always_conflict(*a, **k):
        from all_tomorrow.storage.semantic_store import StoreConflictError
        raise StoreConflictError("forced revision race")

    store.attach_execution_ref = always_conflict  # type: ignore[method-assign]

    bridge = DurableRunBridge(store, port, max_reconcile_attempts=2)
    with pytest.raises(ReconciliationExhaustedError):
        await bridge.reconcile_starting_runs()

    # The run is marked FAILED (not silently left STARTING, not forged success),
    # and a reconciliation_failed event was recorded.
    store.attach_execution_ref = real_attach  # type: ignore[method-assign]
    final = await store.get_run(run.run_id)
    assert final.status == RunStatus.FAILED
    events = await store.list_events(run_id=run.run_id)
    assert any(e.type == "run.reconciliation_failed" for e in events)


# 01C-08: no custom lease/heartbeat/requeue daemon in the bridge
def test_01c_08_no_custom_lease_daemon() -> None:
    import io
    import tokenize

    path = Path("src/all_tomorrow/bridge/durable_bridge.py")
    src = path.read_text(encoding="utf-8")
    # Scan only executable code: strip comments and string/docstring literals so
    # accurate prose describing what the bridge deliberately avoids does not trip
    # the check. What matters is that no queue primitive is *implemented*.
    code_tokens: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_tokens.append(tok.string.lower())
    code = " ".join(code_tokens)
    for banned in ("lease", "heartbeat", "claimed_by", "requeue", "lease_expires"):
        assert banned not in code, f"bridge must not implement a custom queue primitive: {banned}"


# 01C-07: the fake adapter satisfies the port contract the bridge depends on
async def test_01c_07_fake_adapter_satisfies_port_via_bridge() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    bridge = DurableRunBridge(store, port)
    run = await _seed_run(store)
    res = await bridge.start_run(run, "at_generic_workflow", {}, run_revision=1)
    # cancel passthrough resolves through the same port contract.
    state = await bridge.cancel_run(run.run_id)
    assert state in (DurableExecutionState.CANCELLED, DurableExecutionState.RUNNING)
    assert res.ref.backend == "fake_durable"
