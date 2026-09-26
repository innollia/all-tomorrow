"""05A — Report Projection & Store verification."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from all_tomorrow.domain.ids import new_id
from all_tomorrow.report.store import (
    PROJECTION_VERSION,
    Report,
    ReportSection,
    ReportStatus,
    ReportStore,
    compute_watermark,
)


def _report(source_refs, summary="s", rid=None) -> Report:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    return Report(
        report_id=rid or new_id("rpt"), user_id="u1", logical_period_id="2026-W39",
        timezone="Asia/Seoul", period_start_utc=now, period_end_utc=now,
        projection_version=PROJECTION_VERSION, input_watermark=compute_watermark(source_refs),
        revision=1, status=ReportStatus.DRAFT, summary=summary,
        sections=(ReportSection("Runs", tuple(source_refs)),), source_refs=tuple(source_refs),
    )


def test_idempotent_same_watermark_same_report() -> None:
    s = ReportStore()
    r1 = s.upsert_draft(_report(["ev1", "ev2"]))
    # A second report with the SAME inputs returns the existing one (idempotent).
    r2 = s.upsert_draft(_report(["ev2", "ev1"]))  # order-independent watermark
    assert r1.report_id == r2.report_id


def test_final_immutable_and_late_event_revision() -> None:
    s = ReportStore()
    draft = s.upsert_draft(_report(["ev1"]))
    final = s.finalize(draft.report_id)
    assert final.status == ReportStatus.FINAL
    # Late event → NEW revision superseding the FINAL, prior row untouched.
    rev = s.revise_for_late_event(final.report_id, ["ev2"], "updated")
    assert rev.revision == 2
    assert rev.supersedes_report_id == final.report_id
    assert s.get(final.report_id).status == ReportStatus.FINAL  # prior FINAL immutable
    assert set(rev.source_refs) == {"ev1", "ev2"}


def test_finalize_idempotent() -> None:
    s = ReportStore()
    draft = s.upsert_draft(_report(["ev1"]))
    f1 = s.finalize(draft.report_id)
    f2 = s.finalize(draft.report_id)
    assert f1.finalized_at == f2.finalized_at


def test_unknown_preserved_not_zeroed() -> None:
    s = ReportStore()
    r = _report(["ev1"])
    r = dataclasses.replace(r, sections=(ReportSection("Cost", ("ev1",), unknown=True),))
    stored = s.upsert_draft(r)
    assert stored.sections[0].unknown is True  # UNKNOWN kept, not turned into 0


def test_no_raw_secret_in_report_row() -> None:
    s = ReportStore()
    # source refs are refs, section body is a ref — no raw secret anywhere.
    r = _report(["artifact:1", "run:2"])
    r = dataclasses.replace(r, sections=(ReportSection("S", ("artifact:1",), body_ref="artifact:1"),))
    stored = s.upsert_draft(r)
    blob = repr(dataclasses.asdict(stored))
    assert "sk-" not in blob and "password" not in blob.lower()
