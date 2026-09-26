"""Stage 3.2C — Lesson persistence & evaluation verification (S3-32C-01..03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from all_tomorrow.domain.ids import new_id
from all_tomorrow.knowledge import (
    KnowledgeStore,
    Lesson,
    LessonConflictError,
    LessonError,
    LessonStatus,
)


def _cand(evidence=("e1", "e2"), scope="global", lid=None):
    return Lesson(lesson_id=lid or new_id("les"), scope=scope, statement="prefer X",
                  evidence_refs=tuple(evidence), confidence=0.8)


# S3-32C-01: one model statement (single/zero evidence) cannot be accepted.
def test_32c_01_single_statement_not_accepted() -> None:
    s = KnowledgeStore()
    c = s.propose(_cand(evidence=("only-one",)))
    with pytest.raises(LessonError):
        s.accept(c.lesson_id)


def test_32c_evidence_backed_accept() -> None:
    s = KnowledgeStore()
    c = s.propose(_cand(evidence=("e1", "e2")))
    accepted = s.accept(c.lesson_id)
    assert accepted.status == LessonStatus.ACCEPTED
    assert accepted.review_at is not None


# S3-32C-02: conflicting lesson is flagged, not silently merged.
def test_32c_02_conflict_flagged_not_merged() -> None:
    s = KnowledgeStore()
    c = s.propose(_cand())
    with pytest.raises(LessonConflictError):
        s.accept(c.lesson_id, conflicts_with=("other-lesson",))
    # it is flagged, still a candidate (not accepted, not merged)
    assert s.get(c.lesson_id).status == LessonStatus.CANDIDATE
    assert "other-lesson" in s.get(c.lesson_id).contradicts


# S3-32C-03: stale lesson surfaces for review and can be retired.
def test_32c_03_stale_review_and_retire() -> None:
    s = KnowledgeStore()
    c = s.propose(_cand())
    accepted = s.accept(c.lesson_id)
    # force it stale
    from dataclasses import replace
    s._lessons[c.lesson_id] = replace(accepted, review_at=datetime(2000, 1, 1, tzinfo=UTC))
    assert c.lesson_id in s.due_for_review()
    retired = s.retire(c.lesson_id)
    assert retired.status == LessonStatus.RETIRED


def test_32c_supersede() -> None:
    s = KnowledgeStore()
    c = s.propose(_cand())
    s.accept(c.lesson_id)
    new = s.supersede(c.lesson_id, _cand())
    assert new.supersedes == c.lesson_id
    assert s.get(c.lesson_id).status == LessonStatus.SUPERSEDED
