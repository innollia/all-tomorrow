"""Stage 2.3C — Question Lifecycle.

Canonical Question state machine: PENDING → ANSWERED / SUPERSEDED / CANCELLED /
EXPIRED. When a replan invalidates a pending question it becomes SUPERSEDED. An
answer emits a durable signal (outbox) exactly once; a late answer to a
non-PENDING question is a safe no-op and never creates a new Run.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError, InvalidStateTransitionError
from all_tomorrow.domain.ids import new_id, utc_now


class QuestionStatus(StrEnum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_TERMINAL = frozenset({
    QuestionStatus.ANSWERED, QuestionStatus.SUPERSEDED,
    QuestionStatus.CANCELLED, QuestionStatus.EXPIRED,
})


class QuestionError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    work_id: str
    prompt: str
    status: QuestionStatus = QuestionStatus.PENDING
    answer_ref: str | None = None
    signal_id: str | None = None
    revision: int = 1
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OutboxSignal:
    signal_id: str
    question_id: str


class QuestionService:
    def __init__(self) -> None:
        self._q: dict[str, Question] = {}
        self._outbox: list[OutboxSignal] = []

    def create(self, question: Question) -> Question:
        # one pending question per work
        if any(q.work_id == question.work_id and q.status == QuestionStatus.PENDING
               for q in self._q.values()):
            raise QuestionError(f"work {question.work_id} already has a PENDING question")
        self._q[question.question_id] = question
        return question

    def answer(self, question_id: str, answer_ref: str) -> tuple[Question, OutboxSignal | None]:
        q = self._q[question_id]
        if q.status != QuestionStatus.PENDING:
            # S2-23C-02: late answer to a non-pending question is a safe no-op.
            return q, None
        signal = OutboxSignal(signal_id=new_id("sig"), question_id=question_id)
        updated = replace(q, status=QuestionStatus.ANSWERED, answer_ref=answer_ref,
                          signal_id=signal.signal_id, revision=q.revision + 1)
        self._q[question_id] = updated
        self._outbox.append(signal)   # S2-23C-01: answer → signal outbox (once)
        return updated, signal

    def supersede_on_replan(self, work_id: str) -> list[str]:
        """A replan invalidates the work's PENDING question → SUPERSEDED."""
        superseded: list[str] = []
        for qid, q in list(self._q.items()):
            if q.work_id == work_id and q.status == QuestionStatus.PENDING:
                self._q[qid] = replace(q, status=QuestionStatus.SUPERSEDED, revision=q.revision + 1)
                superseded.append(qid)
        return superseded

    def cancel(self, question_id: str) -> Question:
        q = self._q[question_id]
        if q.status != QuestionStatus.PENDING:
            raise InvalidStateTransitionError(f"cannot cancel {q.status} question")
        updated = replace(q, status=QuestionStatus.CANCELLED, revision=q.revision + 1)
        self._q[question_id] = updated
        return updated

    def expire_due(self, now: datetime | None = None) -> list[str]:
        now = now or utc_now()
        expired: list[str] = []
        for qid, q in list(self._q.items()):
            if q.status == QuestionStatus.PENDING and q.expires_at and now >= q.expires_at:
                self._q[qid] = replace(q, status=QuestionStatus.EXPIRED, revision=q.revision + 1)
                expired.append(qid)
        return expired

    def outbox(self) -> list[OutboxSignal]:
        return list(self._outbox)

    def get(self, question_id: str) -> Question | None:
        return self._q.get(question_id)
