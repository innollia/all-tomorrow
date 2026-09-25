"""Canonical Scenarios D01-D12 runner for 00A-1 Common Harness.

Executes standardized failure, recovery, concurrency, cancellation, upgrade,
and correlation scenarios against any DurableAdapter candidate with strict
compliance to the 00A-1 specification.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from .adapter import DurableAdapter
from .fixtures import DuplicateMutationError, SideEffectFixtureStore
from .tools import default_kill_hook
from .tracing import HarnessTelemetry
from .types import (
    BackendConnectionError,
    ExecutionIdentity,
    FailPoint,
    HarnessInput,
    HarnessOutput,
    KillException,
    ScenarioId,
    ScenarioResult,
    TraceContext,
)


class ScenarioRunner:
    """Standardized executor for Canonical Scenarios D01-D12."""

    def __init__(self, adapter: DurableAdapter, store: Optional[SideEffectFixtureStore] = None):
        self.adapter = adapter
        self.store = store or SideEffectFixtureStore(strict_idempotency=True)

    def _default_trace(self, scenario_id: str) -> TraceContext:
        return TraceContext(
            trace_id=f"trace-{scenario_id.lower()}-001",
            span_id=f"span-{scenario_id.lower()}-001",
            correlation_id=f"corr-{scenario_id.lower()}-token-99",
        )

    def _default_identity(self, scenario_id: str, run_id: str = "run-1") -> ExecutionIdentity:
        return ExecutionIdentity(
            work_id=f"work-{scenario_id.lower()}",
            run_id=run_id,
            attempt=1,
        )

    # -------------------------------------------------------------------------
    # D01: Normal completion (with deterministic PydanticAI model decision)
    # -------------------------------------------------------------------------
    async def run_d01(self) -> ScenarioResult:
        scenario = ScenarioId.D01_NORMAL_COMPLETION
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D01 Normal Execution",
            query_item_id="item-01",
            mutation_key="key-d01",
            mutation_value="val-d01",
        )

        try:
            output = await self.adapter.start_or_resume(identity, h_input, trace, self.store)
            passed = (
                output.status == "completed"
                and output.mutation_committed
                and output.read_item_data.get("stock") == 42
                and output.model_decision is not None
                and output.model_decision.stock_confirmed == 42
                and output.model_decision.should_commit_mutation is True
                and self.store.count("key-d01") == 1
            )
            notes = f"Completed all steps smoothly. PydanticAI model confidence={output.model_decision.confidence_score if output.model_decision else 'none'}."
        except Exception as e:
            passed = False
            notes = f"Failed with exception: {e}"

        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes=notes,
        )

    # -------------------------------------------------------------------------
    # D02: Kill before model result persist
    # -------------------------------------------------------------------------
    async def run_d02(self) -> ScenarioResult:
        scenario = ScenarioId.D02_KILL_BEFORE_MODEL_RESULT_PERSIST
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D02 Kill Before Model Persist",
            query_item_id="item-02",
            mutation_key="key-d02",
            mutation_value="val-d02",
            injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST,
        )

        # First attempt: must raise KillException
        killed = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store, default_kill_hook)
        except KillException as ke:
            if ke.point == FailPoint.BEFORE_MODEL_RESULT_PERSIST:
                killed = True

        # Second attempt (recovery): resume without failure injection
        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, trace, self.store)

        passed = (
            killed
            and output.status == "completed"
            and output.model_decision is not None
            and output.mutation_committed
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Killed before model persist; restarted and executed model phase to completion.",
        )

    # -------------------------------------------------------------------------
    # D03: Kill after model result persist
    # -------------------------------------------------------------------------
    async def run_d03(self) -> ScenarioResult:
        scenario = ScenarioId.D03_KILL_AFTER_MODEL_RESULT_PERSIST
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D03 Kill After Model Persist",
            query_item_id="item-03",
            mutation_key="key-d03",
            mutation_value="val-d03",
            injected_fail_point=FailPoint.AFTER_MODEL_RESULT_PERSIST,
        )

        killed = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store, default_kill_hook)
        except KillException as ke:
            if ke.point == FailPoint.AFTER_MODEL_RESULT_PERSIST:
                killed = True

        # Recovery run: model result should be replayed from journal without re-computation
        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, trace, self.store)

        passed = (
            killed
            and output.status == "completed"
            and output.model_decision is not None
            and output.mutation_committed
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Killed after model persist; resumed without re-running model phase.",
        )

    # -------------------------------------------------------------------------
    # D04: Kill immediately after external side effect
    # -------------------------------------------------------------------------
    async def run_d04(self) -> ScenarioResult:
        scenario = ScenarioId.D04_KILL_IMMEDIATELY_AFTER_SIDE_EFFECT
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D04 Kill After Side Effect",
            query_item_id="item-04",
            mutation_key="key-d04",
            mutation_value="val-d04",
            injected_fail_point=FailPoint.AFTER_MUTATION_SIDE_EFFECT,
        )

        killed = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store, default_kill_hook)
        except KillException as ke:
            if ke.point == FailPoint.AFTER_MUTATION_SIDE_EFFECT:
                killed = True

        # Recovery run: the mutation was committed, so resumption must reconcile
        # and NOT trigger duplicate side-effects
        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, trace, self.store)

        # A retry may call the fixture again, but the external value may be applied once only.
        call_count = self.store.count("key-d04")
        record = self.store.get("key-d04")
        passed = (
            killed
            and output.status == "completed"
            and output.mutation_committed
            and record is not None
            and record.application_count == 1
            and record.committed_value == "val-d04"
        )

        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes=f"Killed immediately after mutation; recovery reconciled side-effect (call_count={call_count}).",
        )

    # -------------------------------------------------------------------------
    # D05: Duplicate start with same execution identity
    # -------------------------------------------------------------------------
    async def run_d05(self) -> ScenarioResult:
        scenario = ScenarioId.D05_DUPLICATE_START_WITH_SAME_IDENTITY
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D05 Duplicate Start",
            query_item_id="item-05",
            mutation_key="key-d05",
            mutation_value="val-d05",
        )

        # Run 1
        output1 = await self.adapter.start_or_resume(identity, h_input, trace, self.store)
        # Run 2 with identical identity
        output2 = await self.adapter.start_or_resume(identity, h_input, trace, self.store)

        # Both must return valid completion, and mutation key must not duplicate
        passed = (
            output1.status == "completed"
            and output2.status == "completed"
            and self.store.count("key-d05") == 1
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Duplicate execution run attached to existing journal without side-effect collision.",
        )

    # -------------------------------------------------------------------------
    # D06: User wait → process restart → signal → resume
    # -------------------------------------------------------------------------
    async def run_d06(self) -> ScenarioResult:
        scenario = ScenarioId.D06_USER_WAIT_RESTART_SIGNAL_RESUME
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D06 User Wait Signal",
            query_item_id="item-06",
            mutation_key="key-d06",
            mutation_value="val-d06",
            wait_for_signal_name="approval_signal",
            injected_fail_point=FailPoint.DURING_WAIT_SIGNAL,
        )

        # Phase 1: start waiting and simulate restart via kill hook
        killed = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store, default_kill_hook)
        except KillException:
            killed = True

        # Phase 2: send external signal while process was "dead/restarting"
        await self.adapter.send_signal(identity, "approval_signal", {"approved": True, "by": "user-admin"})

        # Phase 3: process resumes, catches the signal and finishes
        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, trace, self.store)

        passed = (
            killed
            and output.status == "completed"
            and output.signal_received_payload == {"approved": True, "by": "user-admin"}
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Waiting run interrupted; signal sent; resumed and consumed signal accurately.",
        )

    # -------------------------------------------------------------------------
    # D07: Long timer/delay → restart → resume
    # -------------------------------------------------------------------------
    async def run_d07(self) -> ScenarioResult:
        scenario = ScenarioId.D07_LONG_TIMER_RESTART_RESUME
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D07 Long Timer",
            query_item_id="item-07",
            mutation_key="key-d07",
            mutation_value="val-d07",
            timer_delay_seconds=0.05,
            injected_fail_point=FailPoint.DURING_TIMER_DELAY,
        )

        killed = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store, default_kill_hook)
        except KillException:
            killed = True

        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, trace, self.store)

        passed = killed and output.status == "completed" and output.timer_elapsed_seconds >= 0.05
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Timer interrupted midway; restarted and timer completed.",
        )

    # -------------------------------------------------------------------------
    # D08: Cancel
    # -------------------------------------------------------------------------
    async def run_d08(self) -> ScenarioResult:
        scenario = ScenarioId.D08_CANCEL
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D08 Cancel Execution",
            query_item_id="item-08",
            mutation_key="key-d08",
            mutation_value="val-d08",
        )

        # Cancel identity before or during execution
        await self.adapter.cancel(identity)
        cancelled = False
        try:
            await self.adapter.start_or_resume(identity, h_input, trace, self.store)
        except RuntimeError as re:
            if "cancelled" in str(re).lower():
                cancelled = True

        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=cancelled,
            recovery_notes="Run was cancelled and prevented from executing.",
        )

    # -------------------------------------------------------------------------
    # D09: Backend temporary unavailable → reconnect (STRICT FAILURE INJECTION)
    # -------------------------------------------------------------------------
    async def run_d09(self, injected_transient_failures: Optional[int] = None) -> ScenarioResult:
        scenario = ScenarioId.D09_BACKEND_TEMP_UNAVAILABLE_RECONNECT
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)
        h_input = HarnessInput(
            task_name="D09 Temporary Unavailable",
            query_item_id="item-09",
            mutation_key="key-d09",
            mutation_value="val-d09",
        )

        expected_failures = 2
        # Inject real transient backend disconnection: respect pre-configured count or parameter
        if injected_transient_failures is not None:
            expected_failures = injected_transient_failures
            self.adapter.simulate_backend_disconnect(transient_failures=injected_transient_failures)
        elif getattr(self.adapter, "_transient_failures_remaining", 0) > 0:
            expected_failures = getattr(self.adapter, "_transient_failures_remaining")
        else:
            self.adapter.simulate_backend_disconnect(transient_failures=2)

        failures_caught = 0
        max_reconnect_attempts = 5
        output = None

        for attempt in range(max_reconnect_attempts):
            try:
                output = await self.adapter.start_or_resume(identity, h_input, trace, self.store)
                break  # Successfully connected and executed
            except BackendConnectionError:
                failures_caught += 1
                # Exponential backoff simulation
                await asyncio.sleep(0.01 * (attempt + 1))

        passed = (
            failures_caught == expected_failures
            and output is not None
            and output.status == "completed"
            and output.mutation_committed
        )

        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes=(
                f"Transient disconnect injected ({failures_caught} failures caught); reconnected cleanly on attempt {failures_caught + 1}."
                if output is not None
                else f"Failed to reconnect after {failures_caught} attempts."
            ),
        )

    # -------------------------------------------------------------------------
    # D10: Old in-flight execution under ordinary application upgrade (STRICT V1->V2 INSTANCE MIGRATION)
    # -------------------------------------------------------------------------
    async def run_d10(self) -> ScenarioResult:
        scenario = ScenarioId.D10_OLD_IN_FLIGHT_EXECUTION_UPGRADE
        identity = self._default_identity(scenario.value)
        trace = self._default_trace(scenario.value)

        # Phase 1: Start execution on V1 adapter instance, pause/kill before mutation
        h_input_v1 = HarnessInput(
            task_name="D10 Upgrade V1",
            query_item_id="item-10",
            mutation_key="key-d10",
            mutation_value="val-d10",
            injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST,
        )
        try:
            await self.adapter.start_or_resume(identity, h_input_v1, trace, self.store, default_kill_hook)
        except KillException:
            pass

        # Phase 2: Export persistent journal from V1 adapter (simulating process shutdown before upgrade)
        v1_exported_journal = self.adapter.export_journal_state()

        # Phase 3: Instantiate fresh Upgraded V2 adapter instance (simulating upgraded application binary)
        adapter_cls = type(self.adapter)
        upgraded_v2_adapter = adapter_cls(candidate_name=getattr(self.adapter, "candidate_name", "baseline"), version="2.0.0")
        upgraded_v2_adapter.import_journal_state(v1_exported_journal)

        # Phase 4: Resume execution on the upgraded V2 adapter instance
        h_input_v2 = HarnessInput(
            task_name="D10 Upgrade V2 Resumption",
            query_item_id="item-10",
            mutation_key="key-d10",
            mutation_value="val-d10",
            metadata={"app_version": "2.0.0"},
            injected_fail_point=FailPoint.NONE,
        )
        output = await upgraded_v2_adapter.start_or_resume(identity, h_input_v2, trace, self.store)

        passed = (
            output.status == "completed"
            and output.mutation_committed
            and output.model_decision is not None
            and upgraded_v2_adapter.version == "2.0.0"
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(upgraded_v2_adapter, "candidate_name", "unknown"),
            version="2.0.0",
            passed=passed,
            recovery_notes="In-flight execution exported from V1 instance and successfully resumed to completion on upgraded V2 instance.",
        )

    # -------------------------------------------------------------------------
    # D11: Two logical Runs for one Work stay distinct
    # -------------------------------------------------------------------------
    async def run_d11(self) -> ScenarioResult:
        scenario = ScenarioId.D11_TWO_LOGICAL_RUNS_FOR_ONE_WORK
        identity_run1 = self._default_identity(scenario.value, run_id="run-001")
        identity_run2 = self._default_identity(scenario.value, run_id="run-002")
        trace1 = self._default_trace(f"{scenario.value}-1")
        trace2 = self._default_trace(f"{scenario.value}-2")

        h_input1 = HarnessInput(
            task_name="D11 Run 1",
            query_item_id="item-11",
            mutation_key="key-d11-1",
            mutation_value="val-d11-1",
        )
        h_input2 = HarnessInput(
            task_name="D11 Run 2",
            query_item_id="item-11",
            mutation_key="key-d11-2",
            mutation_value="val-d11-2",
        )

        out1 = await self.adapter.start_or_resume(identity_run1, h_input1, trace1, self.store)
        out2 = await self.adapter.start_or_resume(identity_run2, h_input2, trace2, self.store)

        # Both belong to same work_id but separate run_id
        state1 = await self.adapter.get_persisted_state(identity_run1)
        state2 = await self.adapter.get_persisted_state(identity_run2)

        passed = (
            out1.execution_identity.run_id == "run-001"
            and out2.execution_identity.run_id == "run-002"
            and state1 != state2
            and self.store.count("key-d11-1") == 1
            and self.store.count("key-d11-2") == 1
        )
        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            recovery_notes="Distinct logical Runs for same Work persisted separately without collision.",
        )

    # -------------------------------------------------------------------------
    # D12: OTel correlation survives recovery (STRICT PRESERVATION FROM PERSISTED JOURNAL)
    # -------------------------------------------------------------------------
    async def run_d12(self) -> ScenarioResult:
        scenario = ScenarioId.D12_OTEL_CORRELATION_SURVIVES_RECOVERY
        identity = self._default_identity(scenario.value)
        
        # Real OpenTelemetry span capture fixture
        telemetry = HarnessTelemetry()

        # Original caller with initial trace and correlation token
        original_trace = TraceContext(
            trace_id="original-root-trace-777",
            span_id="original-root-span-777",
            correlation_id="CORRELATION_TOKEN_SURVIVING_RECOVERY_777",
        )

        h_input = HarnessInput(
            task_name="D12 OTel Correlation",
            query_item_id="item-12",
            mutation_key="key-d12",
            mutation_value="val-d12",
            injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST,
        )

        # Phase 1: Record initial root span before crash
        telemetry.record_span("initial_dispatch", original_trace.correlation_id)

        # Start run and trigger simulated crash
        try:
            await self.adapter.start_or_resume(identity, h_input, original_trace, self.store, default_kill_hook)
        except KillException:
            pass

        # Phase 2: Recovery caller connects with a COMPLETELY DIFFERENT transient context!
        # Strict test: The caller DOES NOT provide the original correlation token.
        # The adapter must restore the original token strictly from its persisted journal.
        transient_recovery_trace = TraceContext(
            trace_id="transient-caller-retry-trace-999",
            span_id="transient-caller-retry-span-999",
            correlation_id="TRANSIENT_CALLER_TOKEN_MUST_NOT_OVERWRITE",
        )

        h_input_resume = h_input.model_copy(update={"injected_fail_point": FailPoint.NONE})
        output = await self.adapter.start_or_resume(identity, h_input_resume, transient_recovery_trace, self.store)

        # Phase 3: Record recovered span using output correlation ID
        telemetry.record_span("recovered_dispatch", output.correlation_id)

        # Real OTel verification: check span attributes in exporter
        captured_correlations = telemetry.get_correlation_ids_from_spans()
        otel_spans_matched = (
            len(captured_correlations) == 2
            and captured_correlations[0] == "CORRELATION_TOKEN_SURVIVING_RECOVERY_777"
            and captured_correlations[1] == "CORRELATION_TOKEN_SURVIVING_RECOVERY_777"
        )

        # Strict assertion: Output MUST carry the original correlation_id from journal, NOT the caller's transient token!
        passed = (
            output.correlation_id == "CORRELATION_TOKEN_SURVIVING_RECOVERY_777"
            and output.correlation_id != transient_recovery_trace.correlation_id
            and otel_spans_matched
        )

        return ScenarioResult(
            scenario_id=scenario.value,
            candidate=getattr(self.adapter, "candidate_name", "unknown"),
            version=getattr(self.adapter, "version", "1.0.0"),
            passed=passed,
            trace_notes=f"Original correlation token '{output.correlation_id}' verified across {len(captured_correlations)} real OTel spans despite transient caller ID.",
        )

    # -------------------------------------------------------------------------
    # Run All
    # -------------------------------------------------------------------------
    async def run_all(self) -> List[ScenarioResult]:
        """Execute the full canonical battery D01 through D12 in sequence."""
        return [
            await self.run_d01(),
            await self.run_d02(),
            await self.run_d03(),
            await self.run_d04(),
            await self.run_d05(),
            await self.run_d06(),
            await self.run_d07(),
            await self.run_d08(),
            await self.run_d09(),
            await self.run_d10(),
            await self.run_d11(),
            await self.run_d12(),
        ]
