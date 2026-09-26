"""01D — Run / Compatibility Linkage verification (01D-01,03,05 at L0/L1; NEED_USER
idempotency + late-answer safety at L1).

Real process-restart (01D-04 L2) and PipelineRuntime regression (01D-02) are
covered by the process-restart harness and the existing pipeline tests
respectively; not re-asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
from all_tomorrow.bridge import (
    DurableRunBridge,
    LateAnswerToTerminalWorkError,
    NeedUserCoordinator,
    assemble_provenance,
)
from all_tomorrow.domain.ids import (
    ExecutionRef,
    new_event_id,
    new_goal_id,
    new_question_id,
    new_run_id,
    new_work_id,
)
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.domain.state import (
    GoalRecord,
    RunRecord,
    RunStatus,
    WorkRecord,
    WorkStatus,
)
from all_tomorrow.ports.durable import SignalOutcome
from all_tomorrow.storage.semantic_store import (
    InMemoryGoalWorkRunStore,
    QuestionRecordSemantic,
    SemanticEvent,
)


def _evt(**kw) -> SemanticEvent:
    kw.setdefault("actor", "test")
    kw.setdefault("type", "test.event")
    return SemanticEvent(event_id=new_event_id(), **kw)


def _evidence() -> CompletionEvidence:
    return CompletionEvidence(criterion_ref="c", evaluator_ref="e", evaluator_version="1")


async def _seed(store: InMemoryGoalWorkRunStore):
    goal = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(goal, _evt(goal_id=goal.goal_id, type="goal.created"))
    work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title="w")
    await store.create_work(work, _evt(work_id=work.work_id, type="work.created"))
    return goal, work


# 01D-01: Work → many Runs → each with its own ExecutionRef
async def test_01d_01_work_many_runs_each_ref() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    bridge = DurableRunBridge(store, port)
    goal, work = await _seed(store)

    # First attempt: create + start + attach ref.
    run1 = RunRecord(run_id=new_run_id(), work_id=work.work_id, attempt_number=1)
    await store.create_run(run1, _evt(run_id=run1.run_id, type="run.created"))
    await bridge.start_run(run1, "at_generic_workflow", {}, run_revision=1)
    # Terminalize it, then a second attempt (new Run, new ref).
    rev = store.run_revision(run1.run_id)
    await store.transition_run_status(run1.run_id, RunStatus.FAILED, rev, _evt(run_id=run1.run_id, type="run.failed"))

    run2 = RunRecord(run_id=new_run_id(), work_id=work.work_id, attempt_number=2)
    await store.create_run(run2, _evt(run_id=run2.run_id, type="run.created"))
    await bridge.start_run(run2, "at_generic_workflow", {}, run_revision=1)

    graph = await assemble_provenance(store, goal.goal_id)
    assert len(graph.work) == 1
    wp = graph.work[0]
    assert len(wp.runs) == 2
    refs = graph.all_execution_refs()
    assert len(refs) == 2
    # Distinct external identities per Run (work_id:run_id keyed).
    assert refs[0].execution_id != refs[1].execution_id


# 01D-05: full provenance graph is linkable (pipeline/agent/span/artifact refs)
async def test_01d_05_full_provenance_graph_linkable() -> None:
    store = InMemoryGoalWorkRunStore()
    goal, work = await _seed(store)
    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    ref = ExecutionRef(backend="dbos", execution_id=f"{work.work_id}:{run.run_id}")
    await store.attach_execution_ref(run.run_id, 1, ref, _evt(run_id=run.run_id, type="run.attach"))

    # Record external provenance refs on events (pipeline/agent/span/tool/artifact).
    await store.transition_run_status(
        run.run_id, RunStatus.RUNNING, store.run_revision(run.run_id),
        SemanticEvent(
            event_id=new_event_id(), actor="worker", type="run.progress",
            work_id=work.work_id, run_id=run.run_id,
            payload={
                "pipeline_execution_id": "pipe-123",
                "agent_invocation_ref": "agent_inv_9",
                "span_ref": "otel:abc",
                "worker_tool_request_id": "tool_req_5",
                "artifact_refs": ["art:1", "art:2"],
            },
            artifact_refs=("art:3",),
        ),
    )

    graph = await assemble_provenance(store, goal.goal_id)
    rp = graph.work[0].runs[0]
    assert rp.execution_ref is not None and rp.execution_ref.execution_id.endswith(str(run.run_id))
    assert rp.pipeline_execution_id == "pipe-123"
    assert "agent_inv_9" in rp.agent_invocation_refs
    assert "otel:abc" in rp.span_refs
    assert "tool_req_5" in rp.worker_tool_request_ids
    assert set(rp.artifact_refs) == {"art:1", "art:2", "art:3"}
    assert graph.is_fully_linked()


# 01D-03: researcher/bridge layer does not depend on PipelineRuntime types
def test_01d_03_no_forced_pipelineruntime_dependency() -> None:
    import io
    import tokenize

    for rel in ("src/all_tomorrow/bridge/durable_bridge.py", "src/all_tomorrow/bridge/provenance.py"):
        src = Path(rel).read_text(encoding="utf-8")
        code_tokens = [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]
        code = " ".join(code_tokens)
        assert "PipelineRuntime" not in code, f"{rel} must not couple to PipelineRuntime in code"
        assert "all_tomorrow.runtime" not in code, f"{rel} must not import the pipeline runtime"


# NEED_USER: answer persists then signals; question_id == signal_id
async def test_01d_need_user_answer_then_signal() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    goal, work = await _seed(store)
    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    ref = await port.start(run.run_id, "at_generic_workflow", {})
    await store.attach_execution_ref(run.run_id, 1, ref, _evt(run_id=run.run_id, type="attach"))

    coord = NeedUserCoordinator(store, port)
    q = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve?", work_id=work.work_id, run_id=run.run_id
    )
    await coord.ask(q)
    res = await coord.answer(q.question_id, q.revision, answer_ref="ans:yes")
    assert res.question.status == "ANSWERED"
    assert res.signal is not None and res.signal.outcome == SignalOutcome.DELIVERED
    assert res.signal.signal_id == str(q.question_id)  # question_id == signal_id


# NEED_USER: duplicate answer/signal is idempotent (no second execution)
async def test_01d_need_user_duplicate_answer_idempotent() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    goal, work = await _seed(store)
    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    ref = await port.start(run.run_id, "at_generic_workflow", {})
    await store.attach_execution_ref(run.run_id, 1, ref, _evt(run_id=run.run_id, type="attach"))

    coord = NeedUserCoordinator(store, port)
    q = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve?", work_id=work.work_id, run_id=run.run_id
    )
    await coord.ask(q)
    first = await coord.answer_idempotent(q.question_id, "ans:yes")
    assert first.question.status == "ANSWERED"
    # Duplicate delivery: signal is ignored, question stays answered, no new run.
    second = await coord.answer_idempotent(q.question_id, "ans:yes")
    assert second.question.status == "ANSWERED"
    assert second.signal is not None
    assert second.signal.outcome == SignalOutcome.DUPLICATE_IGNORED
    assert len(await store.list_runs(work.work_id)) == 1


# NEED_USER: restart does not re-create the same question
async def test_01d_need_user_restart_no_duplicate_question() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    _, work = await _seed(store)
    coord = NeedUserCoordinator(store, port)
    q = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve?", work_id=work.work_id
    )
    await coord.ask(q)
    # A restart tries to ask the "same" question (new id, same work) → refused by
    # the one_pending_question_per_work guard.
    from all_tomorrow.storage.semantic_store import PendingQuestionExistsError
    q_dup = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve?", work_id=work.work_id
    )
    with pytest.raises(PendingQuestionExistsError):
        await coord.ask(q_dup)


# NEED_USER: late answer to terminal Work never implicitly starts execution
async def test_01d_need_user_late_answer_terminal_work_refused() -> None:
    store = InMemoryGoalWorkRunStore()
    port = FakeDurableAdapter()
    _, work = await _seed(store)
    coord = NeedUserCoordinator(store, port)
    q = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve?", work_id=work.work_id
    )
    await coord.ask(q)

    # Terminalize the Work while the question is still pending.
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision, _evt(work_id=work.work_id, type="work.running")
    )
    cur = await store.get_work(work.work_id)
    await store.transition_work_status(
        work.work_id, WorkStatus.SUCCEEDED, cur.revision,
        _evt(work_id=work.work_id, type="work.succeeded"), evidence=_evidence(),
    )

    with pytest.raises(LateAnswerToTerminalWorkError):
        await coord.answer(q.question_id, q.revision, answer_ref="ans:late")
