from __future__ import annotations

import pytest

from all_tomorrow.adapters.fake_adapters import FakeAgentAdapter, FakeDurableAdapter
from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, new_run_id
from all_tomorrow.ports.agent import AgentExecutionRequest
from all_tomorrow.ports.durable import (
    CancelOutcome,
    DurableExecutionState,
    SignalOutcome,
)
from all_tomorrow.ports.tools import (
    SideEffectClass,
    ToolDescriptor,
)
from all_tomorrow.ports.workers import (
    WorkerDescriptor,
)


@pytest.mark.asyncio
class TestDurableExecutionPortContract:
    """Requirements S0-00B2-01 through S0-00B2-04, and S0-00B2-06."""

    async def test_same_run_id_start_idempotency(self) -> None:
        """S0-00B2-01: Starting with the same run_id must return existing ExecutionRef."""
        adapter = FakeDurableAdapter()
        run_id = new_run_id()

        ref1 = await adapter.start(run_id, "test_workflow", {"arg": 1})
        ref2 = await adapter.start(run_id, "test_workflow", {"arg": 1})

        assert ref1 == ref2
        assert ref1.execution_id == ref2.execution_id

    async def test_cancel_separates_terminal_missing_and_unavailable(self) -> None:
        """S0-00B2-02: Cancel must distinguish terminal, missing, and unavailable."""
        adapter = FakeDurableAdapter()
        run_id = new_run_id()
        ref = await adapter.start(run_id, "test_workflow", {})

        # Active cancel
        cancel_res = await adapter.cancel(ref)
        assert cancel_res.outcome == CancelOutcome.CANCEL_REQUESTED

        # Already terminal cancel
        cancel_terminal_res = await adapter.cancel(ref)
        assert cancel_terminal_res.outcome == CancelOutcome.ALREADY_TERMINAL

        # Missing execution cancel
        missing_ref = ExecutionRef(backend="fake_durable", execution_id="non_existent")
        cancel_missing_res = await adapter.cancel(missing_ref)
        assert cancel_missing_res.outcome == CancelOutcome.NOT_FOUND
        assert cancel_missing_res.error is not None
        assert cancel_missing_res.error.category == ErrorCategory.NOT_FOUND

        # Backend unavailable cancel
        adapter.simulate_unavailable = True
        cancel_unavail_res = await adapter.cancel(ref)
        assert cancel_unavail_res.outcome == CancelOutcome.UNAVAILABLE
        assert cancel_unavail_res.error is not None
        assert cancel_unavail_res.error.category == ErrorCategory.UNAVAILABLE

    async def test_duplicate_signal_id_idempotency(self) -> None:
        """S0-00B2-03: Duplicate signal_id must be handled idempotently."""
        adapter = FakeDurableAdapter()
        run_id = new_run_id()
        ref = await adapter.start(run_id, "test_workflow", {})

        # First signal delivery
        sig1 = await adapter.signal(ref, "user_response", "sig_001", {"approved": True})
        assert sig1.outcome == SignalOutcome.DELIVERED

        # Duplicate signal with same signal_id
        sig2 = await adapter.signal(ref, "user_response", "sig_001", {"approved": True})
        assert sig2.outcome == SignalOutcome.DUPLICATE_IGNORED

        # Different signal_id is delivered
        sig3 = await adapter.signal(ref, "user_response", "sig_002", {"approved": False})
        assert sig3.outcome == SignalOutcome.DELIVERED

    async def test_result_separates_pending_from_empty_result(self) -> None:
        """S0-00B2-04: Pending status must be cleanly distinguished from empty completed payload."""
        adapter = FakeDurableAdapter()
        run_id = new_run_id()
        ref = await adapter.start(run_id, "test_workflow", {})

        # While running, is_pending is True, payload is None
        res_pending = await adapter.result(ref)
        assert res_pending.is_pending is True
        assert res_pending.payload is None
        assert res_pending.state == DurableExecutionState.RUNNING

        # Complete with an empty dict {} as valid output
        await adapter.complete_execution(ref, result_payload={})

        res_completed = await adapter.result(ref)
        assert res_completed.is_pending is False
        assert res_completed.state == DurableExecutionState.COMPLETED
        assert res_completed.payload == {}

    async def test_fake_alternate_adapter_conformance(self) -> None:
        """S0-00B2-06: Alternate adapter instance passes all contract requirements."""
        alternate = FakeDurableAdapter(backend_name="restate_mock")
        run_id = new_run_id()
        ref = await alternate.start(run_id, "restate_flow", {"mode": "fast"})
        assert ref.backend == "restate_mock"
        status = await alternate.get_status(ref)
        assert status.state == DurableExecutionState.RUNNING


@pytest.mark.asyncio
class TestAgentExecutionPortContract:
    async def test_agent_success(self) -> None:
        agent = FakeAgentAdapter()
        req = AgentExecutionRequest(
            model_route_ref="primary-gpt4o",
            toolset_ref="all-tomorrow-tools",
            prompt="Analyze the repository",
        )
        res = await agent.execute(req)
        assert res.success is True
        assert res.error is None
        assert res.usage.total_tokens == 30

    async def test_malformed_structured_output_not_coerced_to_success(self) -> None:
        """Malformed structured output must not be coerced to success."""
        agent = FakeAgentAdapter()
        agent.fail_with_malformed_output = True
        req = AgentExecutionRequest(
            model_route_ref="primary-gpt4o",
            toolset_ref="all-tomorrow-tools",
            prompt="Generate JSON",
            output_schema_ref="schema://Report",
        )
        res = await agent.execute(req)
        assert res.success is False
        assert res.error is not None
        assert res.error.category == ErrorCategory.INVALID_INPUT
        assert res.error.code == "malformed_structured_output"


class TestDescriptors:
    def test_tool_descriptor_validation(self) -> None:
        tool = ToolDescriptor(
            tool_id="fetch_repo",
            version="1.0.0",
            source_owner="all-tomorrow",
            capabilities=frozenset({"read_source"}),
            side_effect_class=SideEffectClass.READ_ONLY,
            required_authority="repo.read",
        )
        assert tool.tool_id == "fetch_repo"
        assert tool.side_effect_class == SideEffectClass.READ_ONLY

    def test_worker_descriptor_validation(self) -> None:
        worker = WorkerDescriptor(
            worker_id="codex_cli",
            version="1.0.0",
            capabilities=frozenset({"code_generation"}),
            authority_scope="workspace.write",
        )
        assert worker.worker_id == "codex_cli"
        assert worker.authority_scope == "workspace.write"
