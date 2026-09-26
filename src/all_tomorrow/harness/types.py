"""Type definitions and result schemas for 00A-1 Common Harness.

This module is completely decoupled from any specific durable execution engine
(e.g., DBOS, Restate, Temporal).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class ModelDecision(BaseModel):
    """Structured decision output produced by the harness PydanticAI agent."""

    task_summary: str = Field(..., description="Summary of the evaluated task")
    stock_confirmed: int = Field(default=0, description="Stock verified from tool call")
    should_commit_mutation: bool = Field(default=True, description="Decision to commit external side effect")
    confidence_score: float = Field(default=1.0, description="Deterministic confidence score")
    planned_mutation_value: str = Field(..., description="Target value to persist")


class FailPoint(str, Enum):
    """Deterministic failure injection points for walking skeleton tests."""

    NONE = "none"
    BEFORE_MODEL_RESULT_PERSIST = "before_model_result_persist"
    AFTER_MODEL_RESULT_PERSIST = "after_model_result_persist"
    AFTER_MUTATION_SIDE_EFFECT = "after_mutation_side_effect"
    DURING_WAIT_SIGNAL = "during_wait_signal"
    DURING_TIMER_DELAY = "during_timer_delay"
    ON_BACKEND_DISCONNECT = "on_backend_disconnect"


class ScenarioId(str, Enum):
    """Canonical durable execution test scenarios D01-D12."""

    D01_NORMAL_COMPLETION = "D01"
    D02_KILL_BEFORE_MODEL_RESULT_PERSIST = "D02"
    D03_KILL_AFTER_MODEL_RESULT_PERSIST = "D03"
    D04_KILL_IMMEDIATELY_AFTER_SIDE_EFFECT = "D04"
    D05_DUPLICATE_START_WITH_SAME_IDENTITY = "D05"
    D06_USER_WAIT_RESTART_SIGNAL_RESUME = "D06"
    D07_LONG_TIMER_RESTART_RESUME = "D07"
    D08_CANCEL = "D08"
    D09_BACKEND_TEMP_UNAVAILABLE_RECONNECT = "D09"
    D10_OLD_IN_FLIGHT_EXECUTION_UPGRADE = "D10"
    D11_TWO_LOGICAL_RUNS_FOR_ONE_WORK = "D11"
    D12_OTEL_CORRELATION_SURVIVES_RECOVERY = "D12"


class ExecutionIdentity(BaseModel):
    """Deterministic identity tracking for execution runs."""

    work_id: str = Field(..., description="Semantic Work identifier in All Tomorrow")
    run_id: str = Field(..., description="Unique logical run identifier")
    attempt: int = Field(default=1, description="Current execution attempt number")


class TraceContext(BaseModel):
    """OpenTelemetry correlation context surviving recovery across processes."""

    trace_id: str = Field(..., description="OTel trace identifier")
    span_id: str = Field(..., description="OTel root/parent span identifier")
    correlation_id: str = Field(..., description="All Tomorrow cross-process correlation token")


class HarnessInput(BaseModel):
    """Typed input for the walking skeleton harness."""

    task_name: str
    query_item_id: str = "item-default"
    mutation_key: str = "key-default"
    mutation_value: str = "value-default"
    timer_delay_seconds: float = 0.0
    wait_for_signal_name: Optional[str] = None
    injected_fail_point: FailPoint = FailPoint.NONE
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HarnessOutput(BaseModel):
    """Typed output from the walking skeleton harness."""

    status: str = "completed"
    task_name: str
    read_item_data: Dict[str, Any] = Field(default_factory=dict)
    model_decision: Optional[ModelDecision] = None
    mutation_committed: bool = False
    mutation_value: Optional[str] = None
    signal_received_payload: Optional[Any] = None
    timer_elapsed_seconds: float = 0.0
    correlation_id: str
    execution_identity: ExecutionIdentity


class ScenarioResult(BaseModel):
    """Standardized result schema for all scenario evaluations (00A-1 specification)."""

    scenario_id: str
    candidate: str
    version: str
    passed: bool
    manual_steps: List[str] = Field(default_factory=list)
    # Unknown measurements remain unknown instead of pretending to be zero/one.
    custom_glue_loc: Optional[int] = None
    adapter_loc: Optional[int] = None
    processes_required: Optional[int] = None
    persistent_state_systems: Optional[List[str]] = None
    recovery_notes: str = ""
    persisted_payload_notes: str = ""
    trace_notes: str = ""


class KillException(RuntimeError):
    """Explicit simulated process/worker termination hook."""

    def __init__(self, point: FailPoint, message: str = ""):
        super().__init__(f"Simulated kill at point: {point.value}. {message}".strip())
        self.point = point


class BackendConnectionError(RuntimeError):
    """Simulated transient backend storage / cluster disconnection error for D09."""

    def __init__(self, message: str = "Database / durable backend temporarily unavailable"):
        super().__init__(message)
