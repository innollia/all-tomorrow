"""Negative test suite for 00A-1 Common Harness.

Strictly verifies that buggy or non-compliant adapter implementations
ACTUALLY FAIL the canonical scenarios under required failure conditions:
1. D04 fails when an unhandled duplicate side effect occurs.
2. D09 fails when transient backend failures exceed max retry allowance.
3. D12 fails when correlation ID is not strictly preserved across recovery.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import pytest

from all_tomorrow.harness import (
    BaselineMemoryAdapter,
    DuplicateMutationError,
    FailPoint,
    HarnessInput,
    HarnessOutput,
    KillException,
    ScenarioRunner,
    SideEffectFixtureStore,
    TraceContext,
)
from all_tomorrow.harness.tools import mutation_stub_tool, read_inventory_tool
from all_tomorrow.harness.types import ExecutionIdentity


class NonIdempotentFlawedAdapter(BaselineMemoryAdapter):
    """Buggy adapter that blindly re-executes mutation with conflicting value upon crash recovery."""

    async def start_or_resume(
        self,
        identity: ExecutionIdentity,
        harness_input: HarnessInput,
        trace_context: Optional[TraceContext],
        store: SideEffectFixtureStore,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
    ) -> HarnessOutput:
        key = self._key(identity)
        is_resume = key in self._journal

        # If resuming after kill, buggy adapter attempts to mutate with an altered value
        # violating strict idempotency
        val = "conflicting-mutated-value" if is_resume else harness_input.mutation_value

        self._journal.setdefault(key, {"identity": identity.model_dump()})

        # Trigger mutation without checking if already completed
        record = mutation_stub_tool(
            store=store,
            idempotency_key=harness_input.mutation_key,
            value=val,
            kill_hook=kill_hook,
            fail_point=harness_input.injected_fail_point,
        )

        return HarnessOutput(
            status="completed",
            task_name=harness_input.task_name,
            mutation_committed=record.applied_at_least_once,
            mutation_value=record.committed_value,
            correlation_id=trace_context.correlation_id if trace_context else "",
            execution_identity=identity,
        )


class CorruptedCorrelationAdapter(BaselineMemoryAdapter):
    """Buggy adapter that leaks caller's transient correlation ID instead of restoring original."""

    async def start_or_resume(
        self,
        identity: ExecutionIdentity,
        harness_input: HarnessInput,
        trace_context: Optional[TraceContext],
        store: SideEffectFixtureStore,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
    ) -> HarnessOutput:
        # Trigger kill hook if requested
        if harness_input.injected_fail_point == FailPoint.BEFORE_MODEL_RESULT_PERSIST and kill_hook:
            kill_hook(FailPoint.BEFORE_MODEL_RESULT_PERSIST)

        # Buggy behavior: overrides correlation_id with whatever caller passed during recovery
        leaked_corr = trace_context.correlation_id if trace_context else "corrupted"

        return HarnessOutput(
            status="completed",
            task_name=harness_input.task_name,
            mutation_committed=True,
            correlation_id=leaked_corr,  # BUG: Does NOT preserve original correlation!
            execution_identity=identity,
        )


@pytest.mark.asyncio
async def test_negative_d04_unhandled_duplicate_mutation_fails():
    """Verify that a flawed adapter producing duplicate conflicting mutations FAILS D04."""
    adapter = NonIdempotentFlawedAdapter()
    store = SideEffectFixtureStore(strict_idempotency=True)
    runner = ScenarioRunner(adapter=adapter, store=store)

    # D04 must detect unhandled DuplicateMutationError or regression
    # and fail the scenario (passed == False)
    with pytest.raises(DuplicateMutationError):
        await runner.run_d04()


@pytest.mark.asyncio
async def test_negative_d09_unrecoverable_backend_fails():
    """Verify that D09 reports FAILURE when backend disconnection exceeds max retries."""
    adapter = BaselineMemoryAdapter()
    # Inject 10 failures when runner only retries 5 times
    adapter.simulate_backend_disconnect(transient_failures=10)

    runner = ScenarioRunner(adapter=adapter)
    res = await runner.run_d09()

    assert res.passed is False, "D09 must report failed when backend cannot reconnect!"


@pytest.mark.asyncio
async def test_negative_d12_corrupted_correlation_fails():
    """Verify that D12 reports FAILURE when an adapter fails to restore the persistent correlation token."""
    adapter = CorruptedCorrelationAdapter()
    runner = ScenarioRunner(adapter=adapter)

    res = await runner.run_d12()
    assert res.passed is False, "D12 must fail when caller's transient correlation token overwrites original!"
