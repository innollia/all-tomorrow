"""Stage 3.2D — Lesson reuse & outcome verification (S3-32D-01..03)."""

from __future__ import annotations

import pytest

from all_tomorrow.domain.ids import new_id
from all_tomorrow.knowledge import Lesson, LessonStatus
from all_tomorrow.knowledge_outcomes import (
    ReuseError,
    ReuseOutcome,
    ReuseRecord,
    apply_outcome,
    counts_as_success,
    record_reuse,
)


def _lesson(conf=0.5):
    return Lesson(lesson_id="les1", scope="global", statement="do X",
                  evidence_refs=("e1", "e2"), confidence=conf, status=LessonStatus.ACCEPTED)


# S3-32D-01: a lesson with no real reuse is not counted as success.
def test_32d_01_no_reuse_not_success() -> None:
    rec = ReuseRecord(lesson_id="les1", work_id="w1", run_id="")  # no run
    assert counts_as_success(rec) is False
    with pytest.raises(ReuseError):
        record_reuse("les1", "w1", "")


# S3-32D-02: outcome must be linked to an Outcome ref.
def test_32d_02_outcome_ref_required() -> None:
    rec = record_reuse("les1", "w1", "run1")
    with pytest.raises(ReuseError):
        apply_outcome(_lesson(), rec, ReuseOutcome.SUCCESS, outcome_ref="")
    updated, linked = apply_outcome(_lesson(), rec, ReuseOutcome.SUCCESS, outcome_ref="oc1")
    assert linked.outcome_ref == "oc1" and linked.run_id == "run1"
    assert counts_as_success(linked) is True


# S3-32D-03: harmful outcome lowers confidence and forces review.
def test_32d_03_negative_lowers_confidence() -> None:
    rec = record_reuse("les1", "w1", "run1")
    updated, linked = apply_outcome(_lesson(conf=0.5), rec, ReuseOutcome.HARMFUL, outcome_ref="oc2")
    assert updated.confidence < 0.5
    assert updated.review_at is not None
    assert counts_as_success(linked) is False


def test_32d_success_raises_confidence() -> None:
    rec = record_reuse("les1", "w1", "run1")
    updated, _ = apply_outcome(_lesson(conf=0.5), rec, ReuseOutcome.SUCCESS, outcome_ref="oc3")
    assert updated.confidence > 0.5


def test_32d_no_effect_neutral() -> None:
    rec = record_reuse("les1", "w1", "run1")
    updated, linked = apply_outcome(_lesson(conf=0.5), rec, ReuseOutcome.NO_EFFECT, outcome_ref="oc4")
    assert updated.confidence == 0.5
    assert counts_as_success(linked) is False
