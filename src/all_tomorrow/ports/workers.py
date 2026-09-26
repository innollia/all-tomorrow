from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from all_tomorrow.domain.errors import CanonicalError


@dataclass(frozen=True, slots=True)
class WorkerDescriptor:
    worker_id: str
    version: str
    capabilities: frozenset[str]
    supported_artifact_types: frozenset[str] = frozenset()
    authority_scope: str = "default"
    side_effect_capabilities: frozenset[str] = frozenset()
    cancellation_semantics: str = "cooperative"
    timeout_seconds: float = 300.0
    max_output_bytes: int = 10_000_000
    health_status: str = "healthy"
    adapter_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.worker_id or not self.worker_id.strip():
            raise ValueError("WorkerDescriptor.worker_id must be non-empty")
        if not self.version or not self.version.strip():
            raise ValueError("WorkerDescriptor.version must be non-empty")
        if not isinstance(self.capabilities, frozenset):
            raise ValueError("WorkerDescriptor.capabilities must be a frozenset")


@dataclass(frozen=True, slots=True)
class WorkerExecutionRequest:
    worker_id: str
    request_id: str
    trace_id: str
    capabilities: frozenset[str]
    payload: dict[str, Any]
    project_id: str | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class WorkerExecutionResult:
    worker_id: str
    request_id: str
    trace_id: str
    success: bool
    payload: dict[str, Any] | None = None
    duration_ms: int = 0
    error: CanonicalError | None = None


class WorkerExecutionPort(Protocol):
    """Port interface for executing workers/external worker processes."""

    async def execute_worker(self, request: WorkerExecutionRequest) -> WorkerExecutionResult:
        ...

    async def is_available(self) -> bool:
        ...
