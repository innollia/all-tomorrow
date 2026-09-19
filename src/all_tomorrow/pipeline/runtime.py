from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from all_tomorrow.contracts import (
    Actor,
    ContractError,
    Event,
    ExecutionContext,
    NodeResult,
    NodeStatus,
    PipelineSpec,
    PipelineStep,
    UserQuestion,
    new_id,
)
from all_tomorrow.registry import WorkerService
from all_tomorrow.storage.run_store import (
    InMemoryRunStateStore,
    QuestionRecord,
    RunConflictError,
    RunRecord,
    RunStateStore,
    RunStatus,
    hash_resume_token,
)
from .nodes import CapabilitySelectNode, WorkerRunNode


class PipelineNode(Protocol):
    async def run(
        self,
        context: ExecutionContext,
        config: dict[str, Any],
        inputs: dict[str, Any],
    ) -> NodeResult: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    trace_id: str
    pipeline_id: str
    pipeline_version: int
    status: RunStatus
    outputs: dict[str, Any]
    question: UserQuestion | None = None
    error: str | None = None


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def append(self, event: Event) -> None:
        self.events.append(event)


_FULL_REFERENCE = re.compile(r"^\$\{([^}]+)}$")
_INLINE_REFERENCE = re.compile(r"\$\{([^}]+)}")


class PipelineRuntime:
    """Stateless pipeline execution runtime backed by a RunStateStore."""

    def __init__(
        self,
        *,
        store: RunStateStore | None = None,
        event_sink: InMemoryEventSink | None = None,
        worker_service: WorkerService | None = None,
    ) -> None:
        self._nodes: dict[str, PipelineNode] = {}
        self.store: RunStateStore = store or InMemoryRunStateStore()
        self.event_sink = event_sink or InMemoryEventSink()
        self.worker_service = worker_service
        if worker_service is not None:
            self.register("capability.select", CapabilitySelectNode(worker_service))
            self.register("worker.run", WorkerRunNode(worker_service))
            self.register("agent.run", WorkerRunNode(worker_service))

    def register(self, node_type: str, node: PipelineNode) -> None:
        if not node_type.strip():
            raise ContractError("node_type must not be empty")
        if node_type in self._nodes:
            raise ContractError(f"node type already registered: {node_type}")
        self._nodes[node_type] = node

    async def start(self, spec: PipelineSpec, context: ExecutionContext) -> RunResult:
        if spec.status != "active":
            raise ContractError(f"pipeline must be active to run: {spec.identity}")
        run = RunRecord(
            run_id=new_id("run"),
            spec=spec,
            context=context,
            current_step_id=spec.steps[0].id,
            revision=0,
            status=RunStatus.RUNNING,
        )
        await self.store.create_run(run)
        await self._event(run, "run.started", Actor.ORCHESTRATOR, {"pipeline": spec.identity})
        return await self._drive(run)

    async def resume(self, resume_token: str, answer: dict[str, Any]) -> RunResult:
        if not isinstance(resume_token, str) or not resume_token.strip():
            raise ContractError("invalid or already-used resume token")
        token_hash = hash_resume_token(resume_token)

        resumed_run = await self.store.resume_run(token_hash, answer)
        await self._event(
            resumed_run,
            "run.user_answered",
            Actor.USER,
            {"step_id": resumed_run.current_step_id},
        )
        return await self._drive(resumed_run)

    async def cancel(self, run_id: str) -> RunResult:
        run = await self.store.get_run(run_id)
        if run is None:
            raise ContractError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ContractError(f"run is already terminal: {run.status}")
        run.status = RunStatus.CANCELLED
        await self.store.cancel_pending_questions(run_id)
        run.revision = await self.store.update_run(run, expected_revision=run.revision)
        await self._event(run, "run.cancelled", Actor.USER, {"step_id": run.current_step_id})
        return self._result(run)

    async def _drive(self, run: RunRecord) -> RunResult:
        step_by_id = {step.id: step for step in run.spec.steps}
        ordered_ids = [step.id for step in run.spec.steps]
        visited = 0

        while run.status is RunStatus.RUNNING:
            visited += 1
            if visited > max(100, len(ordered_ids) * 10):
                return await self._fail(run, "pipeline exceeded step execution safety limit")

            step = step_by_id[run.current_step_id]
            try:
                condition_matches = self._condition_matches(step.when, run)
            except ContractError as error:
                return await self._fail(run, str(error))
            if not condition_matches:
                await self._event(run, "step.skipped", Actor.ORCHESTRATOR, {"step_id": step.id})
                next_id = self._default_next(step, ordered_ids)
                if next_id is None:
                    return await self._succeed(run)
                run.current_step_id = next_id
                run.revision = await self.store.update_run(run, expected_revision=run.revision)
                continue

            node = self._nodes.get(step.type)
            if node is None:
                return await self._fail(run, f"unregistered node type: {step.type}")

            try:
                inputs = self._resolve(step.inputs, run)
                config = self._resolve(step.config, run)
            except ContractError as error:
                return await self._fail(run, str(error))

            if isinstance(config, dict):
                config.setdefault("step_id", step.id)

            await self._event(run, "step.started", Actor.ORCHESTRATOR, {"step_id": step.id, "node_type": step.type})
            try:
                result = await node.run(run.context, config, inputs)
            except Exception as error:  # node boundary converts implementation errors to run failure
                return await self._fail(run, f"node {step.id} raised {type(error).__name__}: {error}")

            for node_event in result.events:
                if not isinstance(node_event, dict):
                    return await self._fail(run, f"node {step.id} emitted non-dict event")
                ev_type = node_event.get("type")
                if not isinstance(ev_type, str) or not ev_type.strip():
                    return await self._fail(run, f"node {step.id} emitted event with invalid type: {ev_type!r}")
                ev_actor_val = node_event.get("actor", Actor.AGENT)
                try:
                    ev_actor = Actor(ev_actor_val) if not isinstance(ev_actor_val, Actor) else ev_actor_val
                except (ValueError, TypeError):
                    return await self._fail(run, f"node {step.id} emitted event with invalid actor: {ev_actor_val!r}")
                raw_meta = node_event.get("metadata", {})
                if not isinstance(raw_meta, dict):
                    return await self._fail(run, f"node {step.id} emitted event with non-dict metadata")
                ev_meta = dict(raw_meta)
                for forbidden in (
                    "prompt",
                    "message",
                    "instructions",
                    "task",
                    "constraints",
                    "secrets",
                    "secret",
                    "payload",
                    "raw_prompt",
                    "raw_output",
                    "acceptance_criteria",
                    "expected_result_format",
                ):
                    ev_meta.pop(forbidden, None)
                ev_meta.setdefault("pipeline", run.spec.identity)
                ev_meta.setdefault("step_id", step.id)
                await self._event(
                    run,
                    ev_type.strip(),
                    ev_actor,
                    ev_meta,
                    artifact_refs=tuple(node_event.get("artifact_refs", ())),
                )

            await self._event(
                run,
                "step.completed",
                Actor.ORCHESTRATOR,
                {"step_id": step.id, "status": result.status.value},
                artifact_refs=result.artifacts,
            )

            if result.status is NodeStatus.RETRY:
                attempts = run.attempts.get(step.id, 0) + 1
                run.attempts[step.id] = attempts
                if attempts <= step.max_retries:
                    run.revision = await self.store.update_run(run, expected_revision=run.revision)
                    await self._event(
                        run, "step.retrying", Actor.ORCHESTRATOR, {"step_id": step.id, "attempt": attempts}
                    )
                    continue
                return await self._fail(run, result.error or f"step {step.id} exhausted retries")

            if result.status is NodeStatus.NEED_USER:
                token = new_id("resume")
                token_hash = hash_resume_token(token)
                run.status = RunStatus.NEED_USER
                # Persist question stripped of plaintext token
                run.question = result.user_question.with_resume_token(None)  # type: ignore[union-attr]
                q_record = QuestionRecord(
                    question_id=new_id("question"),
                    run_id=run.run_id,
                    blocked_step=step.id,
                    question=result.user_question.question,  # type: ignore[union-attr]
                    reason=result.user_question.reason,  # type: ignore[union-attr]
                    required_fields=result.user_question.required_fields,  # type: ignore[union-attr]
                    resume_token_hash=token_hash,
                    status="pending",
                )
                await self.store.create_question(q_record)
                run.revision = await self.store.update_run(run, expected_revision=run.revision)
                await self._event(
                    run,
                    "run.needs_user",
                    Actor.ORCHESTRATOR,
                    {"step_id": step.id, "reason": run.question.reason},
                )
                # Plaintext token returned ONLY to the caller via RunResult
                return RunResult(
                    run_id=run.run_id,
                    trace_id=run.context.trace_id,
                    pipeline_id=run.spec.pipeline_id,
                    pipeline_version=run.spec.version,
                    status=run.status,
                    outputs=dict(run.outputs),
                    question=result.user_question.with_resume_token(token),  # type: ignore[union-attr]
                    error=run.error,
                )

            if result.status is NodeStatus.WAITING:
                run.status = RunStatus.WAITING
                run.revision = await self.store.update_run(run, expected_revision=run.revision)
                return self._result(run)
            if result.status is NodeStatus.CANCELLED:
                run.status = RunStatus.CANCELLED
                run.revision = await self.store.update_run(run, expected_revision=run.revision)
                return self._result(run)
            if result.status is NodeStatus.FAILED:
                return await self._fail(run, result.error or f"step {step.id} failed")

            run.outputs[step.id] = result.output
            run.context.variables.setdefault("steps", {})[step.id] = {"output": result.output}
            run.context.artifact_refs.extend(result.artifacts)

            target = step.on_status.get(result.status.value) or result.next_hint or step.next_step
            if target is None:
                target = self._default_next(step, ordered_ids)
            if target is None:
                return await self._succeed(run)
            if target not in step_by_id:
                return await self._fail(run, f"step {step.id} selected unknown target {target!r}")
            run.current_step_id = target
            run.revision = await self.store.update_run(run, expected_revision=run.revision)

        return self._result(run)

    def _resolve(self, value: Any, run: RunRecord) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve(item, run) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve(item, run) for item in value]
        if not isinstance(value, str):
            return value
        full = _FULL_REFERENCE.match(value)
        if full:
            return self._lookup(full.group(1), run)
        return _INLINE_REFERENCE.sub(lambda match: str(self._lookup(match.group(1), run)), value)

    def _lookup(self, path: str, run: RunRecord) -> Any:
        root: dict[str, Any] = {
            "request": run.context.request,
            "context": run.context,
            "variables": run.context.variables,
            **run.context.variables.get("steps", {}),
        }
        parts = path.split(".")
        current: Any = root
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                raise ContractError(f"unresolved pipeline reference: ${{{path}}}")
        return current

    def _condition_matches(self, condition: dict[str, Any] | None, run: RunRecord) -> bool:
        if condition is None:
            return True
        if not isinstance(condition, dict) or set(condition) != {"ref", "equals"}:
            raise ContractError("step.when must contain exactly ref and equals")
        actual = self._lookup(str(condition["ref"]), run)
        return actual == condition["equals"]

    @staticmethod
    def _default_next(step: PipelineStep, ordered_ids: list[str]) -> str | None:
        index = ordered_ids.index(step.id)
        return ordered_ids[index + 1] if index + 1 < len(ordered_ids) else None

    async def _succeed(self, run: RunRecord) -> RunResult:
        run.status = RunStatus.SUCCEEDED
        run.revision = await self.store.update_run(run, expected_revision=run.revision)
        await self._event(run, "run.succeeded", Actor.ORCHESTRATOR, {})
        return self._result(run)

    async def _fail(self, run: RunRecord, error: str) -> RunResult:
        run.status = RunStatus.FAILED
        run.error = error
        run.revision = await self.store.update_run(run, expected_revision=run.revision)
        await self._event(run, "run.failed", Actor.ORCHESTRATOR, {"error": error})
        return self._result(run)

    def _result(self, run: RunRecord) -> RunResult:
        return RunResult(
            run_id=run.run_id,
            trace_id=run.context.trace_id,
            pipeline_id=run.spec.pipeline_id,
            pipeline_version=run.spec.version,
            status=run.status,
            outputs=dict(run.outputs),
            question=run.question,
            error=run.error,
        )

    async def _event(
        self,
        run: RunRecord,
        event_type: str,
        actor: Actor,
        metadata: dict[str, Any],
        *,
        artifact_refs: tuple[str, ...] = (),
    ) -> None:
        await self.event_sink.append(
            Event(
                type=event_type,
                actor=actor,
                trace_id=run.context.trace_id,
                user_id=run.context.user_ref,
                project_id=run.context.project_ref,
                session_id=run.context.session_ref,
                run_id=run.run_id,
                artifact_refs=artifact_refs,
                metadata=metadata,
            )
        )
