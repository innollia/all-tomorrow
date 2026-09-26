"""Verification for 00D Observability and Privacy requirements.

Tests:
- D-TRACE-01: End-to-end correlation across goal_id, work_id, run_id, trace_id, execution_id, and artifact_ref.
- D-DUP-01: Clean span topology with no duplicate/disjoint span trees for MCP/tool calls.
- D-EVENT-01: Domain events capture only long-term facts and do not explode proportionally to OTel spans.
- D-PRIV-01: Negative scan proves zero leaks of prompt text or secret tokens in exported telemetry attributes.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from all_tomorrow.adapters.fake_adapters import FakeAgentAdapter, FakeDurableAdapter
from all_tomorrow.domain import CompletionEvidence
from all_tomorrow.domain.events import EventRecord
from all_tomorrow.domain.ids import ExecutionRef, new_event_id, utc_now
from all_tomorrow.observability import CorrelationContext, TelemetryManager
from all_tomorrow.orchestration.walking_skeleton import WalkingSkeletonOrchestrator
from all_tomorrow.storage.artifact_store import LocalArtifactStore
from all_tomorrow.storage.delivery_store import DeliveryStore


class TestObservability00D:
    """Stage 00D Observability & Privacy Requirements Verification."""

    @pytest.mark.asyncio
    async def test_d_trace_01_end_to_end_correlation(self, tmp_path: Path) -> None:
        """D-TRACE-01: Skeleton execution is fully correlated end-to-end across required IDs."""
        span_file = tmp_path / "spans.jsonl"
        telemetry = TelemetryManager(span_file=span_file, in_memory=True)
        durable_port = FakeDurableAdapter()
        agent_port = FakeAgentAdapter()
        delivery_store = DeliveryStore()
        artifact_store = LocalArtifactStore(tmp_path / "artifacts")

        orch = WalkingSkeletonOrchestrator(
            durable_port=durable_port,
            agent_port=agent_port,
            delivery_store=delivery_store,
            artifact_store=artifact_store,
            telemetry=telemetry,
        )

        goal, work = await orch.initiate_goal_and_work("user-trace-01", "Trace Goal", "Trace Work")
        run, intent = await orch.create_starting_run(work.work_id)
        exec_ref = ExecutionRef(backend="fake_durable", execution_id=f"exec-{run.run_id}")
        orch.cas_attach_execution_ref(run.run_id, exec_ref)

        # Agent step
        agent_res = await orch.execute_agent_step(run.run_id, prompt="Calculate metric")
        assert agent_res.success

        # Artifact step
        art_ref = await orch.record_artifact(run.run_id, b'{"result": "computed_value"}')

        # Complete step
        evidence = CompletionEvidence(
            criterion_ref="crit_trace_01",
            evaluator_ref="eval_trace",
            evaluator_version="1.0",
        )
        await orch.complete_run_and_work(run.run_id, {"status": "ok"}, evidence)

        # Assert spans
        spans = telemetry.get_finished_spans()
        assert len(spans) >= 4, f"Expected at least 4 finished spans, got {len(spans)}"

        # Find spans
        root_span = next((s for s in spans if s.name == "orchestrator_run"), None)
        assert root_span is not None, "Root orchestrator span must exist"

        agent_span = next((s for s in spans if s.name == "agent_execution_step"), None)
        assert agent_span is not None, "Agent step child span must exist"

        art_span = next((s for s in spans if s.name == "record_artifact"), None)
        assert art_span is not None, "Artifact record child span must exist"

        comp_span = next((s for s in spans if s.name == "complete_run"), None)
        assert comp_span is not None, "Completion child span must exist"

        # Verify trace correlation attributes on root and children
        root_attrs = root_span.attributes
        assert root_attrs["all_tomorrow.goal_id"] == str(goal.goal_id)
        assert root_attrs["all_tomorrow.work_id"] == str(work.work_id)
        assert root_attrs["all_tomorrow.run_id"] == str(run.run_id)
        assert root_attrs["all_tomorrow.trace_id"] == f"trace-{run.run_id}"
        assert root_attrs["all_tomorrow.execution_id"] == exec_ref.execution_id

        # Verify child spans share the same trace_id
        for child in [agent_span, art_span, comp_span]:
            assert child.context.trace_id == root_span.context.trace_id, (
                f"Child span {child.name} has disjoint trace_id"
            )
            assert child.parent.span_id == root_span.context.span_id, (
                f"Child span {child.name} must have root as parent"
            )

        # Verify artifact ref is attached in artifact span
        assert art_span.attributes["all_tomorrow.artifact_id"] == str(art_ref.artifact_id)
        assert art_span.attributes["all_tomorrow.media_type"] == "application/json"

    def test_d_dup_01_no_duplicate_span_trees(self, tmp_path: Path) -> None:
        """D-DUP-01: Same tool/MCP calls produce single hierarchical tree without duplicate trees."""
        telemetry = TelemetryManager(in_memory=True)
        corr = CorrelationContext(
            goal_id="g1",
            work_id="w1",
            run_id="r1",
            trace_id="t1",
            execution_id="e1",
        )

        root = telemetry.start_root_span("root_pipeline", context=corr)

        # Call MCP tool A twice
        tool_span_1 = telemetry.start_child_span(
            "mcp_call:inventory",
            parent_span=root,
            context=corr,
            extra_attributes={"tool.name": "check_inventory", "tool.call_index": 1},
        )
        tool_span_1.end()

        tool_span_2 = telemetry.start_child_span(
            "mcp_call:inventory",
            parent_span=root,
            context=corr,
            extra_attributes={"tool.name": "check_inventory", "tool.call_index": 2},
        )
        tool_span_2.end()

        root.end()

        spans = telemetry.get_finished_spans()
        assert len(spans) == 3

        # Topological verification:
        root_spans = [s for s in spans if s.parent is None]
        assert len(root_spans) == 1, "Must have exactly 1 root span (no disjoint/orphaned trees)"
        assert root_spans[0].name == "root_pipeline"

        child_spans = [s for s in spans if s.parent is not None]
        assert len(child_spans) == 2
        for child in child_spans:
            assert child.parent.span_id == root_spans[0].context.span_id
            assert child.context.trace_id == root_spans[0].context.trace_id

    @pytest.mark.asyncio
    async def test_d_event_01_events_do_not_explode_with_spans(self, tmp_path: Path) -> None:
        """D-EVENT-01: Domain events are restricted to long-term facts and do not explode with spans."""
        telemetry = TelemetryManager(in_memory=True)
        durable_port = FakeDurableAdapter()
        agent_port = FakeAgentAdapter()
        delivery_store = DeliveryStore()
        artifact_store = LocalArtifactStore(tmp_path / "artifacts")

        orch = WalkingSkeletonOrchestrator(
            durable_port=durable_port,
            agent_port=agent_port,
            delivery_store=delivery_store,
            artifact_store=artifact_store,
            telemetry=telemetry,
        )

        goal, work = await orch.initiate_goal_and_work("user-event", "Event Goal", "Event Work")
        run, _ = await orch.create_starting_run(work.work_id)
        exec_ref = ExecutionRef(backend="fake_durable", execution_id=f"exec-{run.run_id}")
        orch.cas_attach_execution_ref(run.run_id, exec_ref)

        # Record domain event for starting
        orch.events.append(
            EventRecord(
                event_id=new_event_id(),
                event_type="RUN_STARTED",
                actor_ref="orchestrator",
                correlation_id=f"corr-{run.run_id}",
                subject_refs={"run_id": str(run.run_id), "work_id": str(work.work_id)},
            )
        )

        # Generate 15 granular tool/agent sub-spans in telemetry
        corr = orch.correlation_contexts[run.run_id]
        root = orch.active_spans[run.run_id]
        for i in range(15):
            sub_span = telemetry.start_child_span(
                f"step_sub_operation_{i}",
                parent_span=root,
                context=corr,
                extra_attributes={"step.index": i},
            )
            sub_span.end()

        # Complete run
        evidence = CompletionEvidence(
            criterion_ref="crit_event_01",
            evaluator_ref="eval_ev",
            evaluator_version="1.0",
        )
        await orch.complete_run_and_work(run.run_id, {"ok": True}, evidence)

        # Record domain event for completion
        orch.events.append(
            EventRecord(
                event_id=new_event_id(),
                event_type="WORK_SUCCEEDED",
                actor_ref="orchestrator",
                correlation_id=f"corr-{run.run_id}",
                subject_refs={"work_id": str(work.work_id), "goal_id": str(goal.goal_id)},
            )
        )

        spans = telemetry.get_finished_spans()
        # Telemetry captured many granular sub-operations
        assert len(spans) >= 17, f"Expected >= 17 spans, got {len(spans)}"

        # Domain events are strictly bounded to long-term facts
        assert len(orch.events) == 2, f"Domain events must remain bounded, got {len(orch.events)}"
        assert {e.event_type for e in orch.events} == {"RUN_STARTED", "WORK_SUCCEEDED"}

    @pytest.mark.asyncio
    async def test_d_priv_01_secret_and_prompt_telemetry_scan_zero(self, tmp_path: Path) -> None:
        """D-PRIV-01: Negative scan proves 0 occurrences of secret fixtures or raw prompts in telemetry."""
        span_file = tmp_path / "privacy_spans.jsonl"
        telemetry = TelemetryManager(span_file=span_file, in_memory=True)

        secret_canary = f"sk-secret-token-{uuid4().hex}"
        prompt_canary = f"Top-Secret-Prompt-{uuid4().hex}: Do not leak this instruction"
        tool_secret_canary = f"bearer secret-key-{uuid4().hex}"

        durable_port = FakeDurableAdapter()
        agent_port = FakeAgentAdapter()
        delivery_store = DeliveryStore()
        artifact_store = LocalArtifactStore(tmp_path / "artifacts")

        orch = WalkingSkeletonOrchestrator(
            durable_port=durable_port,
            agent_port=agent_port,
            delivery_store=delivery_store,
            artifact_store=artifact_store,
            telemetry=telemetry,
        )

        goal, work = await orch.initiate_goal_and_work("user-priv", "Privacy Goal", "Privacy Work")
        run, _ = await orch.create_starting_run(work.work_id)
        exec_ref = ExecutionRef(backend="fake_durable", execution_id=f"exec-{run.run_id}")
        orch.cas_attach_execution_ref(run.run_id, exec_ref)

        # Execute agent step with prompt containing secret and canary
        full_prompt = f"{prompt_canary} using auth {secret_canary}"
        await orch.execute_agent_step(run.run_id, prompt=full_prompt)

        # Emitting custom span with sensitive attributes
        corr = orch.correlation_contexts[run.run_id]
        root = orch.active_spans[run.run_id]
        sensitive_span = telemetry.start_child_span(
            "worker_execution",
            parent_span=root,
            context=corr,
            extra_attributes={
                "prompt": prompt_canary,
                "raw_prompt": full_prompt,
                "api_key": secret_canary,
                "auth_header": tool_secret_canary,
                "safe_info": "safe_metadata_value",
            },
        )
        sensitive_span.end()

        # Complete
        evidence = CompletionEvidence(
            criterion_ref="crit_priv_01",
            evaluator_ref="eval_privacy",
            evaluator_version="1.0",
        )
        await orch.complete_run_and_work(run.run_id, {"ok": True}, evidence)

        # 1. Scan in-memory finished spans
        spans = telemetry.get_finished_spans()
        assert len(spans) >= 3

        for span in spans:
            attrs_str = json.dumps(dict(span.attributes or {}))
            assert secret_canary not in attrs_str, f"Secret leaked in span {span.name}"
            assert prompt_canary not in attrs_str, f"Prompt leaked in span {span.name}"
            assert tool_secret_canary not in attrs_str, f"Tool secret leaked in span {span.name}"

        # 2. Scan exported JSON-line file
        if span_file.exists():
            file_content = span_file.read_text(encoding="utf-8")
            assert secret_canary not in file_content, "Secret leaked in exported span file"
            assert prompt_canary not in file_content, "Prompt canary leaked in exported span file"
            assert tool_secret_canary not in file_content, "Tool secret leaked in exported span file"

        # 3. Assert total leak count is strictly 0
        dumped_all = json.dumps([dict(s.attributes or {}) for s in spans])
        leak_matches = [
            canary for canary in [secret_canary, prompt_canary, tool_secret_canary]
            if canary in dumped_all
        ]
        assert len(leak_matches) == 0, f"Privacy violation: found leaks {leak_matches}"
