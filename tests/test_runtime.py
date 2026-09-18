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
from all_tomorrow.pipeline import PipelineRuntime, RunStatus, load_pipeline


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

