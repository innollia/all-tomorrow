from __future__ import annotations

from typing import Iterable

from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.ports.tools import ToolDescriptor
from all_tomorrow.ports.workers import WorkerDescriptor


class ToolRegistry:
    """Canonical registry for tools and tool descriptors.

    S0-00B5-01: Decoupled from transport gateways (LiteLLM / FastMCP).
    S0-00B5-04: Generic capability-based lookup with zero hardcoded tool name branching.
    """

    def __init__(self, initial_tools: Iterable[ToolDescriptor] = ()) -> None:
        self._tools: dict[str, ToolDescriptor] = {}
        for tool in initial_tools:
            self.register(tool)

    def register(self, tool: ToolDescriptor) -> None:
        if tool.tool_id in self._tools:
            existing = self._tools[tool.tool_id]
            if existing.version == tool.version:
                raise InvariantViolationError(
                    f"Tool '{tool.tool_id}' version '{tool.version}' is already registered"
                )
        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> ToolDescriptor | None:
        return self._tools.get(tool_id)

    def find_by_capabilities(self, required_capabilities: frozenset[str]) -> list[ToolDescriptor]:
        return [
            tool
            for tool in self._tools.values()
            if required_capabilities <= tool.capabilities
        ]

    def all_tools(self) -> list[ToolDescriptor]:
        return list(self._tools.values())


class WorkerRegistry:
    """Canonical registry for workers and worker descriptors.

    S0-00B5-04: Generic capability and health selection with zero core name branching.
    """

    def __init__(self, initial_workers: Iterable[WorkerDescriptor] = ()) -> None:
        self._workers: dict[str, WorkerDescriptor] = {}
        for worker in initial_workers:
            self.register(worker)

    def register(self, worker: WorkerDescriptor) -> None:
        if worker.worker_id in self._workers:
            existing = self._workers[worker.worker_id]
            if existing.version == worker.version:
                raise InvariantViolationError(
                    f"Worker '{worker.worker_id}' version '{worker.version}' is already registered"
                )
        self._workers[worker.worker_id] = worker

    def get(self, worker_id: str) -> WorkerDescriptor | None:
        return self._workers.get(worker_id)

    def find_by_capabilities(
        self,
        required_capabilities: frozenset[str],
        only_healthy: bool = True,
    ) -> list[WorkerDescriptor]:
        matches: list[WorkerDescriptor] = []
        for worker in self._workers.values():
            if required_capabilities <= worker.capabilities:
                if only_healthy and worker.health_status != "healthy":
                    continue
                matches.append(worker)
        return matches

    def all_workers(self) -> list[WorkerDescriptor]:
        return list(self._workers.values())
