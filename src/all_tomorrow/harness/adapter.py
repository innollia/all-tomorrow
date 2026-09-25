"""Durable execution adapter protocol and baseline in-memory reference adapter.

The harness does NOT import or depend on DBOS, Restate, Temporal, etc.
Any candidate engine is tested by providing a DurableAdapter implementation.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Set

from .agent import ModelDecision, create_deterministic_agent
from .fixtures import SideEffectFixtureStore
from .tools import mutation_stub_tool, read_inventory_tool
from .types import (
    BackendConnectionError,
    ExecutionIdentity,
    FailPoint,
    HarnessInput,
    HarnessOutput,
    KillException,
    TraceContext,
)


class DurableAdapter(ABC):
    """Abstract interface that all durable execution candidates must implement."""

    @abstractmethod
    async def start_or_resume(
        self,
        identity: ExecutionIdentity,
        harness_input: HarnessInput,
        trace_context: Optional[TraceContext],
        store: SideEffectFixtureStore,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
    ) -> HarnessOutput:
        """Execute or resume an execution run until completion or failure."""
        raise NotImplementedError

    @abstractmethod
    async def send_signal(
        self,
        identity: ExecutionIdentity,
        signal_name: str,
        payload: Any,
    ) -> None:
        """Send an external signal to a waiting execution run."""
        raise NotImplementedError

    @abstractmethod
    async def cancel(
        self,
        identity: ExecutionIdentity,
    ) -> None:
        """Cancel an in-flight execution run."""
        raise NotImplementedError

    @abstractmethod
    async def get_persisted_state(
        self,
        identity: ExecutionIdentity,
    ) -> Dict[str, Any]:
        """Retrieve persisted execution state for verification."""
        raise NotImplementedError

    @abstractmethod
    def simulate_backend_disconnect(self, transient_failures: int = 1) -> None:
        """Inject transient backend disconnection errors for scenario D09."""
        raise NotImplementedError

    @abstractmethod
    def export_journal_state(self) -> Dict[str, Any]:
        """Export raw persisted journals to verify application upgrade in D10."""
        raise NotImplementedError

    @abstractmethod
    def import_journal_state(self, state: Dict[str, Any]) -> None:
        """Import persisted journals into an upgraded adapter instance for D10."""
        raise NotImplementedError


class BaselineMemoryAdapter(DurableAdapter):
    """Reference implementation of a step-journaling durable adapter in memory.

    Provides deterministic walking-skeleton execution, simulating step journaling,
    PydanticAI agent integration via TestModel, recovery replay, external signals,
    and timers without depending on third-party engines.
    """

    def __init__(self, candidate_name: str = "baseline-memory", version: str = "1.0.0"):
        self.candidate_name = candidate_name
        self.version = version
        # Simulated durable storage: keyed by (work_id, run_id)
        self._journal: Dict[str, Dict[str, Any]] = {}
        # Signal queues: keyed by (work_id, run_id, signal_name)
        self._signals: Dict[str, asyncio.Queue] = {}
        # Cancelled runs
        self._cancelled: Set[str] = set()
        # Simulated transient connection failures for D09
        self._transient_failures_remaining: int = 0

    def simulate_backend_disconnect(self, transient_failures: int = 1) -> None:
        self._transient_failures_remaining = transient_failures

    def export_journal_state(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in self._journal.items()}

    def import_journal_state(self, state: Dict[str, Any]) -> None:
        self._journal = {k: dict(v) for k, v in state.items()}

    def _key(self, identity: ExecutionIdentity) -> str:
        return f"{identity.work_id}:{identity.run_id}"

    async def start_or_resume(
        self,
        identity: ExecutionIdentity,
        harness_input: HarnessInput,
        trace_context: Optional[TraceContext],
        store: SideEffectFixtureStore,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
    ) -> HarnessOutput:
        # Check simulated transient backend disconnect (D09)
        if self._transient_failures_remaining > 0:
            self._transient_failures_remaining -= 1
            raise BackendConnectionError("Simulated transient backend disconnect. Connection refused.")

        key = self._key(identity)
        if key in self._cancelled:
            raise RuntimeError(f"Run {key} has been cancelled.")

        # Retrieve or initialize durable run journal
        # D12 Requirement: The original correlation_id and trace context must be
        # stored in the journal and preserved across any subsequent recovery runs.
        is_new_run = key not in self._journal
        if is_new_run:
            orig_trace = trace_context.model_dump() if trace_context else {}
            state = {
                "identity": identity.model_dump(),
                "origin_trace_context": orig_trace,
                "origin_correlation_id": orig_trace.get("correlation_id", "unknown-corr-id"),
                "completed_steps": {},
                "model_decision": None,
                "read_item_data": None,
                "mutation_committed": False,
                "mutation_value": None,
                "signal_payload": None,
                "timer_elapsed": 0.0,
            }
            self._journal[key] = state
        else:
            state = self._journal[key]

        # Step 1: Read-only tool execution
        if "read_tool" not in state["completed_steps"]:
            read_data = read_inventory_tool(harness_input.query_item_id)
            state["read_item_data"] = read_data
            state["completed_steps"]["read_tool"] = True

        # Step 2: Deterministic PydanticAI agent execution & model result persist point
        if "model_persist" not in state["completed_steps"]:
            if harness_input.injected_fail_point == FailPoint.BEFORE_MODEL_RESULT_PERSIST and kill_hook:
                kill_hook(FailPoint.BEFORE_MODEL_RESULT_PERSIST)

            # Execute real PydanticAI deterministic agent
            agent = create_deterministic_agent()
            agent_result = await agent.run(
                f"Evaluate task '{harness_input.task_name}' for item '{harness_input.query_item_id}'"
            )
            decision: ModelDecision = agent_result.output

            # Persist model result into the durable journal
            state["model_decision"] = decision.model_dump()
            state["completed_steps"]["model_persist"] = True

            if harness_input.injected_fail_point == FailPoint.AFTER_MODEL_RESULT_PERSIST and kill_hook:
                kill_hook(FailPoint.AFTER_MODEL_RESULT_PERSIST)

        # Step 3: Mutation side-effect tool
        if "mutation_tool" not in state["completed_steps"]:
            record = mutation_stub_tool(
                store=store,
                idempotency_key=harness_input.mutation_key,
                value=harness_input.mutation_value,
                kill_hook=kill_hook,
                fail_point=harness_input.injected_fail_point,
            )
            state["mutation_committed"] = record.applied_at_least_once
            state["mutation_value"] = record.committed_value
            state["completed_steps"]["mutation_tool"] = True

        # Step 4: Durable timer / delay
        if harness_input.timer_delay_seconds > 0 and "timer" not in state["completed_steps"]:
            if harness_input.injected_fail_point == FailPoint.DURING_TIMER_DELAY and kill_hook:
                kill_hook(FailPoint.DURING_TIMER_DELAY)
            await asyncio.sleep(harness_input.timer_delay_seconds)
            state["timer_elapsed"] = harness_input.timer_delay_seconds
            state["completed_steps"]["timer"] = True

        # Step 5: Durable wait for signal
        if harness_input.wait_for_signal_name and "wait_signal" not in state["completed_steps"]:
            if harness_input.injected_fail_point == FailPoint.DURING_WAIT_SIGNAL and kill_hook:
                kill_hook(FailPoint.DURING_WAIT_SIGNAL)

            sig_key = f"{key}:{harness_input.wait_for_signal_name}"
            q = self._signals.setdefault(sig_key, asyncio.Queue())
            payload = await q.get()
            state["signal_payload"] = payload
            state["completed_steps"]["wait_signal"] = True

        # Recover model decision object if present in journal
        recovered_decision = (
            ModelDecision(**state["model_decision"]) if state.get("model_decision") else None
        )

        # D12: Always guarantee original correlation_id from persistent journal
        preserved_correlation_id = state.get("origin_correlation_id", "unknown-corr-id")

        return HarnessOutput(
            status="completed",
            task_name=harness_input.task_name,
            read_item_data=state["read_item_data"] or {},
            model_decision=recovered_decision,
            mutation_committed=state["mutation_committed"],
            mutation_value=state["mutation_value"],
            signal_received_payload=state["signal_payload"],
            timer_elapsed_seconds=state["timer_elapsed"],
            correlation_id=preserved_correlation_id,
            execution_identity=identity,
        )

    async def send_signal(
        self,
        identity: ExecutionIdentity,
        signal_name: str,
        payload: Any,
    ) -> None:
        key = self._key(identity)
        sig_key = f"{key}:{signal_name}"
        q = self._signals.setdefault(sig_key, asyncio.Queue())
        await q.put(payload)

    async def cancel(self, identity: ExecutionIdentity) -> None:
        key = self._key(identity)
        self._cancelled.add(key)

    async def get_persisted_state(self, identity: ExecutionIdentity) -> Dict[str, Any]:
        key = self._key(identity)
        return self._journal.get(key, {})
