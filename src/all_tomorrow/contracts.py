from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class ContractError(ValueError):
    """Raised when data violates a public control-plane contract."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4()}"


def require_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a non-empty string")
    return value.strip()


class NodeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    WAITING = "WAITING"
    NEED_USER = "NEED_USER"
    CANCELLED = "CANCELLED"


class Actor(StrEnum):
    USER = "user"
    EDGE_AGENT = "edge_agent"
    ORCHESTRATOR = "orchestrator"
    AGENT = "agent"
    TOOL = "tool"
    SCHEDULER = "scheduler"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    message: str
    source: str
    request_id: str = field(default_factory=lambda: new_id("req"))
    received_at: datetime = field(default_factory=utc_now)
    attachments: tuple[str, ...] = ()
    session_ref: str | None = None
    edge_analysis: dict[str, Any] = field(default_factory=dict)
    candidate_project_id: str | None = None
    central_reason: str | None = None

    def __post_init__(self) -> None:
        require_text(self.message, "request.message")
        require_text(self.source, "request.source")
        require_text(self.request_id, "request.request_id")


@dataclass(frozen=True, slots=True)
class UserQuestion:
    question: str
    reason: str
    blocked_step: str
    required_fields: tuple[str, ...]
    resume_token: str | None = None

    def __post_init__(self) -> None:
        require_text(self.question, "user_question.question")
        require_text(self.reason, "user_question.reason")
        require_text(self.blocked_step, "user_question.blocked_step")
        if not self.required_fields:
            raise ContractError("user_question.required_fields must not be empty")
        for index, item in enumerate(self.required_fields):
            require_text(item, f"user_question.required_fields[{index}]")

    def with_resume_token(self, token: str) -> UserQuestion:
        return UserQuestion(
            question=self.question,
            reason=self.reason,
            blocked_step=self.blocked_step,
            required_fields=self.required_fields,
            resume_token=token,
        )


@dataclass(frozen=True, slots=True)
class NodeResult:
    status: NodeStatus
    output: Any = None
    artifacts: tuple[str, ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    next_hint: str | None = None
    user_question: UserQuestion | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status is NodeStatus.NEED_USER and self.user_question is None:
            raise ContractError("NEED_USER result requires user_question")
        if self.status is not NodeStatus.NEED_USER and self.user_question is not None:
            raise ContractError("user_question is only valid for NEED_USER")
        if self.status is NodeStatus.FAILED and not self.error:
            raise ContractError("FAILED result requires error")


@dataclass(frozen=True, slots=True)
class PipelineStep:
    id: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    when: dict[str, Any] | None = None
    next_step: str | None = None
    on_status: dict[str, str] = field(default_factory=dict)
    max_retries: int = 0

    def __post_init__(self) -> None:
        require_text(self.id, "pipeline.step.id")
        require_text(self.type, f"pipeline.step[{self.id}].type")
        if self.max_retries < 0:
            raise ContractError(f"pipeline.step[{self.id}].max_retries must be >= 0")


@dataclass(frozen=True, slots=True)
class PipelineSpec:
    pipeline_id: str
    version: int
    status: str
    steps: tuple[PipelineStep, ...]
    parent_version: int | None = None
    change_reason: str | None = None
    trigger: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.pipeline_id, "pipeline.pipeline_id")
        if self.version < 1:
            raise ContractError("pipeline.version must be >= 1")
        if self.status not in {"draft", "active", "retired"}:
            raise ContractError("pipeline.status must be draft, active, or retired")
        if not self.steps:
            raise ContractError("pipeline.steps must not be empty")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ContractError("pipeline step ids must be unique")
        known = set(ids)
        for step in self.steps:
            targets = ([step.next_step] if step.next_step else []) + list(step.on_status.values())
            for target in targets:
                if target not in known:
                    raise ContractError(f"pipeline.step[{step.id}] targets unknown step {target!r}")

    @property
    def identity(self) -> str:
        return f"{self.pipeline_id}@{self.version}"


@dataclass(slots=True)
class ExecutionContext:
    request: RequestEnvelope
    user_ref: str
    trace_id: str = field(default_factory=lambda: new_id("trace"))
    project_ref: str | None = None
    session_ref: str | None = None
    memory_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    permissions: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        require_text(self.user_ref, "execution_context.user_ref")
        require_text(self.trace_id, "execution_context.trace_id")


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    actor: Actor
    trace_id: str
    event_id: str = field(default_factory=lambda: new_id("evt"))
    occurred_at: datetime = field(default_factory=utc_now)
    user_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    parent_event_id: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.type, "event.type")
        require_text(self.trace_id, "event.trace_id")


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    name: str
    owner: str
    source_refs: tuple[str, ...] = ()
    aliases: frozenset[str] = frozenset()
    maintainer_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    description: str


@dataclass(frozen=True, slots=True)
class Worker:
    worker_id: str
    capabilities: frozenset[str]
    status: str = "unknown"
    latency_ms: int | None = None
    cost_score: float = 0.0
    evaluation_score: float = 0.0
    privacy_tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Tool:
    tool_id: str
    provider: str
    capabilities: frozenset[str]
    risk: str
    permissions: frozenset[str] = frozenset()
    status: str = "unknown"
    latency_ms: int | None = None
