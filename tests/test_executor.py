"""Feature 1/2 -- Executor loop: claim, run, question hand-off, resume.

Uses a fake WorkerAdapter injected into a real WorkerService, so no real CLI
process is spawned. Covers:
  - PENDING -> RUNNING -> SUCCEEDED on a successful worker result.
  - a failing worker (or no worker) -> FAILED with a recorded reason, never a
    fake success.
  - two concurrent claim_pending_work calls never claim the same Work
    (single-active-run invariant preserved).
  - a worker result carrying need_question -> Question created, Work WAITING.
  - answering that question resumes the Work with a NEW Run (no double-run for
    the same answer; a late/duplicate resume attempt on a non-WAITING Work is a
    safe no-op).
"""

from __future__ import annotations

import asyncio

import pytest

from all_tomorrow.contracts import Worker, WorkerRequest, WorkerResult, WorkerStatus
from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, WorkRecord, WorkStatus
from all_tomorrow.executor import ExecutorLoop, resume_answered_work
from all_tomorrow.registry import WorkerService
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


def _evt(**kw):
    kw.setdefault("actor", "t")
    kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


class _FakeAdapter:
    def __init__(self, worker_id: str, *, result: WorkerResult | None = None,
                 raises: Exception | None = None, available: bool = True) -> None:
        self._worker_id = worker_id
        self._result = result
        self._raises = raises
        self._available = available

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"code"})

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result

    async def is_available(self) -> bool:
        return self._available


def _service_with(adapter: _FakeAdapter) -> WorkerService:
    service = WorkerService()
    service.register_worker(Worker(adapter.worker_id, adapter.capabilities, status="available"), adapter)
    return service


async def _goal_and_work(store, *, title: str = "do a thing") -> tuple[GoalRecord, WorkRecord]:
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title=title)
    await store.create_work(w, _evt(work_id=w.work_id))
    return g, w


async def test_pending_to_succeeded_on_worker_success() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    adapter = _FakeAdapter("kiro", result=WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.SUCCESS, payload={"ok": True}, duration_ms=5,
    ))
    loop = ExecutorLoop(store, _service_with(adapter), worker_id="kiro")
    results = await loop.run_one_cycle()
    assert len(results) == 1 and results[0].outcome == "succeeded"
    done = await store.get_work(w.work_id)
    assert done.status == WorkStatus.SUCCEEDED


async def test_worker_failure_marks_work_failed_not_success() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    adapter = _FakeAdapter("kiro", result=WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.FAILED, error="boom", duration_ms=1,
    ))
    loop = ExecutorLoop(store, _service_with(adapter), worker_id="kiro")
    results = await loop.run_one_cycle()
    assert results[0].outcome == "failed"
    assert "boom" in (results[0].detail or "")
    done = await store.get_work(w.work_id)
    assert done.status == WorkStatus.FAILED


async def test_no_worker_configured_marks_work_failed() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    empty_service = WorkerService()  # no adapters registered at all
    loop = ExecutorLoop(store, empty_service, worker_id="kiro")
    results = await loop.run_one_cycle()
    assert results[0].outcome == "failed"
    assert "no worker" in (results[0].detail or "").lower()
    done = await store.get_work(w.work_id)
    assert done.status == WorkStatus.FAILED


async def test_two_concurrent_claims_never_take_the_same_work() -> None:
    store = InMemoryGoalWorkRunStore()
    works = [ (await _goal_and_work(store, title=f"t{i}"))[1] for i in range(4) ]
    adapter = _FakeAdapter("kiro", result=WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.SUCCESS, payload={}, duration_ms=1,
    ))
    service = _service_with(adapter)
    loop_a = ExecutorLoop(store, service, worker_id="kiro")
    loop_b = ExecutorLoop(store, service, worker_id="kiro")
    results_a, results_b = await asyncio.gather(
        loop_a.run_one_cycle(limit=4), loop_b.run_one_cycle(limit=4)
    )
    claimed_ids = [r.work_id for r in results_a] + [r.work_id for r in results_b]
    assert sorted(claimed_ids) == sorted(str(w.work_id) for w in works)
    assert len(claimed_ids) == len(set(claimed_ids))  # no Work claimed twice


async def test_need_question_moves_work_to_waiting_and_creates_question() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    adapter = _FakeAdapter("kiro", result=WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.SUCCESS,
        payload={"need_question": "어떤 브랜치에 배포할까요?"}, duration_ms=1,
    ))
    loop = ExecutorLoop(store, _service_with(adapter), worker_id="kiro")
    results = await loop.run_one_cycle()
    assert results[0].outcome == "waiting"
    waiting = await store.get_work(w.work_id)
    assert waiting.status == WorkStatus.WAITING
    questions = await store.list_questions(w.work_id)
    assert len(questions) == 1 and questions[0].status == "PENDING"


async def test_answering_question_resumes_work_with_new_run() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    adapter = _FakeAdapter("kiro", result=WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.SUCCESS,
        payload={"need_question": "계속할까요?"}, duration_ms=1,
    ))
    loop = ExecutorLoop(store, _service_with(adapter), worker_id="kiro")
    await loop.run_one_cycle()
    question = (await store.list_questions(w.work_id))[0]

    await store.answer_question(question.question_id, question.revision, "네", "sig1")
    resumed = await resume_answered_work(store, w.work_id)
    assert resumed is True
    work_after = await store.get_work(w.work_id)
    assert work_after.status == WorkStatus.RUNNING
    runs = await store.list_runs(w.work_id)
    assert len(runs) == 2  # original waiting Run + the new resumed Run


async def test_late_answer_or_already_advanced_work_is_a_safe_noop() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_and_work(store)
    # Work never claimed -- still PENDING, not WAITING.
    resumed = await resume_answered_work(store, w.work_id)
    assert resumed is False
    still = await store.get_work(w.work_id)
    assert still.status == WorkStatus.PENDING
    assert len(await store.list_runs(w.work_id)) == 0
