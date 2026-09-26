"""Real Restate D01 workflow accepting the same typed payload as DBOS."""

import os
from datetime import timedelta
import psycopg

import restate

from all_tomorrow.harness.agent import create_deterministic_agent
from all_tomorrow.harness.tools import read_inventory_tool
from all_tomorrow.harness.types import ExecutionIdentity, FailPoint, HarnessInput, HarnessOutput, TraceContext
from .live_common import apply_mutation, observe_model, crash_at, emit_trace, record_followup, model_agent, model_context
from .otel_file_exporter import persisted_context, tracer_for


TRACER = tracer_for(os.environ["AT_TEST_OTEL_SPANS"]) if os.environ.get("AT_TEST_OTEL_SPANS") else None


service = restate.Workflow("AllTomorrowCommonD01")


@service.main()
async def run(ctx: restate.WorkflowContext, payload: dict) -> dict:
    data = HarnessInput.model_validate(payload["input"])
    identity = ExecutionIdentity.model_validate(payload["identity"])
    trace = TraceContext.model_validate(payload["trace"])

    async def read() -> dict:
        return read_inventory_tool(data.query_item_id)

    async def decide() -> dict:
        with model_context(trace):
            result = await model_agent().run(
                f"Evaluate task '{data.task_name}' for item '{data.query_item_id}'"
            )
        observe_model(os.environ["AT_TEST_FIXTURE_URL"], data)
        crash_at(data, FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, TRACER, trace)
        return result.output.model_dump()

    async def mutate() -> str:
        value = apply_mutation(os.environ["AT_TEST_FIXTURE_URL"], data)
        crash_at(data, FailPoint.AFTER_MUTATION_SIDE_EFFECT, 77, TRACER, trace)
        return value

    inventory = await ctx.run("common_read_inventory", read)
    decision = await ctx.run("common_model_decision", decide)
    crash_at(data, FailPoint.AFTER_MODEL_RESULT_PERSIST, 79, TRACER, trace)
    value = await ctx.run("common_mutation", mutate)
    signal_payload = None
    if data.timer_delay_seconds:
        emit_trace(TRACER, trace, "common_timer_started")
        await ctx.sleep(timedelta(seconds=data.timer_delay_seconds), name="common_timer")
        emit_trace(TRACER, trace, "common_timer_finished")
    if data.wait_for_signal_name:
        async def mark_waiting() -> bool:
            with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
                conn.execute(
                    "INSERT INTO common_wait_probe (workflow_id, waiting) VALUES (%s, TRUE) ON CONFLICT (workflow_id) DO NOTHING",
                    (f"{identity.work_id}:{identity.run_id}",),
                )
                conn.commit()
            return True

        await ctx.run("common_mark_waiting", mark_waiting)
        emit_trace(TRACER, trace, "common_restate_wait_started")
        signal_payload = await ctx.promise(data.wait_for_signal_name, type_hint=dict)
        emit_trace(TRACER, trace, "common_restate_recovered")
    if signal_payload is not None:
        async def followup():
            record_followup(os.environ["AT_TEST_FIXTURE_URL"], data.mutation_key)
        await ctx.run("common_followup", followup)
    if os.environ.get("AT_TEST_APP_REVISION") == "2":
        async def finalize():
            from .common_revision_v2 import finalize as implementation
            return implementation(os.environ["AT_TEST_FIXTURE_URL"], data.mutation_key)
        await ctx.run("common_v2_finalize", finalize)
    emit_trace(TRACER, trace, "common_completed")
    return HarnessOutput(
        task_name=data.task_name,
        read_item_data=inventory,
        model_decision=decision,
        mutation_committed=True,
        mutation_value=value,
        signal_received_payload=signal_payload,
        correlation_id=trace.correlation_id,
        execution_identity=identity,
        timer_elapsed_seconds=data.timer_delay_seconds,
    ).model_dump(mode="json")


@service.handler()
async def approve(ctx: restate.WorkflowSharedContext, payload: dict) -> None:
    await ctx.promise("approval", type_hint=dict).resolve(payload)


app = restate.app([service], protocol="request_response")
