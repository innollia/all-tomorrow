"""Stage 3.3B — Resource Ledger verification (S3-33B-01..04)."""

from __future__ import annotations

import asyncio

import pytest

from all_tomorrow.resource_ledger import CapacityExceededError, LedgerError, ResourceLedger


# S3-33B-01: concurrent reservation cannot exceed the ceiling.
async def test_33b_01_concurrent_ceiling() -> None:
    ledger = ResourceLedger("gpu", capacity=3)

    async def reserve():
        try:
            await ledger.reserve(1)
            return True
        except CapacityExceededError:
            return False

    results = await asyncio.gather(*[reserve() for _ in range(10)])
    assert sum(results) == 3
    snap = await ledger.reconcile()
    assert snap["reserved"] == 3


# S3-33B-02: failed op still counts actual cost.
async def test_33b_02_failed_op_cost_counted() -> None:
    ledger = ResourceLedger("api", capacity=100)
    await ledger.consume_actual(5, failed=True)   # failed but incurred cost
    snap = await ledger.reconcile()
    assert snap["actual_usage"] == 5


async def test_33b_02_unknown_actual_not_zeroed() -> None:
    ledger = ResourceLedger("api", capacity=100)
    with pytest.raises(LedgerError):
        await ledger.consume_actual(None)


# S3-33B-03: expired reservation is released on reconcile.
async def test_33b_03_expired_reservation_released() -> None:
    ledger = ResourceLedger("gpu", capacity=2)
    await ledger.reserve(2, ttl_seconds=0)   # already expired
    snap = await ledger.reconcile()
    assert snap["reserved"] == 0
    # capacity freed → can reserve again
    await ledger.reserve(2)
    assert (await ledger.reconcile())["reserved"] == 2


# unknown capacity → conservative deny.
async def test_33b_unknown_capacity_conservative() -> None:
    ledger = ResourceLedger("mystery", capacity=None)
    with pytest.raises(CapacityExceededError):
        await ledger.reserve(1)


# S3-33B-04: role distinct from lineage budget — this is a shared-resource ledger.
def test_33b_04_distinct_from_lineage_budget() -> None:
    import all_tomorrow.resource_ledger as rl
    import all_tomorrow.researcher.lineage as lb
    # Different modules, different concepts (no shared class).
    assert rl.ResourceLedger is not getattr(lb, "BudgetLedger", None)
