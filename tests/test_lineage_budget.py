"""02D — Lineage, dedup and budget verification (02D-01..07)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from all_tomorrow.researcher.lineage import (
    BudgetConfig,
    BudgetExceededError,
    BudgetLedger,
    DedupConflictError,
    OpenWorkDedupIndex,
    UnknownCostError,
    dedup_fingerprint,
)
from all_tomorrow.domain.ids import utc_now


def _fp(objective="do the thing", evidence=("ev1",), goal="g1"):
    return dedup_fingerprint(
        action_type="create_work", target_goal_id=goal, target_project_id=None,
        objective=objective, evidence_refs=evidence, materializer_schema_version="1",
    )


# 02D-01: concurrent same decision → one Work.
async def test_02d_01_concurrent_same_decision_one_work() -> None:
    idx = OpenWorkDedupIndex()
    fp = _fp()

    async def claim(wid):
        await idx.claim(fp, wid)
        return wid

    results = await asyncio.gather(claim("w1"), claim("w2"), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, DedupConflictError)]
    assert len(ok) == 1 and len(conflicts) == 1


# 02D-02: wording variation with same canonical key dedups.
def test_02d_02_wording_variation_same_fingerprint() -> None:
    a = _fp("Do the Thing!")
    b = _fp("do   the thing")
    assert a == b


# 02D-03: different stable evidence → different fingerprint (separate Work allowed).
def test_02d_03_distinct_evidence_separate() -> None:
    a = _fp(evidence=("ev1",))
    b = _fp(evidence=("ev2",))
    assert a != b
    # evidence order does not matter (sorted)
    assert _fp(evidence=("ev1", "ev2")) == _fp(evidence=("ev2", "ev1"))


# 02D-04: concurrent budget reservation does not exceed the ceiling.
async def test_02d_04_concurrent_budget_no_overcommit() -> None:
    cfg = BudgetConfig("v1", max_created_work=3, max_tokens=1000, max_concurrent_runs=2,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")

    async def reserve():
        try:
            await ledger.reserve_work("L1")
            return True
        except BudgetExceededError:
            return False

    results = await asyncio.gather(*[reserve() for _ in range(10)])
    assert sum(1 for r in results if r) == 3  # exactly the ceiling
    assert ledger.usage("L1").created_work == 3


# 02D-05: unknown cost is not settled as 0 and blocks further spend.
async def test_02d_05_unknown_cost_not_zero() -> None:
    cfg = BudgetConfig("v1", max_created_work=10, max_tokens=1000, max_concurrent_runs=5,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")
    await ledger.consume_tokens("L1", None)  # UNKNOWN
    assert ledger.usage("L1").has_unknown_cost is True
    with pytest.raises(UnknownCostError):
        await ledger.reserve_work("L1")


# 02D-06: deep lineage within budget is allowed.
async def test_02d_06_deep_lineage_within_budget() -> None:
    cfg = BudgetConfig("v1", max_created_work=100, max_tokens=10_000, max_concurrent_runs=1,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")
    for _ in range(50):
        await ledger.reserve_work("L1")
    assert ledger.usage("L1").created_work == 50


# 02D-07: budget exhaustion does not delete existing usage/state.
async def test_02d_07_exhaustion_preserves_state() -> None:
    cfg = BudgetConfig("v1", max_created_work=1, max_tokens=1000, max_concurrent_runs=1,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")
    await ledger.reserve_work("L1")
    with pytest.raises(BudgetExceededError):
        await ledger.reserve_work("L1")
    # prior reservation intact
    assert ledger.usage("L1").created_work == 1


# failed call that incurred cost still consumes; run slot release works.
async def test_02d_run_slot_reserve_release() -> None:
    cfg = BudgetConfig("v1", max_created_work=10, max_tokens=1000, max_concurrent_runs=1,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")
    await ledger.reserve_run_slot("L1")
    with pytest.raises(BudgetExceededError):
        await ledger.reserve_run_slot("L1")
    await ledger.release_run_slot("L1")
    await ledger.reserve_run_slot("L1")  # freed slot reusable
    assert ledger.usage("L1").active_runs == 1
