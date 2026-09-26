"""Stage 3.2C — Lesson Persistence & Evaluation.

A LessonCandidate becomes an AcceptedLesson only with real supporting evidence —
one model self-assessment is not enough. A lesson that conflicts with an existing
accepted lesson is flagged for resolution, never silently merged. Stale lessons
(past their review_at) are surfaced for review and can be retired/superseded.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now

ACCEPTANCE_POLICY_VERSION = "1"
_MIN_EVIDENCE = 2   # need >= 2 independent evidence refs, not a single model statement


class LessonError(DomainError):
    pass


class LessonConflictError(LessonError):
    pass


class LessonStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class Lesson:
    lesson_id: str
    scope: str                     # e.g. "project:x" / "global"
    statement: str
    evidence_refs: tuple[str, ...]
    confidence: float
    status: LessonStatus = LessonStatus.CANDIDATE
    contradicts: tuple[str, ...] = ()      # lesson_ids it conflicts with
    review_at: datetime | None = None
    supersedes: str | None = None
    created_at: datetime = field(default_factory=utc_now)


class KnowledgeStore:
    def __init__(self) -> None:
        self._lessons: dict[str, Lesson] = {}

    def _accepted_in_scope(self, scope: str) -> list[Lesson]:
        return [l for l in self._lessons.values()
                if l.scope == scope and l.status == LessonStatus.ACCEPTED]

    def propose(self, candidate: Lesson) -> Lesson:
        self._lessons[candidate.lesson_id] = replace(candidate, status=LessonStatus.CANDIDATE)
        return self._lessons[candidate.lesson_id]

    def accept(self, lesson_id: str, *, conflicts_with: tuple[str, ...] = ()) -> Lesson:
        """Accept a candidate only with sufficient evidence; conflicts block silent merge."""
        c = self._lessons[lesson_id]
        # S3-32C-01: one model statement is not enough.
        if len(c.evidence_refs) < _MIN_EVIDENCE:
            raise LessonError(
                f"lesson {lesson_id} needs >= {_MIN_EVIDENCE} evidence refs, has {len(c.evidence_refs)}"
            )
        # S3-32C-02: a conflicting lesson is flagged, not silently merged.
        if conflicts_with:
            flagged = replace(c, contradicts=conflicts_with)
            self._lessons[lesson_id] = flagged
            raise LessonConflictError(
                f"lesson {lesson_id} conflicts with {conflicts_with}; resolve before accept"
            )
        accepted = replace(c, status=LessonStatus.ACCEPTED,
                           review_at=utc_now() + timedelta(days=90))
        self._lessons[lesson_id] = accepted
        return accepted

    def due_for_review(self, now: datetime | None = None) -> list[str]:
        now = now or utc_now()
        return [lid for lid, l in self._lessons.items()
                if l.status == LessonStatus.ACCEPTED and l.review_at and now >= l.review_at]

    def retire(self, lesson_id: str) -> Lesson:
        l = self._lessons[lesson_id]
        retired = replace(l, status=LessonStatus.RETIRED)
        self._lessons[lesson_id] = retired
        return retired

    def supersede(self, old_id: str, new_candidate: Lesson) -> Lesson:
        old = self._lessons[old_id]
        self._lessons[old_id] = replace(old, status=LessonStatus.SUPERSEDED)
        new = replace(new_candidate, supersedes=old_id)
        self._lessons[new.lesson_id] = new
        return new

    def get(self, lesson_id: str) -> Lesson | None:
        return self._lessons.get(lesson_id)
