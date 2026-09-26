"""Stage 3.2D — Lesson Reuse & Outcome.

A lesson's track record only moves when it was ACTUALLY reused: an inclusion
provenance links the lesson to the Work/Run that used it, and that Run's Outcome
(success / no-effect / harmful) updates the lesson's confidence and review
schedule. A lesson that was never reused is never counted as a success; a
negative outcome lowers confidence and forces a review.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now
from all_tomorrow.knowledge import Lesson, LessonStatus


class ReuseError(DomainError):
    pass


class ReuseOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    NO_EFFECT = "NO_EFFECT"
    HARMFUL = "HARMFUL"


@dataclass(frozen=True, slots=True)
class ReuseRecord:
    lesson_id: str
    work_id: str
    run_id: str            # the Run that actually consumed the lesson
    outcome_ref: str | None = None   # ref to the Outcome record (S3-32D-02)
    outcome: ReuseOutcome | None = None


def record_reuse(lesson_id: str, work_id: str, run_id: str) -> ReuseRecord:
    """Register that a lesson was actually included in a Run (provenance)."""
    if not run_id:
        raise ReuseError("reuse must reference a real Run")
    return ReuseRecord(lesson_id=lesson_id, work_id=work_id, run_id=run_id)


def apply_outcome(lesson: Lesson, record: ReuseRecord, outcome: ReuseOutcome,
                  outcome_ref: str) -> tuple[Lesson, ReuseRecord]:
    """Update the lesson from a REAL reuse outcome (S3-32D-01,02,03)."""
    if record.lesson_id != lesson.lesson_id:
        raise ReuseError("outcome record does not match lesson")
    if not outcome_ref:
        raise ReuseError("outcome must be linked to an Outcome ref")   # S3-32D-02
    linked = replace(record, outcome=outcome, outcome_ref=outcome_ref)

    if outcome == ReuseOutcome.SUCCESS:
        new_conf = min(1.0, lesson.confidence + 0.1)
        updated = replace(lesson, confidence=new_conf)
    elif outcome == ReuseOutcome.NO_EFFECT:
        updated = lesson   # no credit, no penalty
    else:  # HARMFUL — S3-32D-03: drop confidence and force review now
        new_conf = max(0.0, lesson.confidence - 0.3)
        updated = replace(lesson, confidence=new_conf, review_at=utc_now())
    return updated, linked


def counts_as_success(record: ReuseRecord) -> bool:
    """S3-32D-01: only a lesson actually reused with a SUCCESS outcome counts."""
    return record.outcome == ReuseOutcome.SUCCESS and bool(record.run_id) and bool(record.outcome_ref)
