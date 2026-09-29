"""Feature 3 -- executor stores successful Run output as an ArtifactRef, linked
via CompletionEvidence.artifact_refs so /api/goals/{id} & artifact viewing can
find it."""
from __future__ import annotations

from all_tomorrow.contracts import Worker, WorkerRequest, WorkerResult, WorkerStatus
from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.outcomes import OutcomeStatus, TargetType
from all_tomorrow.domain.state import GoalRecord, WorkRecord
from all_tomorrow.executor import ExecutorLoop
from all_tomorrow.registry import WorkerService
from all_tomorrow.storage.artifact_store import LocalArtifactStore
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


def _evt(**kw):
    kw.setdefault("actor", "t")
    kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


class _FakeAdapter:
    def __init__(self, worker_id: str, result: WorkerResult) -> None:
        self._worker_id = worker_id
        self._result = result

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"code"})

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        return self._result

    async def is_available(self) -> bool:
        return True


async def test_successful_run_output_is_stored_as_artifact(tmp_path) -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="do a thing")
    await store.create_work(w, _evt(work_id=w.work_id))

    adapter = _FakeAdapter("kiro", WorkerResult(
        request_id="r", trace_id="t", status=WorkerStatus.SUCCESS,
        payload={"output": "결과 텍스트입니다"}, duration_ms=3,
    ))
    service = WorkerService()
    service.register_worker(Worker("kiro", adapter.capabilities, status="available"), adapter)

    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    loop = ExecutorLoop(store, service, worker_id="kiro", artifact_store=artifact_store)
    await loop.run_one_cycle()

    events = await store.list_events(work_id=w.work_id)
    succeeded = [e for e in events if e.type == "work.succeeded"]
    assert succeeded

    outcome = await store.get_outcome(w.work_id)
    assert outcome is not None
    assert outcome.status == OutcomeStatus.SATISFIED
    assert outcome.evidence is not None
    assert len(outcome.evidence.artifact_refs) == 1

    stored_files = list((tmp_path / "artifacts").glob("*.dat"))
    assert len(stored_files) == 1
    assert stored_files[0].read_text(encoding="utf-8") == "결과 텍스트입니다"
