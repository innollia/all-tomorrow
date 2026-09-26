"""05A — Report Projection and Store.

Durable, bounded, source-backed operational report projection (not an Event
dump). A report is identified by (user_id, logical_period_id, projection_version,
input_watermark) so the same input reproduces the same report. A FINAL report is
immutable: a late source Event for that period produces a NEW revision linked via
``supersedes_report_id`` rather than overwriting the row. Cost/result UNKNOWN is
preserved, never coerced to 0/empty, and no raw secret/content is copied into a
report row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now

PROJECTION_VERSION = "1"


class ReportError(DomainError):
    pass


class FinalReportImmutableError(ReportError):
    pass


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


@dataclass(frozen=True, slots=True)
class ReportSection:
    title: str
    source_refs: tuple[str, ...]
    body_ref: str | None = None      # a ref, never raw content
    unknown: bool = False            # cost/result unavailable → preserved as UNKNOWN


@dataclass(frozen=True, slots=True)
class Report:
    report_id: str
    user_id: str
    logical_period_id: str
    timezone: str
    period_start_utc: datetime
    period_end_utc: datetime
    projection_version: str
    input_watermark: str
    revision: int
    status: ReportStatus
    summary: str
    sections: tuple[ReportSection, ...]
    source_refs: tuple[str, ...]
    supersedes_report_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    finalized_at: datetime | None = None

    def idempotency_key(self) -> str:
        return "\x1f".join([
            self.user_id, self.logical_period_id, self.projection_version, self.input_watermark
        ])


def compute_watermark(source_refs: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(sorted(source_refs)).encode()).hexdigest()[:16]


class ReportStore:
    """In-memory reference store enforcing idempotency + FINAL immutability."""

    def __init__(self) -> None:
        self._by_key: dict[str, Report] = {}
        self._by_id: dict[str, Report] = {}

    def upsert_draft(self, report: Report) -> Report:
        """Idempotent by key: same watermark returns the existing report unchanged."""
        key = report.idempotency_key()
        existing = self._by_key.get(key)
        if existing is not None:
            return existing  # same exact input → same report/ref
        self._by_key[key] = report
        self._by_id[report.report_id] = report
        return report

    def finalize(self, report_id: str) -> Report:
        r = self._by_id[report_id]
        if r.status == ReportStatus.FINAL:
            return r  # idempotent finalize
        final = _replace_status(r, ReportStatus.FINAL, finalized_at=utc_now())
        self._by_id[report_id] = final
        self._by_key[final.idempotency_key()] = final
        return final

    def revise_for_late_event(self, report_id: str, new_source_refs: list[str], new_summary: str) -> Report:
        """A late event for a FINAL period → NEW revision, prior FINAL untouched."""
        prior = self._by_id[report_id]
        if prior.status != ReportStatus.FINAL:
            raise ReportError("only a FINAL report is superseded by a revision")
        merged = tuple(dict.fromkeys([*prior.source_refs, *new_source_refs]))
        revision = Report(
            report_id=new_id("rpt"),
            user_id=prior.user_id, logical_period_id=prior.logical_period_id,
            timezone=prior.timezone, period_start_utc=prior.period_start_utc,
            period_end_utc=prior.period_end_utc, projection_version=prior.projection_version,
            input_watermark=compute_watermark(merged), revision=prior.revision + 1,
            status=ReportStatus.DRAFT, summary=new_summary,
            sections=prior.sections, source_refs=merged,
            supersedes_report_id=prior.report_id,
        )
        self._by_id[revision.report_id] = revision
        self._by_key[revision.idempotency_key()] = revision
        # prior FINAL row is left immutable and still retrievable.
        return revision

    def get(self, report_id: str) -> Report | None:
        return self._by_id.get(report_id)


def _replace_status(r: Report, status: ReportStatus, *, finalized_at: datetime | None) -> Report:
    from dataclasses import replace
    return replace(r, status=status, finalized_at=finalized_at)
