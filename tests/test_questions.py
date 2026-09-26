"""Stage 2.3C — Question lifecycle verification (S2-23C-01,02)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import new_id, utc_now
from all_tomorrow.questions import (
    Question,
    QuestionError,
    QuestionService,
    QuestionStatus,
)


def _q(work="w1", expires=None):
    return Question(question_id=new_id("q"), work_id=work, prompt="Approve?", expires_at=expires)


# S2-23C-01: answer emits exactly one outbox signal.
def test_23c_01_answer_signal_once() -> None:
    s = QuestionService()
    q = s.create(_q())
    updated, sig = s.answer(q.question_id, "ans:yes")
    assert updated.status == QuestionStatus.ANSWERED and sig is not None
    assert len(s.outbox()) == 1
    # answering again (late) is a no-op — no second signal, no new Run.
    again, sig2 = s.answer(q.question_id, "ans:no")
    assert sig2 is None and len(s.outbox()) == 1
    assert again.answer_ref == "ans:yes"


# S2-23C-02: replan supersedes the pending question; a late answer is safe.
def test_23c_02_replan_supersedes() -> None:
    s = QuestionService()
    q = s.create(_q())
    superseded = s.supersede_on_replan("w1")
    assert q.question_id in superseded
    assert s.get(q.question_id).status == QuestionStatus.SUPERSEDED
    # late answer to a superseded question does nothing.
    _, sig = s.answer(q.question_id, "late")
    assert sig is None


def test_23c_one_pending_per_work() -> None:
    s = QuestionService()
    s.create(_q("w1"))
    with pytest.raises(QuestionError):
        s.create(_q("w1"))


def test_23c_cancel_and_expire() -> None:
    s = QuestionService()
    q = s.create(_q("w1"))
    assert s.cancel(q.question_id).status == QuestionStatus.CANCELLED
    # expire path
    q2 = s.create(_q("w2", expires=utc_now() - timedelta(seconds=1)))
    expired = s.expire_due()
    assert q2.question_id in expired
    assert s.get(q2.question_id).status == QuestionStatus.EXPIRED
