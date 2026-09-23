from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NewType
from uuid import uuid4

GoalId = NewType("GoalId", str)
WorkId = NewType("WorkId", str)
RunId = NewType("RunId", str)
ProjectId = NewType("ProjectId", str)
EventId = NewType("EventId", str)
OutcomeId = NewType("OutcomeId", str)
QuestionId = NewType("QuestionId", str)
ArtifactId = NewType("ArtifactId", str)
TriggerId = NewType("TriggerId", str)
DeliveryId = NewType("DeliveryId", str)
RequestId = NewType("RequestId", str)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4()}"


def new_goal_id() -> GoalId:
    return GoalId(new_id("goal"))


def new_work_id() -> WorkId:
    return WorkId(new_id("work"))


def new_run_id() -> RunId:
    return RunId(new_id("run"))


def new_project_id() -> ProjectId:
    return ProjectId(new_id("proj"))


def new_event_id() -> EventId:
    return EventId(new_id("evt"))


def new_outcome_id() -> OutcomeId:
    return OutcomeId(new_id("outc"))


def new_question_id() -> QuestionId:
    return QuestionId(new_id("q"))


def new_artifact_id() -> ArtifactId:
    return ArtifactId(new_id("art"))


def new_trigger_id() -> TriggerId:
    return TriggerId(new_id("trig"))


def new_delivery_id() -> DeliveryId:
    return DeliveryId(new_id("dlv"))


def new_request_id() -> RequestId:
    return RequestId(new_id("req"))


@dataclass(frozen=True, slots=True)
class ExecutionRef:
    """External durable execution reference owned strictly by a Run.

    Work records must never store an ExecutionRef directly.
    """
    backend: str
    execution_id: str
    execution_version: int = 1
    attached_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend or not self.backend.strip():
            raise ValueError("ExecutionRef.backend must be non-empty")
        if not self.execution_id or not self.execution_id.strip():
            raise ValueError("ExecutionRef.execution_id must be non-empty")
        if self.execution_version < 1:
            raise ValueError("ExecutionRef.execution_version must be >= 1")
