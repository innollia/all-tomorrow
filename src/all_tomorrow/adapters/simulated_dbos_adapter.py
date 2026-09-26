"""In-memory sketch of a DBOS-shaped adapter.

This module never calls DBOS and cannot prove DBOS durability or recovery.
It is kept only to exercise the common harness interface during the spike.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional, Set

from all_tomorrow.harness.adapter import DurableAdapter
from all_tomorrow.harness.agent import create_deterministic_agent
from all_tomorrow.harness.fixtures import SideEffectFixtureStore
from all_tomorrow.harness.tools import default_kill_hook, mutation_stub_tool, read_inventory_tool
from all_tomorrow.harness.types import (
    BackendConnectionError,
    ExecutionIdentity,
    FailPoint,
    HarnessInput,
    HarnessOutput,
    KillException,
    ModelDecision,
    TraceContext,
)


class SimulatedDBOSAdapter(DurableAdapter):
    """In-memory simulation; never use as a production durable adapter."""

    def __init__(
        self,
        candidate_name: str = "dbos-simulation",
        version: str = "simulation",
        use_sqlite: bool = True,
    ):
        self.candidate_name = candidate_name
        self.version = version
        self.use_sqlite = use_sqlite

        # Internal state/journal cache for in-memory / test simulation
        self._journal: Dict[str, Dict[str, Any]] = {}
        self._signals: Dict[str, asyncio.Queue] = {}
        self._cancelled: Set[str] = set()
        self._transient_failures_remaining: int = 0

    def simulate_backend_disconnect(self, transient_failures: int = 1) -> None:
        self._transient_failures_remaining = transient_failures

    def export_journal_state(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in self._journal.items()}

    def import_journal_state(self, state: Dict[str, Any]) -> None:
        self._journal = {k: dict(v) for k, v in state.items()}

    def _workflow_id(self, identity: ExecutionIdentity) -> str:
        """Map All Tomorrow ExecutionIdentity deterministically to DBOS workflow ID."""
        return f"{identity.work_id}:{identity.run_id}"

    async def start_or_resume(
        self,
        identity: ExecutionIdentity,
        harness_input: HarnessInput,
        trace_context: Optional[TraceContext],
        store: SideEffectFixtureStore,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
    ) -> HarnessOutput:
        # In-memory disconnect hook; no DBOS connection is touched.
        if self._transient_failures_remaining > 0:
            self._transient_failures_remaining -= 1
            raise BackendConnectionError("DBOS cluster/database connection temporarily unavailable.")

        w_id = self._workflow_id(identity)

        if w_id in self._cancelled:
            raise RuntimeError(f"DBOS workflow '{w_id}' was cancelled.")

        # Create an in-memory journal entry.
        is_new = w_id not in self._journal
        if is_new:
            orig_trace = trace_context.model_dump() if trace_context else {}
            state = {
                "workflow_id": w_id,
                "identity": identity.model_dump(),
                "origin_trace_context": orig_trace,
                "origin_correlation_id": orig_trace.get("correlation_id", "unknown-corr-id"),
                "steps": {},
                "model_decision": None,
                "read_item_data": None,
                "mutation_committed": False,
                "mutation_value": None,
                "signal_payload": None,
                "timer_elapsed": 0.0,
            }
            self._journal[w_id] = state
        else:
            state = self._journal[w_id]

        # Step 1: Read inventory tool.
        if "read_tool" not in state["steps"]:
            read_data = read_inventory_tool(harness_input.query_item_id)
            state["read_item_data"] = read_data
            state["steps"]["read_tool"] = True

        # Step 2: Deterministic PydanticAI agent and in-memory model result.
        if "model_persist" not in state["steps"]:
            if harness_input.injected_fail_point == FailPoint.BEFORE_MODEL_RESULT_PERSIST and kill_hook:
                kill_hook(FailPoint.BEFORE_MODEL_RESULT_PERSIST)

            agent = create_deterministic_agent()
            agent_result = await agent.run(
                f"DBOS evaluation for task '{harness_input.task_name}' on item '{harness_input.query_item_id}'"
            )
            decision: ModelDecision = agent_result.output

            state["model_decision"] = decision.model_dump()
            state["steps"]["model_persist"] = True

            if harness_input.injected_fail_point == FailPoint.AFTER_MODEL_RESULT_PERSIST and kill_hook:
                kill_hook(FailPoint.AFTER_MODEL_RESULT_PERSIST)

        # Step 3: Mutation side-effect tool with external idempotency seam.
        if "mutation_tool" not in state["steps"]:
            record = mutation_stub_tool(
                store=store,
                idempotency_key=harness_input.mutation_key,
                value=harness_input.mutation_value,
                kill_hook=kill_hook,
                fail_point=harness_input.injected_fail_point,
            )
            state["mutation_committed"] = record.applied_at_least_once
            state["mutation_value"] = record.committed_value
            state["steps"]["mutation_tool"] = True

        # Step 4: asyncio delay; this is not a durable timer.
        if harness_input.timer_delay_seconds > 0 and "timer" not in state["steps"]:
            if harness_input.injected_fail_point == FailPoint.DURING_TIMER_DELAY and kill_hook:
                kill_hook(FailPoint.DURING_TIMER_DELAY)
            await asyncio.sleep(harness_input.timer_delay_seconds)
            state["timer_elapsed"] = harness_input.timer_delay_seconds
            state["steps"]["timer"] = True

        # Step 5: asyncio queue wait; this is not a durable signal.
        if harness_input.wait_for_signal_name and "wait_signal" not in state["steps"]:
            if harness_input.injected_fail_point == FailPoint.DURING_WAIT_SIGNAL and kill_hook:
                kill_hook(FailPoint.DURING_WAIT_SIGNAL)

            sig_key = f"{w_id}:{harness_input.wait_for_signal_name}"
            q = self._signals.setdefault(sig_key, asyncio.Queue())
            payload = await q.get()
            state["signal_payload"] = payload
            state["steps"]["wait_signal"] = True

        recovered_decision = (
            ModelDecision(**state["model_decision"]) if state.get("model_decision") else None
        )

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
        """Send to an in-memory asyncio queue."""
        w_id = self._workflow_id(identity)
        sig_key = f"{w_id}:{signal_name}"
        q = self._signals.setdefault(sig_key, asyncio.Queue())
        await q.put(payload)

    async def cancel(self, identity: ExecutionIdentity) -> None:
        """Mark an in-memory execution as cancelled."""
        w_id = self._workflow_id(identity)
        self._cancelled.add(w_id)

    async def get_persisted_state(self, identity: ExecutionIdentity) -> Dict[str, Any]:
        """Retrieve the in-memory journal state for inspection."""
        w_id = self._workflow_id(identity)
        return self._journal.get(w_id, {})
