"""Stage 3.2A — Trigger store & scheduler verification (S3-32A-01..04)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from all_tomorrow.triggers import (
    TriggerError,
    TriggerKind,
    TriggerRecord,
    TriggerScheduler,
    logical_fire_key,
)


def _t(tid="t1", tz="Asia/Seoul", horizon=7):
    return TriggerRecord(trigger_id=tid, user_id="u1", kind=TriggerKind.RECURRING_DAILY,
                         timezone=tz, catch_up_horizon_days=horizon)


# S3-32A-01: duplicate fire (same logical period) → one Work.
def test_32a_01_duplicate_fire_one_work() -> None:
    s = TriggerScheduler(); s.register(_t())
    w1 = s.fire("t1", datetime(2026, 9, 27, 1, 0, tzinfo=UTC))   # 10:00 KST
    w2 = s.fire("t1", datetime(2026, 9, 27, 13, 0, tzinfo=UTC))  # 22:00 KST same day
    assert w1 is not None and w2 is None                        # second is a duplicate


# S3-32A-02: a revision change makes a new logical schedule (old-rev key differs).
def test_32a_02_revision_changes_fire_key() -> None:
    s = TriggerScheduler(); s.register(_t())
    t = s._triggers["t1"]
    k1 = logical_fire_key(t, datetime(2026, 9, 27, 1, 0, tzinfo=UTC))
    t2 = s.update_revision("t1")
    k2 = logical_fire_key(t2, datetime(2026, 9, 27, 1, 0, tzinfo=UTC))
    assert k1 != k2 and k1.endswith("r1") and k2.endswith("r2")


# S3-32A-03: DST fold does not duplicate a logical period.
def test_32a_03_dst_fold_no_duplicate() -> None:
    s = TriggerScheduler(); s.register(_t(tz="America/New_York"))
    w1 = s.fire("t1", datetime(2026, 11, 1, 5, 30, tzinfo=UTC))   # 01:30 EDT
    w2 = s.fire("t1", datetime(2026, 11, 1, 6, 30, tzinfo=UTC))   # 01:30 EST (folded)
    assert w1 is not None and w2 is None


# S3-32A-04: catch-up bounded by horizon.
def test_32a_04_bounded_catch_up() -> None:
    s = TriggerScheduler(); s.register(_t(horizon=3))
    keys = s.catch_up_keys("t1", date(2026, 8, 1), datetime(2026, 9, 27, 15, 0, tzinfo=UTC))
    assert len(keys) <= 3


def test_32a_cancel_disables() -> None:
    s = TriggerScheduler(); s.register(_t())
    s.cancel("t1")
    with pytest.raises(TriggerError):
        s.fire("t1", datetime(2026, 9, 27, 1, 0, tzinfo=UTC))
