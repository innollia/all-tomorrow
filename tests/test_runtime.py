from dataclasses import dataclass
from typing import Any

import pytest

from all_tomorrow.contracts import (
    ContractError,
    ExecutionContext,
    NodeResult,
    NodeStatus,
    PipelineSpec,
    PipelineStep,
    RequestEnvelope,
    UserQuestion,
)
from all_tomorrow.pipeline import PipelineRuntime, RunResult, RunStatus, load_pipeline


@dataclass
class RecordingNode:
    name: str
    calls: list[str]

    async def run(self, context, config, inputs) -> NodeResult:
        self.calls.append(self.name)
        return NodeResult(status=NodeStatus.SUCCESS, output=inputs or self.name)


class ConfirmNode:
    async def run(self, context, config, inputs) -> NodeResult:
        answer = context.variables.get("user_answers", {}).get("confirm_project")
        if answer is None:
            return NodeResult(
                status=NodeStatus.NEED_USER,
                user_question=UserQuestion(
                    question="Use this project?",
                    reason="Mutation target must be confirmed",
                    blocked_step="confirm_project",
                    required_fields=("confirmed",),
                ),
            )
        return NodeResult(status=NodeStatus.SUCCESS, output=answer)


def context(candidate: str | None = "project:eve") -> ExecutionContext:
    return ExecutionContext(
        request=RequestEnvelope(message="Fix it", source="test", candidate_project_id=candidate),
        user_ref="user:test",
    )


@pytest.mark.asyncio
async def test_yaml_order_changes_execution_without_code_change(tmp_path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime()
    runtime.register("node.a", RecordingNode("a", calls))
    runtime.register("node.b", RecordingNode("b", calls))

    first = PipelineSpec(
        pipeline_id="order",
        version=1,
        status="active",
        steps=(PipelineStep(id="a", type="node.a"), PipelineStep(id="b", type="node.b")),
    )
    second = PipelineSpec(
        pipeline_id="order",
        version=2,
        status="active",
        parent_version=1,
        steps=(PipelineStep(id="b", type="node.b"), PipelineStep(id="a", type="node.a")),
    )

    assert (await runtime.start(first, context())).status is RunStatus.SUCCEEDED
    assert (await runtime.start(second, context())).status is RunStatus.SUCCEEDED
    assert calls == ["a", "b", "b", "a"]


@pytest.mark.asyncio
async def test_need_user_resumes_same_run_step_and_version() -> None:
    runtime = PipelineRuntime()
    runtime.register("demo.resolve_project", RecordingNode("resolve", []))
    runtime.register("demo.confirm_project", ConfirmNode())
    runtime.register("demo.finish", RecordingNode("finish", []))
    spec = load_pipeline("pipelines/demo.yaml")

    waiting = await runtime.start(spec, context())
    assert waiting.status is RunStatus.NEED_USER
    assert waiting.pipeline_version == 1
    assert waiting.question is not None
    assert waiting.question.blocked_step == "confirm_project"

    resumed = await runtime.resume(waiting.question.resume_token, {"confirmed": True})
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.run_id == waiting.run_id
    assert resumed.trace_id == waiting.trace_id
    assert resumed.pipeline_version == waiting.pipeline_version
    assert resumed.outputs["finish"]["confirmation"] is True

    event_types = [event.type for event in runtime.event_sink.events]
    assert "run.needs_user" in event_types
    assert "run.user_answered" in event_types
    assert event_types[-1] == "run.succeeded"


@pytest.mark.asyncio
async def test_resume_token_is_single_use_and_required_fields_are_enforced() -> None:
    runtime = PipelineRuntime()
    runtime.register("ask", ConfirmNode())
    spec = PipelineSpec(
        pipeline_id="question",
        version=1,
        status="active",
        steps=(PipelineStep(id="confirm_project", type="ask"),),
    )
    waiting = await runtime.start(spec, context())
    token = waiting.question.resume_token

    with pytest.raises(ContractError, match="missing required"):
        await runtime.resume(token, {})

    assert (await runtime.resume(token, {"confirmed": True})).status is RunStatus.SUCCEEDED
    with pytest.raises(ContractError, match="already-used"):
        await runtime.resume(token, {"confirmed": True})


@pytest.mark.asyncio
async def test_unresolved_reference_fails_closed() -> None:
    runtime = PipelineRuntime()
    runtime.register("record", RecordingNode("record", []))
    spec = PipelineSpec(
        pipeline_id="bad-ref",
        version=1,
        status="active",
        steps=(PipelineStep(id="x", type="record", inputs={"value": "${missing.output}"}),),
    )
    result = await runtime.start(spec, context())
    assert result.status is RunStatus.FAILED
    assert "unresolved pipeline reference" in result.error


@pytest.mark.asyncio
async def test_trace_and_pipeline_version_are_on_every_event() -> None:
    runtime = PipelineRuntime()
    runtime.register("record", RecordingNode("record", []))
    spec = PipelineSpec(
        pipeline_id="trace",
        version=7,
        status="active",
        steps=(PipelineStep(id="x", type="record"),),
    )
    result = await runtime.start(spec, context())
    assert result.pipeline_version == 7
    assert {event.trace_id for event in runtime.event_sink.events} == {result.trace_id}
    assert {event.run_id for event in runtime.event_sink.events} == {result.run_id}


@pytest.mark.asyncio
async def test_runtime_suspends_in_a_and_resumes_in_b_with_same_store() -> None:
    import json
    from all_tomorrow.storage import InMemoryRunStateStore, hash_resume_token
    from all_tomorrow.pipeline import InMemoryEventSink

    store = InMemoryRunStateStore()
    sink = InMemoryEventSink()

    runtime_a = PipelineRuntime(store=store, event_sink=sink)
    runtime_a.register("demo.resolve_project", RecordingNode("resolve", []))
    runtime_a.register("demo.confirm_project", ConfirmNode())
    runtime_a.register("demo.finish", RecordingNode("finish", []))
    spec = load_pipeline("pipelines/demo.yaml")

    waiting = await runtime_a.start(spec, context())
    assert waiting.status is RunStatus.NEED_USER
    assert waiting.question is not None
    assert waiting.question.blocked_step == "confirm_project"
    token = waiting.question.resume_token
    assert token is not None

    # Invariant: durable store state contains NO plaintext resume tokens
    run_snapshot = store._runs[waiting.run_id]
    assert "resume_token" not in run_snapshot["question"] or run_snapshot["question"]["resume_token"] is None
    assert token not in json.dumps(run_snapshot)

    token_hash = hash_resume_token(token)
    assert token_hash in store._questions
    assert token not in json.dumps(store._questions[token_hash])
    assert store._questions[token_hash]["status"] == "pending"

    # Runtime A is discarded; runtime B has NO prior in-memory maps of runtime A
    del runtime_a

    runtime_b = PipelineRuntime(store=store, event_sink=sink)
    runtime_b.register("demo.resolve_project", RecordingNode("resolve", []))
    runtime_b.register("demo.confirm_project", ConfirmNode())
    runtime_b.register("demo.finish", RecordingNode("finish", []))

    resumed = await runtime_b.resume(token, {"confirmed": True})
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.run_id == waiting.run_id
    assert resumed.trace_id == waiting.trace_id
    assert resumed.pipeline_version == waiting.pipeline_version
    assert resumed.outputs["finish"]["confirmation"] is True
    assert resumed.outputs["finish"]["project"] == {"candidate": "project:eve"}
    assert resumed.question is None

    # Invariant: event continuity across runtime instances
    event_types = [event.type for event in sink.events]
    assert "run.started" in event_types
    assert "run.needs_user" in event_types
    assert "run.user_answered" in event_types
    assert "run.succeeded" in event_types
    assert {event.trace_id for event in sink.events} == {waiting.trace_id}
    assert {event.run_id for event in sink.events} == {waiting.run_id}

    # Invariant: single use — cannot resume with same token again
    with pytest.raises(ContractError, match="invalid or already-used resume token"):
        await runtime_b.resume(token, {"confirmed": True})


@pytest.mark.asyncio
async def test_duplicate_and_concurrent_resume_prevention() -> None:
    import asyncio
    from all_tomorrow.storage import InMemoryRunStateStore, RunConflictError

    store = InMemoryRunStateStore()
    runtime_a = PipelineRuntime(store=store)
    runtime_a.register("ask", ConfirmNode())
    runtime_a.register("finish", RecordingNode("finish", []))
    spec = PipelineSpec(
        pipeline_id="dup_test",
        version=1,
        status="active",
        steps=(
            PipelineStep(id="confirm_project", type="ask", next_step="finish"),
            PipelineStep(id="finish", type="finish"),
        ),
    )

    waiting = await runtime_a.start(spec, context())
    token = waiting.question.resume_token

    # Test optimistic conflict: direct stale revision update is rejected
    run_record = await store.get_run(waiting.run_id)
    assert run_record is not None
    with pytest.raises(RunConflictError, match="revision conflict"):
        await store.update_run(run_record, expected_revision=run_record.revision - 1)

    # Test concurrent resumes on fresh runtime instances
    runtime_b1 = PipelineRuntime(store=store)
    runtime_b1.register("ask", ConfirmNode())
    runtime_b1.register("finish", RecordingNode("finish", []))

    runtime_b2 = PipelineRuntime(store=store)
    runtime_b2.register("ask", ConfirmNode())
    runtime_b2.register("finish", RecordingNode("finish", []))

    results = await asyncio.gather(
        runtime_b1.resume(token, {"confirmed": True}),
        runtime_b2.resume(token, {"confirmed": True}),
        return_exceptions=True,
    )

    succeeded = [r for r in results if isinstance(r, RunResult) and r.status is RunStatus.SUCCEEDED]
    failed = [r for r in results if isinstance(r, Exception)]

    assert len(succeeded) == 1, f"Expected exactly 1 success, got {len(succeeded)}"
    assert len(failed) == 1, f"Expected exactly 1 failure, got {len(failed)}"
    assert isinstance(failed[0], ContractError)


@pytest.mark.asyncio
async def test_resume_fails_closed_on_invalid_tokens_and_mismatched_state() -> None:
    from all_tomorrow.storage import InMemoryRunStateStore

    store = InMemoryRunStateStore()
    runtime = PipelineRuntime(store=store)
    runtime.register("ask", ConfirmNode())
    spec = PipelineSpec(
        pipeline_id="fail_closed_test",
        version=1,
        status="active",
        steps=(PipelineStep(id="confirm_project", type="ask"),),
    )

    waiting = await runtime.start(spec, context())
    token = waiting.question.resume_token

    # Fabricated token fails closed
    with pytest.raises(ContractError, match="invalid or already-used resume token"):
        await runtime.resume("resume_fabricated_token_value", {"confirmed": True})

    # Empty token fails closed
    with pytest.raises(ContractError, match="invalid or already-used resume token"):
        await runtime.resume("", {"confirmed": True})

    # Missing required answer fields fails closed and does NOT consume token
    with pytest.raises(ContractError, match="missing required answer fields: confirmed"):
        await runtime.resume(token, {})

    # Blocked step mismatch fails closed
    store_run = await store.get_run(waiting.run_id)
    assert store_run is not None
    store_run.current_step_id = "other_step"
    await store.update_run(store_run, expected_revision=store_run.revision)

    with pytest.raises(ContractError, match="resume step mismatch"):
        await runtime.resume(token, {"confirmed": True})

    # Restore step and cancel run -> cancelled run fails closed
    store_run.current_step_id = "confirm_project"
    await store.update_run(store_run, expected_revision=store_run.revision)
    await runtime.cancel(waiting.run_id)
    with pytest.raises(ContractError, match="invalid or already-used resume token"):
        await runtime.resume(token, {"confirmed": True})


@pytest.mark.asyncio
async def test_state_persisted_at_every_observable_transition() -> None:
    from all_tomorrow.storage import InMemoryRunStateStore

    store = InMemoryRunStateStore()
    runtime = PipelineRuntime(store=store)

    attempts_seen: list[int] = []

    class RetryingNode:
        async def run(self, context, config, inputs) -> NodeResult:
            attempts_seen.append(1)
            if len(attempts_seen) < 2:
                return NodeResult(status=NodeStatus.RETRY, error="transient failure")
            return NodeResult(status=NodeStatus.SUCCESS, output="retry_ok")

    runtime.register("retry_node", RetryingNode())
    runtime.register("ask_node", ConfirmNode())
    runtime.register("record_node", RecordingNode("record", []))

    spec = PipelineSpec(
        pipeline_id="transition_tracker",
        version=1,
        status="active",
        steps=(
            PipelineStep(id="s_retry", type="retry_node", max_retries=2, next_step="confirm_project"),
            PipelineStep(id="confirm_project", type="ask_node", next_step="s_record"),
            PipelineStep(id="s_record", type="record_node"),
        ),
    )

    ctx = context()
    waiting = await runtime.start(spec, ctx)
    assert waiting.status is RunStatus.NEED_USER

    # Check store at suspension
    run_snap = await store.get_run(waiting.run_id)
    assert run_snap is not None
    assert run_snap.spec.identity == "transition_tracker@1"
    assert run_snap.attempts == {"s_retry": 1}
    assert run_snap.outputs == {"s_retry": "retry_ok"}
    assert run_snap.current_step_id == "confirm_project"
    assert run_snap.status is RunStatus.NEED_USER
    assert run_snap.question is not None
    assert run_snap.question.blocked_step == "confirm_project"
    assert run_snap.question.resume_token is None  # no plaintext token in store
    assert run_snap.revision >= 3  # initial -> retry -> s_retry complete -> confirm_project NEED_USER

    # Resume
    resumed = await runtime.resume(waiting.question.resume_token, {"confirmed": True})
    assert resumed.status is RunStatus.SUCCEEDED

    # Check store at completion
    final_snap = await store.get_run(waiting.run_id)
    assert final_snap is not None
    assert final_snap.status is RunStatus.SUCCEEDED
    assert final_snap.question is None
    assert final_snap.outputs["s_retry"] == "retry_ok"
    assert final_snap.outputs["confirm_project"] == {"confirmed": True}
    assert final_snap.outputs["s_record"] == "record"
    assert final_snap.revision > run_snap.revision


@pytest.mark.asyncio
async def test_atomic_resume_fault_leaves_token_reusable_and_run_need_user() -> None:
    from all_tomorrow.storage import InMemoryRunStateStore, RunConflictError, hash_resume_token

    store = InMemoryRunStateStore()
    runtime = PipelineRuntime(store=store)
    runtime.register("ask", ConfirmNode())
    runtime.register("finish", RecordingNode("finish", []))

    spec = PipelineSpec(
        pipeline_id="fault_test",
        version=1,
        status="active",
        steps=(
            PipelineStep(id="confirm_project", type="ask", next_step="finish"),
            PipelineStep(id="finish", type="finish"),
        ),
    )

    waiting = await runtime.start(spec, context())
    assert waiting.status is RunStatus.NEED_USER
    token = waiting.question.resume_token
    token_hash = hash_resume_token(token)

    # Verify initial suspension state in store
    assert store._questions[token_hash]["status"] == "pending"
    initial_run = await store.get_run(waiting.run_id)
    assert initial_run is not None
    assert initial_run.status is RunStatus.NEED_USER
    initial_revision = initial_run.revision

    # Inject a failure into the atomic resume operation (simulating transaction abort/process fault/conflict)
    original_resume_run = store.resume_run
    fail_atomic_resume = True

    async def faulty_resume_run(th: str, ans: dict[str, Any]):
        if fail_atomic_resume:
            raise RunConflictError("simulated crash during atomic resume")
        return await original_resume_run(th, ans)

    store.resume_run = faulty_resume_run

    # Attempting to resume fails with the simulated fault
    with pytest.raises(RunConflictError, match="simulated crash during atomic resume"):
        await runtime.resume(token, {"confirmed": True})

    # Invariants after failed resume:
    # 1. Question record is untouched (still pending, no answer recorded)
    assert store._questions[token_hash]["status"] == "pending"
    assert store._questions[token_hash]["answer"] is None
    assert store._questions[token_hash]["answered_at"] is None

    # 2. Run record is untouched (still NEED_USER, revision unchanged, question preserved)
    run_after_fault = await store.get_run(waiting.run_id)
    assert run_after_fault is not None
    assert run_after_fault.status is RunStatus.NEED_USER
    assert run_after_fault.revision == initial_revision
    assert run_after_fault.question is not None

    # 3. Token remains fully reusable! Clear the fault and resume with the exact same token
    fail_atomic_resume = False
    resumed = await runtime.resume(token, {"confirmed": True})
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.run_id == waiting.run_id
    assert resumed.outputs["confirm_project"] == {"confirmed": True}
    assert resumed.outputs["finish"] == "finish"

    # 4. Now the question is consumed and run is SUCCEEDED
    assert store._questions[token_hash]["status"] == "answered"
    final_run = await store.get_run(waiting.run_id)
    assert final_run is not None
    assert final_run.status is RunStatus.SUCCEEDED
    assert final_run.revision > initial_revision
