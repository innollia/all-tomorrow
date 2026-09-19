from __future__ import annotations

from typing import Any

from all_tomorrow.contracts import (
    Actor,
    ContractError,
    ExecutionContext,
    NodeResult,
    NodeStatus,
    UserQuestion,
    WorkerRequest,
    WorkerStatus,
)
from all_tomorrow.registry import CapabilityRegistry, SelectionRequest, WorkerService


class CapabilitySelectNode:
    """Pipeline node that selects an available worker matching required capabilities."""

    def __init__(self, service: WorkerService | CapabilityRegistry) -> None:
        self._service = service
        self._registry = service.registry if isinstance(service, WorkerService) else service

    async def run(
        self,
        context: ExecutionContext,
        config: dict[str, Any],
        inputs: dict[str, Any],
    ) -> NodeResult:
        step_id = config.get("step_id") or inputs.get("step_id") or "capability.select"

        # 1. Parse required capabilities
        raw_caps = (
            inputs.get("required_capabilities")
            or config.get("required_capabilities")
            or inputs.get("capabilities")
            or config.get("capabilities")
        )
        if isinstance(raw_caps, str):
            req_caps = frozenset(c.strip() for c in raw_caps.split(",") if c.strip())
        elif isinstance(raw_caps, (list, tuple, set, frozenset)):
            req_caps = frozenset(str(c) for c in raw_caps)
        else:
            req_caps = frozenset()

        # 2. Parse privacy tags
        raw_tags = inputs.get("privacy_tags") or config.get("privacy_tags") or ()
        if isinstance(raw_tags, str):
            priv_tags = frozenset(p.strip() for p in raw_tags.split(",") if p.strip())
        elif isinstance(raw_tags, (list, tuple, set, frozenset)):
            priv_tags = frozenset(str(p) for p in raw_tags)
        else:
            priv_tags = frozenset()

        allow_policy_relaxation = bool(
            config.get("allow_policy_relaxation") or inputs.get("allow_policy_relaxation")
        )

        # 3. Check if answered via resume or explicit user override
        user_answers = context.variables.get("user_answers", {}).get(step_id, {})
        if "worker_id" in user_answers:
            chosen_id = user_answers["worker_id"]
            chosen = self._registry.get_worker(chosen_id)
            if chosen is None:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=f"Selected worker {chosen_id!r} not found in registry",
                )
            if chosen.status != "available":
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=f"Selected worker {chosen_id!r} is not available in registry",
                )
            # User override must enforce required capabilities and privacy tags
            if not allow_policy_relaxation:
                if not (req_caps <= chosen.capabilities):
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=(
                            f"Selected worker {chosen_id!r} does not satisfy required capabilities "
                            f"{sorted(req_caps)}"
                        ),
                    )
                if not (priv_tags <= chosen.privacy_tags):
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=(
                            f"Selected worker {chosen_id!r} does not satisfy required privacy tags "
                            f"{sorted(priv_tags)}"
                        ),
                    )

            event = {
                "type": "capability.selected",
                "actor": Actor.AGENT,
                "metadata": {
                    "worker_id": chosen.worker_id,
                    "capabilities": sorted(chosen.capabilities),
                    "selection_source": "user_override",
                },
            }
            return NodeResult(
                status=NodeStatus.SUCCESS,
                output={
                    "worker_id": chosen.worker_id,
                    "capabilities": sorted(chosen.capabilities),
                    "status": chosen.status,
                    "cost_score": chosen.cost_score,
                    "evaluation_score": chosen.evaluation_score,
                    "privacy_tags": sorted(chosen.privacy_tags),
                },
                events=(event,),
            )

        # 4. Select matching worker (maximum_risk is irrelevant to worker selection)
        selected = self._registry.select_worker(
            SelectionRequest(
                required_capabilities=req_caps,
                privacy_tags=priv_tags,
            )
        )

        # 5. If matching worker found
        if selected is not None:
            # If pipeline policy explicitly requires user selection among matching candidates
            if config.get("require_user_selection"):
                matching_workers = [
                    w.worker_id
                    for w in self._registry.list_workers()
                    if w.status == "available"
                    and req_caps <= w.capabilities
                    and priv_tags <= w.privacy_tags
                ]
                return NodeResult(
                    status=NodeStatus.NEED_USER,
                    user_question=UserQuestion(
                        question=(
                            f"Matching workers available: {', '.join(sorted(matching_workers))}. "
                            f"Select worker to use:"
                        ),
                        reason="Policy requires explicit user confirmation of worker choice.",
                        blocked_step=step_id,
                        required_fields=("worker_id",),
                    ),
                )

            event = {
                "type": "capability.selected",
                "actor": Actor.AGENT,
                "metadata": {
                    "worker_id": selected.worker_id,
                    "capabilities": sorted(selected.capabilities),
                },
            }
            return NodeResult(
                status=NodeStatus.SUCCESS,
                output={
                    "worker_id": selected.worker_id,
                    "capabilities": sorted(selected.capabilities),
                    "status": selected.status,
                    "cost_score": selected.cost_score,
                    "evaluation_score": selected.evaluation_score,
                    "privacy_tags": sorted(selected.privacy_tags),
                },
                events=(event,),
            )

        # 6. No worker matched requirements
        available_workers = [
            w.worker_id for w in self._registry.list_workers() if w.status == "available"
        ]

        if allow_policy_relaxation and available_workers:
            return NodeResult(
                status=NodeStatus.NEED_USER,
                user_question=UserQuestion(
                    question=(
                        f"No worker satisfies required capabilities {sorted(req_caps)}. "
                        f"Policy authorizes relaxation. Available workers: {', '.join(sorted(available_workers))}. "
                        f"Select worker to use:"
                    ),
                    reason="Explicit policy authorization permits user relaxation of worker requirements.",
                    blocked_step=step_id,
                    required_fields=("worker_id",),
                ),
            )

        return NodeResult(
            status=NodeStatus.FAILED,
            error=(
                f"No available worker satisfies required capabilities {sorted(req_caps)} "
                f"with privacy tags {sorted(priv_tags)}"
            ),
        )


class WorkerRunNode:
    """Pipeline node that builds WorkerRequest and executes a bound WorkerAdapter."""

    def __init__(self, service: WorkerService) -> None:
        self._service = service

    async def run(
        self,
        context: ExecutionContext,
        config: dict[str, Any],
        inputs: dict[str, Any],
    ) -> NodeResult:
        step_id = config.get("step_id") or inputs.get("step_id") or "worker.run"

        # 1. Resolve worker_id
        worker_id = inputs.get("worker_id") or config.get("worker_id")
        if isinstance(worker_id, dict):
            worker_id = worker_id.get("worker_id")
        if not worker_id or not isinstance(worker_id, str):
            return NodeResult(
                status=NodeStatus.FAILED,
                error="Missing required input 'worker_id' for worker.run step",
            )

        # Verify adapter is registered
        try:
            adapter = self._service.get_adapter(worker_id)
        except ContractError as err:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Worker {worker_id!r} has no bound executable adapter: {err}",
            )

        # 2. Resolve cwd and check clarification boundary using exact blocked step id
        user_answers = context.variables.get("user_answers", {}).get(step_id, {})
        cwd = (
            user_answers.get("cwd")
            or user_answers.get("project_path")
            or user_answers.get("repository_path")
            or inputs.get("cwd")
            or config.get("cwd")
            or context.variables.get("cwd")
        )

        mutation_possible = (
            config.get("mutation", True) is not False
            and inputs.get("mutation", True) is not False
        )

        if not cwd:
            if mutation_possible:
                return NodeResult(
                    status=NodeStatus.NEED_USER,
                    user_question=UserQuestion(
                        question="Please specify the project or repository working directory path (cwd).",
                        reason="Working directory must be explicitly provided when repository mutation is possible.",
                        blocked_step=step_id,
                        required_fields=("cwd",),
                    ),
                )
            return NodeResult(
                status=NodeStatus.FAILED,
                error="Working directory (cwd) must be specified for worker execution",
            )

        # 3. Build WorkerRequest payload propagating task, constraints, criteria, format, cwd
        task = inputs.get("task") or config.get("task") or context.request.message
        constraints = inputs.get("constraints") or config.get("constraints")
        acceptance_criteria = inputs.get("acceptance_criteria") or config.get("acceptance_criteria")
        expected_format = (
            inputs.get("expected_result_format")
            or config.get("expected_result_format")
            or inputs.get("result_format")
            or config.get("result_format")
        )

        payload: dict[str, Any] = {
            "message": context.request.message,
            "cwd": str(cwd),
        }
        if task is not None:
            payload["task"] = task
        if constraints is not None:
            payload["constraints"] = constraints
        if acceptance_criteria is not None:
            payload["acceptance_criteria"] = acceptance_criteria
        if expected_format is not None:
            payload["expected_result_format"] = expected_format

        # Extra payload inputs/configs without overwriting reserved fields
        reserved = {
            "worker_id",
            "required_capabilities",
            "capabilities",
            "step_id",
            "cwd",
            "message",
            "task",
            "constraints",
            "acceptance_criteria",
            "expected_result_format",
            "result_format",
            "payload",
            "retry_on_fail",
            "retry_statuses",
            "mutation",
            "allow_policy_relaxation",
            "require_user_selection",
        }
        for source in (config.get("payload", {}), inputs.get("payload", {}), config, inputs):
            if isinstance(source, dict):
                for k, v in source.items():
                    if k not in reserved:
                        payload.setdefault(k, v)

        # 4. Resolve capabilities and project_id
        capabilities = adapter.capabilities
        worker_meta = self._service.get_worker(worker_id)
        if worker_meta:
            capabilities = worker_meta.capabilities

        project_id = (
            context.project_ref
            or inputs.get("project_id")
            or config.get("project_id")
            or context.request.candidate_project_id
        )

        worker_request = WorkerRequest(
            request_id=context.request.request_id,
            trace_id=context.trace_id,
            project_id=project_id,
            capabilities=capabilities,
            payload=payload,
        )

        # 5. Execute worker adapter
        worker_result = await self._service.execute(worker_id, worker_request)

        # 6. Build event with minimal provenance metadata (never prompt, payload, or secrets)
        event = {
            "type": "worker.executed",
            "actor": Actor.AGENT,
            "metadata": {
                "worker_id": worker_id,
                "worker_request_id": worker_request.request_id,
                "trace_id": worker_request.trace_id,
                "project_id": worker_request.project_id,
                "status": worker_result.status.value,
                "duration_ms": worker_result.duration_ms,
            },
        }

        # 7. Map WorkerStatus deterministically
        retry_statuses = set(config.get("retry_statuses", ()))
        if config.get("retry_on_fail"):
            retry_statuses.add(WorkerStatus.FAILED.value)

        if worker_result.status is WorkerStatus.SUCCESS:
            return NodeResult(
                status=NodeStatus.SUCCESS,
                output=worker_result.payload,
                events=(event,),
            )
        elif worker_result.status is WorkerStatus.TIMEOUT or worker_result.status.value in retry_statuses:
            return NodeResult(
                status=NodeStatus.RETRY,
                error=worker_result.error or f"Worker timed out: {worker_id}",
                output=worker_result.payload,
                events=(event,),
            )
        else:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=worker_result.error or f"Worker {worker_id} failed with status {worker_result.status.value}",
                output=worker_result.payload,
                events=(event,),
            )


AgentRunNode = WorkerRunNode
