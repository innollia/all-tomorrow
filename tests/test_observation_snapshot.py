"""02A — Observation Snapshot verification (02A-01,02,03,06 + cursor CAS)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id, utc_now
from all_tomorrow.domain.state import GoalRecord, WorkRecord
from all_tomorrow.researcher import (
    CursorConflictError,
    EventCursor,
    ObservationBuilder,
)
from all_tomorrow.storage.semantic_store import (
    InMemoryGoalWorkRunStore,
    SemanticEvent,
)


def _evt(t, eid="", **kw) -> SemanticEvent:
    kw.setdefault("actor", "test")
    kw.setdefault("type", "test.event")
    return SemanticEvent(event_id=eid or new_event_id(), occurred_at=t, **kw)


async def _seed_goal(store) -> GoalRecord:
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(utc_now(), goal_id=g.goal_id, type="goal.created"))
    return g


# 02A-01: same-timestamp events are ordered by event_id, none dropped.
async def test_02a_01_same_timestamp_no_drop() -> None:
    store = InMemoryGoalWorkRunStore()
    g = await _seed_goal(store)
    t = utc_now()
    # three events at the exact same timestamp, ids sortable
    for eid in ("evt_a", "evt_b", "evt_c"):
        store._events.append(_evt(t, eid, goal_id=g.goal_id, type=f"e.{eid}"))
    b = ObservationBuilder(store)
    snap = await b.build("researcher", "u1")
    # all three same-timestamp events appear, in event_id order
    got = [e for e in snap.event_refs if e in ("evt_a", "evt_b", "evt_c")]
    assert got == ["evt_a", "evt_b", "evt_c"]


# 02A-02: terminal history is bounded by recent_limit.
async def test_02a_02_recent_runs_bounded() -> None:
    from all_tomorrow.domain.state import RunRecord, RunStatus
    store = InMemoryGoalWorkRunStore()
    g = await _seed_goal(store)
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(utc_now(), work_id=w.work_id, type="work.created"))
    # Only one active run allowed at a time; terminalize before creating the next.
    for i in range(5):
        r = RunRecord(run_id=__import__("all_tomorrow.domain.ids", fromlist=["new_run_id"]).new_run_id(),
                      work_id=w.work_id, attempt_number=i + 1)
        await store.create_run(r, _evt(utc_now(), run_id=r.run_id, type="run.created"))
        rev = store.run_revision(r.run_id)
        await store.transition_run_status(r.run_id, RunStatus.FAILED, rev, _evt(utc_now(), run_id=r.run_id, type="run.failed"))
    b = ObservationBuilder(store, recent_limit=3)
    snap = await b.build("researcher", "u1")
    assert len(snap.recent_run_refs) <= 3


# 02A-03: same lower cursor reproduces the same range.
async def test_02a_03_reproducible_range() -> None:
    store = InMemoryGoalWorkRunStore()
    g = await _seed_goal(store)
    for i in range(3):
        store._events.append(_evt(utc_now() + timedelta(seconds=i), f"e{i}", goal_id=g.goal_id, type="e"))
    b = ObservationBuilder(store)
    snap1 = await b.build("researcher", "u1")
    snap2 = await b.build("researcher", "u1")  # cursor not advanced → same range
    assert snap1.event_refs == snap2.event_refs


# cursor CAS: advancing with a stale expected revision conflicts.
async def test_02a_cursor_cas_conflict() -> None:
    store = InMemoryGoalWorkRunStore()
    b = ObservationBuilder(store)
    b.advance_cursor("researcher", "u1", EventCursor(utc_now(), "e1", 1), expected_revision=0)
    with pytest.raises(CursorConflictError):
        b.advance_cursor("researcher", "u1", EventCursor(utc_now(), "e2", 2), expected_revision=0)


# 02A-06: no raw secret/content in snapshot metadata.
async def test_02a_06_no_secret_in_snapshot() -> None:
    store = InMemoryGoalWorkRunStore()
    g = await _seed_goal(store)
    # An event whose payload carries a would-be secret; snapshot must keep only the ref.
    store._events.append(_evt(utc_now(), "sec1", goal_id=g.goal_id, type="e",
                              payload={"api_key": "sk-super-secret-value"}))
    b = ObservationBuilder(store)
    snap = await b.build("researcher", "u1")
    import dataclasses
    blob = repr(dataclasses.asdict(snap))
    assert "sk-super-secret-value" not in blob
    assert "sec1" in snap.event_refs  # only the ref is carried
