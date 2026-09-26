"""05B + 05D — composer + trigger/access verification."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from all_tomorrow.domain.ids import new_id
from all_tomorrow.report import (
    AccessDenied,
    Fact,
    Report,
    ReportAccess,
    ReportSection,
    ReportStatus,
    ReportStore,
    SECTION_TITLES,
    TimeModel,
    UnsourcedClaimError,
    compose,
    compute_watermark,
    logical_period_id,
    periods_to_catch_up,
    validate_claims,
)


# 05B: deterministic skeleton has all sections; only source-backed facts populate.
def test_05b_skeleton_all_sections() -> None:
    facts = [Fact("Research Findings", "found X", ("artifact:1",))]
    sections, summary = compose(facts)
    assert [s.title for s in sections] == list(SECTION_TITLES)
    rf = next(s for s in sections if s.title == "Research Findings")
    assert rf.source_refs == ("artifact:1",)


# 05B: unsourced LLM claim → discarded, deterministic fallback summary used.
def test_05b_unsourced_claim_falls_back() -> None:
    facts = [Fact("System Changes", "promoted v2", ("proposal:1",))]
    bad_claim = [Fact("System Changes", "also deleted prod DB", ())]  # no source
    sections, summary = compose(facts, llm_summary="fancy summary", llm_claims=bad_claim)
    assert summary != "fancy summary"  # LLM contribution discarded
    assert "System Changes" in summary


def test_05b_valid_llm_summary_used() -> None:
    facts = [Fact("Research Findings", "x", ("artifact:1",))]
    good = [Fact("Research Findings", "x", ("artifact:1",))]
    sections, summary = compose(facts, llm_summary="nice recap", llm_claims=good)
    assert summary == "nice recap"


def test_05b_validate_claims_rejects_unknown_source() -> None:
    with pytest.raises(UnsourcedClaimError):
        validate_claims([Fact("S", "t", ("unknown:9",))], frozenset({"known:1"}))


# 05D: same local day → same logical period id (idempotent); DST-safe.
def test_05d_logical_period_idempotent_same_local_day() -> None:
    m = TimeModel(timezone="Asia/Seoul")
    a = logical_period_id(m, datetime(2026, 9, 27, 1, 0, tzinfo=UTC))   # 10:00 KST
    b = logical_period_id(m, datetime(2026, 9, 27, 13, 0, tzinfo=UTC))  # 22:00 KST same day
    assert a == b


def test_05d_dst_fold_no_duplicate_day() -> None:
    # US DST fall-back day: two instants map to one local calendar day id.
    m = TimeModel(timezone="America/New_York")
    a = logical_period_id(m, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))  # ~01:30 EDT
    b = logical_period_id(m, datetime(2026, 11, 1, 6, 30, tzinfo=UTC))  # ~01:30 EST (folded)
    assert a == b


# 05D: catch-up bounded by horizon.
def test_05d_catch_up_bounded() -> None:
    m = TimeModel(timezone="Asia/Seoul", catch_up_horizon_days=3)
    # last report was 30 days ago; only the last 3 periods are generated.
    now = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)
    periods = periods_to_catch_up(m, date(2026, 8, 28), now)
    assert len(periods) <= 3


# 05D: access isolation + 401.
def test_05d_access_isolation() -> None:
    store = ReportStore()
    now = datetime(2026, 9, 27, tzinfo=UTC)
    r = Report(report_id=new_id("rpt"), user_id="alice", logical_period_id="2026-W39",
               timezone="Asia/Seoul", period_start_utc=now, period_end_utc=now,
               projection_version="1", input_watermark=compute_watermark(["e1"]), revision=1,
               status=ReportStatus.FINAL, summary="s", sections=(), source_refs=("e1",))
    store.upsert_draft(r)
    access = ReportAccess(store)
    assert access.get(r.report_id, requester_id="alice").user_id == "alice"
    with pytest.raises(AccessDenied):
        access.get(r.report_id, requester_id=None)      # 401
    with pytest.raises(AccessDenied):
        access.get(r.report_id, requester_id="bob")     # not owner
