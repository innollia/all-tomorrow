"""05E — Report & Priority Acceptance (wires 05A-05D, closes §05)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from all_tomorrow.domain.ids import new_id
from all_tomorrow.priority import Commitment, Priority, WorkPriorityInputs, classify_priority, outranks
from all_tomorrow.report import (
    AccessDenied,
    Fact,
    Report,
    ReportAccess,
    ReportStatus,
    ReportStore,
    TimeModel,
    compose,
    compute_watermark,
    logical_period_id,
)


def _seed_report(store, user="u1", refs=("run:1",)) -> Report:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    facts = [Fact("User Work Progress", "shipped kernel", refs)]
    sections, summary = compose(facts)
    r = Report(
        report_id=new_id("rpt"), user_id=user, logical_period_id="2026-09-27|Asia/Seoul|bp1",
        timezone="Asia/Seoul", period_start_utc=now, period_end_utc=now,
        projection_version="1", input_watermark=compute_watermark(list(refs)), revision=1,
        status=ReportStatus.DRAFT, summary=summary, sections=tuple(sections), source_refs=tuple(refs),
    )
    return store.upsert_draft(r)


# End-to-end: generate → finalize → late event revision, owner-only access.
def test_05e_report_lifecycle_and_access() -> None:
    store = ReportStore()
    r = _seed_report(store)
    final = store.finalize(r.report_id)
    assert final.status == ReportStatus.FINAL
    rev = store.revise_for_late_event(final.report_id, ["run:2"], "updated")
    assert rev.revision == 2 and store.get(final.report_id).status == ReportStatus.FINAL

    access = ReportAccess(store)
    assert access.get(r.report_id, requester_id="u1") is not None
    with pytest.raises(AccessDenied):
        access.get(r.report_id, requester_id="intruder")


# Report generation failure isolation: composer fallback yields a durable summary.
def test_05e_generation_failure_isolated() -> None:
    facts = [Fact("System Changes", "promoted v2", ("proposal:1",))]
    # A broken LLM claim is discarded; a deterministic FINAL summary is still produced.
    sections, summary = compose(facts, llm_summary="hallucinated", llm_claims=[Fact("System Changes", "deleted everything", ())])
    assert summary and summary != "hallucinated"


# Priority: a hard user commitment dispatches before autonomous research.
def test_05e_user_commitment_outranks_research() -> None:
    user = classify_priority(WorkPriorityInputs(Commitment.HARD, urgent_safety=True))
    research = classify_priority(WorkPriorityInputs(Commitment.AUTONOMOUS))
    assert user == Priority.P0 and research == Priority.P5
    assert outranks(user, research)


# Time model: same local day is one logical period (idempotent trigger identity).
def test_05e_logical_period_idempotent() -> None:
    m = TimeModel(timezone="Asia/Seoul")
    a = logical_period_id(m, datetime(2026, 9, 27, 2, 0, tzinfo=UTC))
    b = logical_period_id(m, datetime(2026, 9, 27, 12, 0, tzinfo=UTC))
    assert a == b


# Idempotent report projection: same watermark → same report id.
def test_05e_idempotent_projection() -> None:
    store = ReportStore()
    r1 = _seed_report(store, refs=("run:1", "run:2"))
    r2 = _seed_report(store, refs=("run:2", "run:1"))
    assert r1.report_id == r2.report_id
