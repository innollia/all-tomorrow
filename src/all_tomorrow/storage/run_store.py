from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from all_tomorrow.contracts import (
    ContractError,
    ExecutionContext,
    PipelineSpec,
    PipelineStep,
    RequestEnvelope,
    UserQuestion,
    utc_now,
)


class RunConflictError(ContractError):
    """Raised when an optimistic concurrency check fails on run or question state."""


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    NEED_USER = "NEED_USER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def hash_resume_token(token: str) -> str:
    if not isinstance(token, str) or not token.strip():
        raise ContractError("resume token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


@dataclass(slots=True)
class RunRecord:
    run_id: str
    spec: PipelineSpec
    context: ExecutionContext
    current_step_id: str
    outputs: dict[str, Any] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    status: RunStatus = RunStatus.RUNNING
    question: UserQuestion | None = None
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    question_id: str
    run_id: str
    blocked_step: str
    question: str
    reason: str
    required_fields: tuple[str, ...]
    resume_token_hash: str
    status: str = "pending"  # pending, answered, cancelled, expired
    answer: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
    answered_at: datetime | None = None
    expires_at: datetime | None = None


def execution_context_to_dict(context: ExecutionContext) -> dict[str, Any]:
    raw = {
        "request": {
            "message": context.request.message,
            "source": context.request.source,
            "request_id": context.request.request_id,
            "received_at": context.request.received_at.isoformat(),
            "attachments": list(context.request.attachments),
            "session_ref": context.request.session_ref,
            "edge_analysis": dict(context.request.edge_analysis),
            "candidate_project_id": context.request.candidate_project_id,
            "central_reason": context.request.central_reason,
        },
        "user_ref": context.user_ref,
        "trace_id": context.trace_id,
        "project_ref": context.project_ref,
        "session_ref": context.session_ref,
        "memory_refs": list(context.memory_refs),
        "artifact_refs": list(context.artifact_refs),
        "variables": dict(context.variables),
        "budget": dict(context.budget),
        "permissions": sorted(context.permissions),
    }
    return json.loads(json.dumps(raw, default=_json_default))


def execution_context_from_dict(data: dict[str, Any]) -> ExecutionContext:
    req_data = data["request"]
    received_at = req_data.get("received_at")
    if isinstance(received_at, str):
        received_at_dt = datetime.fromisoformat(received_at)
    elif isinstance(received_at, datetime):
        received_at_dt = received_at
    else:
        received_at_dt = utc_now()

    request = RequestEnvelope(
        message=req_data["message"],
        source=req_data["source"],
        request_id=req_data["request_id"],
        received_at=received_at_dt,
        attachments=tuple(req_data.get("attachments", ())),
        session_ref=req_data.get("session_ref"),
        edge_analysis=dict(req_data.get("edge_analysis", {})),
        candidate_project_id=req_data.get("candidate_project_id"),
        central_reason=req_data.get("central_reason"),
    )
    return ExecutionContext(
        request=request,
        user_ref=data["user_ref"],
        trace_id=data["trace_id"],
        project_ref=data.get("project_ref"),
        session_ref=data.get("session_ref"),
        memory_refs=list(data.get("memory_refs", [])),
        artifact_refs=list(data.get("artifact_refs", [])),
        variables=dict(data.get("variables", {})),
        budget=dict(data.get("budget", {})),
        permissions=set(data.get("permissions", [])),
    )


def pipeline_spec_to_dict(spec: PipelineSpec) -> dict[str, Any]:
    raw = {
        "pipeline_id": spec.pipeline_id,
        "version": spec.version,
        "status": spec.status,
        "parent_version": spec.parent_version,
        "change_reason": spec.change_reason,
        "trigger": dict(spec.trigger),
        "steps": [
            {
                "id": step.id,
                "type": step.type,
                "config": dict(step.config),
                "inputs": dict(step.inputs),
                "when": dict(step.when) if step.when is not None else None,
                "next_step": step.next_step,
                "on_status": dict(step.on_status),
                "max_retries": step.max_retries,
            }
            for step in spec.steps
        ],
    }
    return json.loads(json.dumps(raw, default=_json_default))


def pipeline_spec_from_dict(data: dict[str, Any]) -> PipelineSpec:
    steps = tuple(
        PipelineStep(
            id=s["id"],
            type=s["type"],
            config=dict(s.get("config", {})),
            inputs=dict(s.get("inputs", {})),
            when=s.get("when"),
            next_step=s.get("next_step") or s.get("next"),
            on_status=dict(s.get("on_status", {})),
            max_retries=s.get("max_retries", 0),
        )
        for s in data["steps"]
    )
    return PipelineSpec(
        pipeline_id=data.get("pipeline_id") or data.get("id", ""),
        version=data["version"],
        status=data["status"],
        parent_version=data.get("parent_version"),
        change_reason=data.get("change_reason"),
        trigger=dict(data.get("trigger", {})),
        steps=steps,
    )


def user_question_to_dict(question: UserQuestion) -> dict[str, Any]:
    # Never persist plaintext resume token in snapshots
    return {
        "question": question.question,
        "reason": question.reason,
        "blocked_step": question.blocked_step,
        "required_fields": list(question.required_fields),
    }


def user_question_from_dict(data: dict[str, Any]) -> UserQuestion:
    return UserQuestion(
        question=data["question"],
        reason=data["reason"],
        blocked_step=data["blocked_step"],
        required_fields=tuple(data["required_fields"]),
        resume_token=None,
    )


def run_record_to_dict(run: RunRecord) -> dict[str, Any]:
    raw = {
        "run_id": run.run_id,
        "request_id": run.context.request.request_id,
        "trace_id": run.context.trace_id,
        "user_id": run.context.user_ref,
        "project_id": run.context.project_ref,
        "session_id": run.context.session_ref,
        "pipeline_id": run.spec.pipeline_id,
        "pipeline_version": run.spec.version,
        "status": run.status.value,
        "current_step_id": run.current_step_id,
        "context": execution_context_to_dict(run.context),
        "outputs": dict(run.outputs),
        "attempts": dict(run.attempts),
        "error": run.error,
        "revision": run.revision,
        "question": user_question_to_dict(run.question) if run.question is not None else None,
        "spec": pipeline_spec_to_dict(run.spec),
    }
    return json.loads(json.dumps(raw, default=_json_default))


def run_record_from_dict(data: dict[str, Any], spec: PipelineSpec | None = None) -> RunRecord:
    pipeline_spec = spec or (pipeline_spec_from_dict(data["spec"]) if "spec" in data else None)
    if pipeline_spec is None:
        raise ContractError(f"missing pipeline spec for run {data.get('run_id')}")
    context = execution_context_from_dict(data["context"])
    question = user_question_from_dict(data["question"]) if data.get("question") is not None else None
    return RunRecord(
        run_id=data["run_id"],
        spec=pipeline_spec,
        context=context,
        current_step_id=data["current_step_id"],
        outputs=dict(data.get("outputs", {})),
        attempts=dict(data.get("attempts", {})),
        status=RunStatus(data["status"]),
        question=question,
        error=data.get("error"),
        revision=int(data.get("revision", 0)),
    )


def specs_equal(spec_a: Any, spec_b: Any) -> bool:
    """Check if two pipeline specs have canonically identical definition (steps, triggers, metadata)."""
    if isinstance(spec_a, str):
        try:
            spec_a = json.loads(spec_a)
        except Exception:
            pass
    if isinstance(spec_b, str):
        try:
            spec_b = json.loads(spec_b)
        except Exception:
            pass
    obj_a = spec_a if isinstance(spec_a, PipelineSpec) else pipeline_spec_from_dict(spec_a)
    obj_b = spec_b if isinstance(spec_b, PipelineSpec) else pipeline_spec_from_dict(spec_b)
    return (
        obj_a.pipeline_id == obj_b.pipeline_id
        and obj_a.version == obj_b.version
        and obj_a.parent_version == obj_b.parent_version
        and obj_a.change_reason == obj_b.change_reason
        and obj_a.trigger == obj_b.trigger
        and obj_a.steps == obj_b.steps
    )


@runtime_checkable
class RunStateStore(Protocol):
    """Durable state storage abstraction for pipeline runs, questions, and specs."""

    async def save_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None) -> None:
        """Persist immutable pipeline spec. Idempotent if identical; raises RunConflictError on conflict."""
        ...

    async def get_pipeline(self, pipeline_id: str, version: int) -> PipelineSpec | None:
        """Retrieve immutable pipeline spec by pipeline_id and version."""
        ...

    async def create_run(self, run: RunRecord) -> None:
        """Insert a newly started run into the store."""
        ...

    async def update_run(self, run: RunRecord, expected_revision: int) -> int:
        """Update an existing run under optimistic concurrency control, returning new revision.
        Raises RunConflictError on revision mismatch."""
        ...

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Retrieve a run by run_id."""
        ...

    async def create_question(self, question: QuestionRecord) -> str:
        """Store a pending question with resume_token_hash. Plaintext token is never stored."""
        ...

    async def get_pending_question(self, token_hash: str) -> QuestionRecord | None:
        """Retrieve a pending question by resume_token_hash."""
        ...

    async def consume_question(self, token_hash: str, answer: dict[str, Any]) -> QuestionRecord | None:
        """Atomically mark a pending question as answered with answer.
        Returns the updated QuestionRecord if consumed, or None if already answered/invalid."""
        ...

    async def cancel_pending_questions(self, run_id: str) -> None:
        """Cancel any pending questions for the given run_id."""
        ...

    async def resume_run(self, token_hash: str, answer: dict[str, Any]) -> RunRecord:
        """Atomically validate and resume a run waiting for user input under a single lock or transaction.

        Under one in-memory lock or one PostgreSQL transaction, locks/validates the pending question
        and run, checks expiry/status/blocked_step/required fields, writes user_answers into ExecutionContext,
        clears run.question, changes run to RUNNING, increments revision, and marks the question answered.
        Returns the resumed RunRecord. Leaves both records unchanged on every failure.
        """
        ...


class InMemoryRunStateStore:
    """In-memory RunStateStore that stores deep JSON-compatible snapshots.

    Survives recreation of PipelineRuntime instances when the same store object is reused.
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._questions: dict[str, dict[str, Any]] = {}  # keyed by resume_token_hash
        self._specs: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def save_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None) -> None:
        async with self._lock:
            key = (spec.pipeline_id, spec.version)
            payload = raw_spec if raw_spec is not None else pipeline_spec_to_dict(spec)
            if key in self._specs:
                existing = self._specs[key]
                if not specs_equal(existing, payload):
                    raise RunConflictError(
                        f"pipeline spec {spec.identity} already exists with different definition"
                    )
                return
            self._specs[key] = payload

    async def publish_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None) -> None:
        async with self._lock:
            key = (spec.pipeline_id, spec.version)
            payload = raw_spec if raw_spec is not None else pipeline_spec_to_dict(spec)
            if key in self._specs:
                existing = self._specs[key]
                if not specs_equal(existing, payload):
                    raise RunConflictError(
                        f"pipeline spec {spec.identity} already exists with different definition"
                    )
            else:
                self._specs[key] = payload
            if spec.status == "active":
                for (p_id, ver), stored_spec in self._specs.items():
                    if p_id == spec.pipeline_id and ver != spec.version and stored_spec.get("status") == "active":
                        stored_spec["status"] = "retired"
                self._specs[key]["status"] = "active"

    async def get_pipeline(self, pipeline_id: str, version: int) -> PipelineSpec | None:
        async with self._lock:
            data = self._specs.get((pipeline_id, version))
            if data is None:
                return None
            return pipeline_spec_from_dict(data)

    async def create_run(self, run: RunRecord) -> None:
        async with self._lock:
            if run.run_id in self._runs:
                raise RunConflictError(f"run already exists: {run.run_id}")
            key = (run.spec.pipeline_id, run.spec.version)
            payload = pipeline_spec_to_dict(run.spec)
            if key in self._specs:
                if not specs_equal(self._specs[key], payload):
                    raise RunConflictError(
                        f"pipeline spec {run.spec.identity} already exists with different definition"
                    )
            else:
                self._specs[key] = payload
            snapshot = run_record_to_dict(run)
            self._runs[run.run_id] = snapshot

    async def update_run(self, run: RunRecord, expected_revision: int) -> int:
        async with self._lock:
            existing = self._runs.get(run.run_id)
            if existing is None:
                raise ContractError(f"run not found: {run.run_id}")
            current_revision = existing.get("revision", 0)
            if current_revision != expected_revision:
                raise RunConflictError(
                    f"run {run.run_id} revision conflict: expected {expected_revision}, got {current_revision}"
                )
            new_revision = expected_revision + 1
            run.revision = new_revision
            self._runs[run.run_id] = run_record_to_dict(run)
            return new_revision

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            snapshot = self._runs.get(run_id)
            if snapshot is None:
                return None
            spec_data = self._specs.get((snapshot["pipeline_id"], snapshot["pipeline_version"]))
            spec = pipeline_spec_from_dict(spec_data) if spec_data else None
            return run_record_from_dict(snapshot, spec=spec)

    async def create_question(self, question: QuestionRecord) -> str:
        async with self._lock:
            if question.resume_token_hash in self._questions:
                raise RunConflictError(f"question already exists for token hash: {question.resume_token_hash}")
            raw = {
                "question_id": question.question_id,
                "run_id": question.run_id,
                "blocked_step": question.blocked_step,
                "question": question.question,
                "reason": question.reason,
                "required_fields": list(question.required_fields),
                "resume_token_hash": question.resume_token_hash,
                "status": question.status,
                "answer": dict(question.answer) if question.answer is not None else None,
                "created_at": question.created_at.isoformat(),
                "answered_at": question.answered_at.isoformat() if question.answered_at is not None else None,
                "expires_at": question.expires_at.isoformat() if question.expires_at is not None else None,
            }
            self._questions[question.resume_token_hash] = json.loads(json.dumps(raw, default=_json_default))
            return question.question_id

    async def get_pending_question(self, token_hash: str) -> QuestionRecord | None:
        async with self._lock:
            data = self._questions.get(token_hash)
            if data is None:
                return None
            if data["status"] != "pending":
                return None
            expires_at = datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            if expires_at and expires_at <= utc_now():
                return None
            return QuestionRecord(
                question_id=data["question_id"],
                run_id=data["run_id"],
                blocked_step=data["blocked_step"],
                question=data["question"],
                reason=data["reason"],
                required_fields=tuple(data["required_fields"]),
                resume_token_hash=data["resume_token_hash"],
                status=data["status"],
                answer=dict(data["answer"]) if data.get("answer") is not None else None,
                created_at=datetime.fromisoformat(data["created_at"]),
                answered_at=datetime.fromisoformat(data["answered_at"]) if data.get("answered_at") else None,
                expires_at=expires_at,
            )

    async def consume_question(self, token_hash: str, answer: dict[str, Any]) -> QuestionRecord | None:
        async with self._lock:
            data = self._questions.get(token_hash)
            if data is None:
                return None
            if data["status"] != "pending":
                return None
            expires_at = datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            if expires_at and expires_at <= utc_now():
                return None
            now = utc_now()
            data["status"] = "answered"
            data["answer"] = json.loads(json.dumps(dict(answer), default=_json_default))
            data["answered_at"] = now.isoformat()
            return QuestionRecord(
                question_id=data["question_id"],
                run_id=data["run_id"],
                blocked_step=data["blocked_step"],
                question=data["question"],
                reason=data["reason"],
                required_fields=tuple(data["required_fields"]),
                resume_token_hash=data["resume_token_hash"],
                status=data["status"],
                answer=dict(data["answer"]),
                created_at=datetime.fromisoformat(data["created_at"]),
                answered_at=now,
                expires_at=expires_at,
            )

    async def cancel_pending_questions(self, run_id: str) -> None:
        async with self._lock:
            for data in self._questions.values():
                if data["run_id"] == run_id and data["status"] == "pending":
                    data["status"] = "cancelled"

    async def resume_run(self, token_hash: str, answer: dict[str, Any]) -> RunRecord:
        if not isinstance(answer, dict):
            raise ContractError("answer must be a dictionary")
        async with self._lock:
            q_data = self._questions.get(token_hash)
            if q_data is None:
                raise ContractError("invalid or already-used resume token")
            if q_data.get("status") != "pending":
                raise ContractError("invalid or already-used resume token")
            expires_at = datetime.fromisoformat(q_data["expires_at"]) if q_data.get("expires_at") else None
            if expires_at and expires_at <= utc_now():
                raise ContractError("invalid or already-used resume token")

            required_fields = q_data.get("required_fields", [])
            missing = [f for f in required_fields if f not in answer]
            if missing:
                raise ContractError(f"missing required answer fields: {', '.join(missing)}")

            run_id = q_data["run_id"]
            run_snapshot = self._runs.get(run_id)
            if run_snapshot is None:
                raise ContractError(f"run not found for question: {run_id}")

            if run_snapshot["status"] != RunStatus.NEED_USER.value:
                raise ContractError(f"run is not waiting for user input: {run_snapshot['status']}")

            if run_snapshot["current_step_id"] != q_data["blocked_step"]:
                raise ContractError(
                    f"resume step mismatch: run is at {run_snapshot['current_step_id']}, question blocked {q_data['blocked_step']}"
                )

            spec_data = self._specs.get((run_snapshot["pipeline_id"], run_snapshot["pipeline_version"]))
            spec = pipeline_spec_from_dict(spec_data) if spec_data else None
            if spec is None or spec.version <= 0:
                raise ContractError("invalid pipeline spec version")

            now = utc_now()
            run_record = run_record_from_dict(run_snapshot, spec=spec)
            answers = run_record.context.variables.setdefault("user_answers", {})
            answers[run_record.current_step_id] = dict(answer)
            run_record.status = RunStatus.RUNNING
            run_record.question = None
            run_record.revision += 1

            updated_run_snapshot = run_record_to_dict(run_record)

            updated_q_data = dict(q_data)
            updated_q_data["status"] = "answered"
            updated_q_data["answer"] = json.loads(json.dumps(dict(answer), default=_json_default))
            updated_q_data["answered_at"] = now.isoformat()

            # Atomically update both records under lock
            self._questions[token_hash] = updated_q_data
            self._runs[run_id] = updated_run_snapshot

            return run_record

    atomic_resume = resume_run

