from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.contracts import (
    ContractError,
    Tool,
    Worker,
    WorkerAdapter,
    WorkerRequest,
    WorkerResult,
)


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    required_capabilities: frozenset[str]
    privacy_tags: frozenset[str] = frozenset()
    maximum_risk: str = "high"


_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class CapabilityRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._tools: dict[str, Tool] = {}

    def register_worker(self, worker: Worker) -> None:
        if worker.worker_id in self._workers:
            raise ContractError(f"worker already registered: {worker.worker_id}")
        self._workers[worker.worker_id] = worker

    def get_worker(self, worker_id: str) -> Worker | None:
        return self._workers.get(worker_id)

    def list_workers(self) -> tuple[Worker, ...]:
        return tuple(self._workers.values())

    def register_tool(self, tool: Tool) -> None:
        if tool.tool_id in self._tools:
            raise ContractError(f"tool already registered: {tool.tool_id}")
        if tool.risk not in _RISK_ORDER:
            raise ContractError(f"unknown tool risk: {tool.risk}")
        self._tools[tool.tool_id] = tool

    def select_worker(self, request: SelectionRequest) -> Worker | None:
        candidates = [
            worker
            for worker in self._workers.values()
            if worker.status == "available"
            and request.required_capabilities <= worker.capabilities
            and request.privacy_tags <= worker.privacy_tags
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda worker: (
                -worker.evaluation_score,
                worker.cost_score,
                worker.latency_ms if worker.latency_ms is not None else 10**12,
                worker.worker_id,
            ),
        )

    def select_tools(self, request: SelectionRequest) -> tuple[Tool, ...]:
        if request.maximum_risk not in _RISK_ORDER:
            raise ContractError(f"unknown maximum risk: {request.maximum_risk}")
        maximum = _RISK_ORDER[request.maximum_risk]
        candidates = [
            tool
            for tool in self._tools.values()
            if tool.status == "available"
            and request.required_capabilities <= tool.capabilities
            and _RISK_ORDER[tool.risk] <= maximum
        ]
        return tuple(sorted(candidates, key=lambda tool: (tool.latency_ms or 10**12, tool.tool_id)))


class WorkerService:
    """Runtime service binding CapabilityRegistry metadata with executable WorkerAdapters."""

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self._registry: CapabilityRegistry = registry if registry is not None else CapabilityRegistry()
        self._adapters: dict[str, WorkerAdapter] = {}

    @property
    def registry(self) -> CapabilityRegistry:
        return self._registry

    def register_worker(self, worker: Worker, adapter: WorkerAdapter) -> None:
        if worker.worker_id != adapter.worker_id:
            raise ContractError(
                f"worker_id mismatch: metadata {worker.worker_id!r} != adapter {adapter.worker_id!r}"
            )
        if worker.capabilities != adapter.capabilities:
            raise ContractError(
                f"capabilities mismatch for {worker.worker_id!r}: "
                f"metadata {sorted(worker.capabilities)} != adapter {sorted(adapter.capabilities)}"
            )
        if worker.worker_id in self._adapters or self._registry.get_worker(worker.worker_id) is not None:
            raise ContractError(f"worker already registered: {worker.worker_id}")

        self._registry.register_worker(worker)
        self._adapters[worker.worker_id] = adapter

    register = register_worker

    def get_worker(self, worker_id: str) -> Worker | None:
        return self._registry.get_worker(worker_id)

    def list_workers(self) -> tuple[Worker, ...]:
        return self._registry.list_workers()

    def get_adapter(self, worker_id: str) -> WorkerAdapter:
        adapter = self._adapters.get(worker_id)
        if adapter is None:
            raise ContractError(f"no bound adapter for worker: {worker_id}")
        return adapter

    def has_worker(self, worker_id: str) -> bool:
        return worker_id in self._adapters

    def select_worker(self, request: SelectionRequest) -> Worker | None:
        return self._registry.select_worker(request)

    async def execute(self, worker_id: str, request: WorkerRequest) -> WorkerResult:
        adapter = self.get_adapter(worker_id)
        return await adapter.execute(request)

    def register_tool(self, tool: Tool) -> None:
        self._registry.register_tool(tool)

    def select_tools(self, request: SelectionRequest) -> tuple[Tool, ...]:
        return self._registry.select_tools(request)

