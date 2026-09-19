from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from all_tomorrow.contracts import (
    Actor,
    ContractError,
    ExecutionContext,
    NodeResult,
    NodeStatus,
    PipelineSpec,
    PipelineStep,
    RequestEnvelope,
    Worker,
    WorkerAdapter,
    WorkerRequest,
    WorkerResult,
    WorkerStatus,
)
from all_tomorrow.pipeline import (
    CapabilitySelectNode,
    PipelineRuntime,
    RunResult,
    RunStatus,
    WorkerRunNode,
    load_pipeline,
)
from all_tomorrow.registry import CapabilityRegistry, SelectionRequest, WorkerService


class FakeWorkerAdapter:
    def __init__(
        self,
        worker_id: str,
        capabilities: frozenset[str],
        *,
        available: bool = True,
        result_status: WorkerStatus = WorkerStatus.SUCCESS,
        result_payload: dict[str, Any] | None = None,
        result_error: str | None = None,
        duration_ms: int = 15,
    ) -> None:
        self._worker_id = worker_id
        self._capabilities = capabilities
        self._available = available
        self._result_status = result_status
        self._result_payload = result_payload if result_payload is not None else {"done": True}
        self._result_error = result_error
        self._duration_ms = duration_ms
        self.executed_requests: list[WorkerRequest] = []

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    async def is_available(self) -> bool:
        return self._available

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        self.executed_requests.append(request)
        err = self._result_error
        if self._result_status is not WorkerStatus.SUCCESS and not err:
            err = f"Adapter failure with status {self._result_status.value}"
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=self._result_status,
            payload=self._result_payload if self._result_status is WorkerStatus.SUCCESS else None,
            duration_ms=self._duration_ms,
            error=err,
        )


def make_context(
    message: str = "Implement the feature",
    *,
    candidate_project_id: str | None = "project:eve",
    project_ref: str | None = "project:eve",
    request_id: str = "req_123",
    trace_id: str = "trace_456",
    cwd: str | None = None,
) -> ExecutionContext:
    variables: dict[str, Any] = {}
    if cwd is not None:
        variables["cwd"] = cwd
    return ExecutionContext(
        request=RequestEnvelope(
            message=message,
            source="test",
            request_id=request_id,
            candidate_project_id=candidate_project_id,
        ),
        user_ref="user:alice",
        trace_id=trace_id,
        project_ref=project_ref,
        variables=variables,
    )


# 1. Selection chooses available matching bound adapter
@pytest.mark.asyncio
async def test_selection_chooses_available_matching_bound_adapter(tmp_path: Path) -> None:
    service = WorkerService()
    adapter_ag = FakeWorkerAdapter("antigravity", frozenset({"coding", "repo_edit"}))
    adapter_oc = FakeWorkerAdapter("opencode", frozenset({"coding", "terminal"}))

    service.register_worker(
        Worker("antigravity", frozenset({"coding", "repo_edit"}), status="available", evaluation_score=0.9),
        adapter_ag,
    )
    service.register_worker(
        Worker("opencode", frozenset({"coding", "terminal"}), status="available", evaluation_score=0.7),
        adapter_oc,
    )

    runtime = PipelineRuntime(worker_service=service)
    spec = PipelineSpec(
        pipeline_id="select_and_run",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="select",
                type="capability.select",
                inputs={"required_capabilities": ["coding", "repo_edit"]},
            ),
            PipelineStep(
                id="run",
                type="worker.run",
                inputs={
                    "worker_id": "${select.output.worker_id}",
                    "cwd": str(tmp_path),
                },
            ),
        ),
    )

    result = await runtime.start(spec, make_context())
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["select"]["worker_id"] == "antigravity"
    assert result.outputs["run"]["done"] is True
    assert len(adapter_ag.executed_requests) == 1
    assert len(adapter_oc.executed_requests) == 0


# 2. Registration mismatch and duplicate rejected
def test_adapter_metadata_registration_mismatch_and_duplicate_rejected() -> None:
    service = WorkerService()
    adapter = FakeWorkerAdapter("worker_x", frozenset({"coding"}))

    # ID mismatch
    with pytest.raises(ContractError, match="worker_id mismatch"):
        service.register_worker(
            Worker("worker_y", frozenset({"coding"}), status="available"),
            adapter,
        )

    # Capabilities mismatch
    with pytest.raises(ContractError, match="capabilities mismatch"):
        service.register_worker(
            Worker("worker_x", frozenset({"analysis"}), status="available"),
            adapter,
        )

    # Valid registration
    service.register_worker(
        Worker("worker_x", frozenset({"coding"}), status="available"),
        adapter,
    )

    # Duplicate rejected
    with pytest.raises(ContractError, match="already registered"):
        service.register_worker(
            Worker("worker_x", frozenset({"coding"}), status="available"),
            adapter,
        )


# 3. No candidate handling: FAILED unless authorized relaxation, and user override enforces constraints
@pytest.mark.asyncio
async def test_no_candidate_fails_when_no_workers_satisfy_requirements() -> None:
    service = WorkerService()
    adapter = FakeWorkerAdapter("worker_a", frozenset({"analysis"}))
    service.register_worker(
        Worker("worker_a", frozenset({"analysis"}), status="available"),
        adapter,
    )
    runtime = PipelineRuntime(worker_service=service)

    spec = PipelineSpec(
        pipeline_id="fail_no_candidate",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="select",
                type="capability.select",
                inputs={"required_capabilities": ["coding", "repo_edit"]},
            ),
        ),
    )
    result = await runtime.start(spec, make_context())
    assert result.status is RunStatus.FAILED
    assert "No available worker satisfies required capabilities" in (result.error or "")


@pytest.mark.asyncio
async def test_no_candidate_with_policy_relaxation_and_override_validation() -> None:
    service = WorkerService()
    adapter = FakeWorkerAdapter("worker_a", frozenset({"analysis"}))
    service.register_worker(
        Worker("worker_a", frozenset({"analysis"}), status="available"),
        adapter,
    )
    runtime = PipelineRuntime(worker_service=service)

    spec = PipelineSpec(
        pipeline_id="relaxation_test",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="select",
                type="capability.select",
                config={"allow_policy_relaxation": True},
                inputs={"required_capabilities": ["coding"]},
            ),
        ),
    )
    waiting = await runtime.start(spec, make_context())
    assert waiting.status is RunStatus.NEED_USER
    assert waiting.question is not None
    assert waiting.question.blocked_step == "select"
    assert waiting.question.required_fields == ("worker_id",)

    # Resuming with nonexistent worker fails closed
    token = waiting.question.resume_token
    assert token is not None
    resumed_invalid = await runtime.resume(token, {"worker_id": "nonexistent"})
    assert resumed_invalid.status is RunStatus.FAILED
    assert "not found in registry" in (resumed_invalid.error or "")


@pytest.mark.asyncio
async def test_user_override_enforces_required_capabilities_without_relaxation() -> None:
    service = WorkerService()
    adapter_a = FakeWorkerAdapter("worker_a", frozenset({"analysis"}))
    adapter_b = FakeWorkerAdapter("worker_b", frozenset({"coding"}))
    service.register_worker(Worker("worker_a", frozenset({"analysis"}), status="available"), adapter_a)
    service.register_worker(Worker("worker_b", frozenset({"coding"}), status="available"), adapter_b)

    runtime = PipelineRuntime(worker_service=service)
    # Manual selection required among matching candidates
    spec = PipelineSpec(
        pipeline_id="manual_selection",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="select",
                type="capability.select",
                config={"require_user_selection": True},
                inputs={"required_capabilities": ["coding"]},
            ),
        ),
    )
    waiting = await runtime.start(spec, make_context())
    assert waiting.status is RunStatus.NEED_USER
    token = waiting.question.resume_token
    assert token is not None

    # User attempts to pick worker_a which does NOT satisfy "coding"
    resumed = await runtime.resume(token, {"worker_id": "worker_a"})
    assert resumed.status is RunStatus.FAILED
    assert "does not satisfy required capabilities" in (resumed.error or "")


# 4. Missing cwd returns NEED_USER and resumes using exact blocked step id
@pytest.mark.asyncio
async def test_missing_cwd_returns_need_user_and_resumes_with_exact_blocked_step(tmp_path: Path) -> None:
    service = WorkerService()
    adapter = FakeWorkerAdapter("coding_worker", frozenset({"coding"}))
    service.register_worker(Worker("coding_worker", frozenset({"coding"}), status="available"), adapter)

    runtime = PipelineRuntime(worker_service=service)
    custom_step_id = "custom_code_step"
    spec = PipelineSpec(
        pipeline_id="cwd_test",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id=custom_step_id,
                type="worker.run",
                inputs={"worker_id": "coding_worker"},  # cwd omitted
            ),
        ),
    )

    waiting = await runtime.start(spec, make_context(cwd=None))
    assert waiting.status is RunStatus.NEED_USER
    assert waiting.question is not None
    assert waiting.question.blocked_step == custom_step_id
    assert waiting.question.required_fields == ("cwd",)
    token = waiting.question.resume_token
    assert token is not None

    resumed = await runtime.resume(token, {"cwd": str(tmp_path)})
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(adapter.executed_requests) == 1
    assert adapter.executed_requests[0].payload["cwd"] == str(tmp_path)


# 5. Status mappings: SUCCESS, RETRY, FAILED
@pytest.mark.asyncio
async def test_worker_status_mappings_and_retries(tmp_path: Path) -> None:
    service = WorkerService()

    timeout_adapter = FakeWorkerAdapter(
        "timeout_worker", frozenset({"coding"}), result_status=WorkerStatus.TIMEOUT
    )
    failed_adapter = FakeWorkerAdapter(
        "failed_worker", frozenset({"coding"}), result_status=WorkerStatus.FAILED, result_error="Crash"
    )
    traversal_adapter = FakeWorkerAdapter(
        "traversal_worker", frozenset({"coding"}), result_status=WorkerStatus.TRAVERSAL_BLOCKED, result_error="Traversal"
    )
    service.register_worker(Worker("timeout_worker", frozenset({"coding"}), status="available"), timeout_adapter)
    service.register_worker(Worker("failed_worker", frozenset({"coding"}), status="available"), failed_adapter)
    service.register_worker(Worker("traversal_worker", frozenset({"coding"}), status="available"), traversal_adapter)

    runtime = PipelineRuntime(worker_service=service)

    # TIMEOUT retries and exhausts
    spec_timeout = PipelineSpec(
        pipeline_id="timeout_spec",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="s1",
                type="worker.run",
                inputs={"worker_id": "timeout_worker", "cwd": str(tmp_path)},
                max_retries=2,
            ),
        ),
    )
    res_timeout = await runtime.start(spec_timeout, make_context())
    assert res_timeout.status is RunStatus.FAILED
    assert len(timeout_adapter.executed_requests) == 3  # initial + 2 retries

    # TRAVERSAL_BLOCKED fails immediately without retry
    spec_trav = PipelineSpec(
        pipeline_id="trav_spec",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="s2",
                type="worker.run",
                inputs={"worker_id": "traversal_worker", "cwd": str(tmp_path)},
                max_retries=2,
            ),
        ),
    )
    res_trav = await runtime.start(spec_trav, make_context())
    assert res_trav.status is RunStatus.FAILED
    assert len(traversal_adapter.executed_requests) == 1

    # FAILED with retry_on_fail config retries
    spec_retry_fail = PipelineSpec(
        pipeline_id="retry_fail_spec",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="s3",
                type="worker.run",
                config={"retry_on_fail": True},
                inputs={"worker_id": "failed_worker", "cwd": str(tmp_path)},
                max_retries=1,
            ),
        ),
    )
    res_rf = await runtime.start(spec_retry_fail, make_context())
    assert res_rf.status is RunStatus.FAILED
    assert len(failed_adapter.executed_requests) == 2


# 6. Trace, request, project propagation
@pytest.mark.asyncio
async def test_trace_request_project_propagation(tmp_path: Path) -> None:
    service = WorkerService()
    adapter = FakeWorkerAdapter("worker_p", frozenset({"coding"}))
    service.register_worker(Worker("worker_p", frozenset({"coding"}), status="available"), adapter)
    runtime = PipelineRuntime(worker_service=service)

    ctx = make_context(
        message="Original user message",
        request_id="req_fixed_999",
        trace_id="trace_fixed_888",
        project_ref="project:eve_core",
    )

    spec = PipelineSpec(
        pipeline_id="prop_spec",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="step_exec",
                type="worker.run",
                inputs={
                    "worker_id": "worker_p",
                    "cwd": str(tmp_path),
                    "task": "Explicit refactoring task",
                    "constraints": ["No network calls"],
                    "acceptance_criteria": ["All unit tests pass"],
                    "expected_result_format": "json",
                },
            ),
        ),
    )

    res = await runtime.start(spec, ctx)
    assert res.status is RunStatus.SUCCEEDED
    assert len(adapter.executed_requests) == 1
    req = adapter.executed_requests[0]
    assert req.request_id == "req_fixed_999"
    assert req.trace_id == "trace_fixed_888"
    assert req.project_id == "project:eve_core"
    assert req.payload["message"] == "Original user message"
    assert req.payload["task"] == "Explicit refactoring task"
    assert req.payload["constraints"] == ["No network calls"]
    assert req.payload["acceptance_criteria"] == ["All unit tests pass"]
    assert req.payload["expected_result_format"] == "json"
    assert req.payload["cwd"] == str(tmp_path)


# 7. YAML-only worker choice and order inputs change without code edits
@pytest.mark.asyncio
async def test_yaml_only_worker_choice_and_coding_pipeline(tmp_path: Path) -> None:
    service = WorkerService()
    adapter_ag = FakeWorkerAdapter("antigravity", frozenset({"coding", "repo_edit"}))
    service.register_worker(
        Worker("antigravity", frozenset({"coding", "repo_edit"}), status="available"),
        adapter_ag,
    )
    runtime = PipelineRuntime(worker_service=service)

    # Load pipelines/coding.yaml
    spec = load_pipeline("pipelines/coding.yaml")
    assert spec.pipeline_id == "coding"
    assert spec.version == 1

    # First run without cwd -> pauses at run_worker
    ctx = make_context(message="Fix bug in parser")
    waiting = await runtime.start(spec, ctx)
    assert waiting.status is RunStatus.NEED_USER
    assert waiting.question is not None
    assert waiting.question.blocked_step == "run_worker"

    # Resume with cwd -> completes
    resumed = await runtime.resume(waiting.question.resume_token, {"cwd": str(tmp_path)})
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(adapter_ag.executed_requests) == 1
    assert adapter_ag.executed_requests[0].payload["task"] == "Fix bug in parser"


# 8. Events contain provenance but no prompt, message, constraints, or secrets
@pytest.mark.asyncio
async def test_events_contain_provenance_without_prompt_or_secrets(tmp_path: Path) -> None:
    service = WorkerService()
    secret_token = "SECRET_TOKEN_XYZ_999"
    raw_prompt_text = "SECRET_TASK: Refactor auth with SECRET_TOKEN_XYZ_999"
    adapter = FakeWorkerAdapter("worker_safe", frozenset({"coding"}))
    service.register_worker(Worker("worker_safe", frozenset({"coding"}), status="available"), adapter)

    runtime = PipelineRuntime(worker_service=service)
    spec = PipelineSpec(
        pipeline_id="event_privacy_spec",
        version=1,
        status="active",
        steps=(
            PipelineStep(
                id="select",
                type="capability.select",
                inputs={"required_capabilities": ["coding"]},
            ),
            PipelineStep(
                id="run",
                type="worker.run",
                inputs={
                    "worker_id": "${select.output.worker_id}",
                    "cwd": str(tmp_path),
                    "task": raw_prompt_text,
                    "constraints": [secret_token],
                },
            ),
        ),
    )

    ctx = make_context(message=f"Original message with {secret_token}")
    res = await runtime.start(spec, ctx)
    assert res.status is RunStatus.SUCCEEDED

    events = runtime.event_sink.events
    assert any(e.type == "capability.selected" for e in events)
    assert any(e.type == "worker.executed" for e in events)

    # Prove no raw prompt, message, or secrets leaked into event metadata
    for ev in events:
        meta_str = str(ev.metadata)
        assert secret_token not in meta_str
        assert "SECRET_TASK" not in meta_str
        assert "prompt" not in ev.metadata
        assert "message" not in ev.metadata
        assert "task" not in ev.metadata
        assert "constraints" not in ev.metadata
        assert "payload" not in ev.metadata

    # Check worker.executed event metadata specifically
    exec_events = [e for e in events if e.type == "worker.executed"]
    assert len(exec_events) == 1
    meta = exec_events[0].metadata
    assert meta["worker_id"] == "worker_safe"
    assert meta["worker_request_id"] == ctx.request.request_id
    assert meta["trace_id"] == ctx.trace_id
    assert meta["project_id"] == ctx.project_ref
    assert meta["status"] == WorkerStatus.SUCCESS.value
    assert exec_events[0].actor == Actor.AGENT


# 9. Invalid event actor or type fails closed predictably
@pytest.mark.asyncio
async def test_invalid_event_fails_closed() -> None:
    class BadEventNode:
        async def run(self, context, config, inputs) -> NodeResult:
            return NodeResult(
                status=NodeStatus.SUCCESS,
                events=({"type": "", "actor": Actor.AGENT},),
            )

    runtime = PipelineRuntime()
    runtime.register("bad_node", BadEventNode())
    spec = PipelineSpec(
        pipeline_id="bad_event_spec",
        version=1,
        status="active",
        steps=(PipelineStep(id="s", type="bad_node"),),
    )
    res = await runtime.start(spec, make_context())
    assert res.status is RunStatus.FAILED
    assert "invalid type" in (res.error or "")


# 10. register_available_workers works atomically with WorkerService
@pytest.mark.asyncio
async def test_register_available_workers_with_worker_service(tmp_path: Path) -> None:
    from all_tomorrow.adapters.workers import register_available_workers

    service = WorkerService()
    with patch("shutil.which", return_value="/usr/bin/agy"):
        registered = await register_available_workers(
            service,
            antigravity_argv=["agy"],
            allowed_roots=(str(tmp_path),),
        )
    assert registered == ["antigravity"]
    worker = service.get_worker("antigravity")
    assert worker is not None
    assert worker.status == "available"
    adapter = service.get_adapter("antigravity")
    assert adapter.worker_id == "antigravity"
