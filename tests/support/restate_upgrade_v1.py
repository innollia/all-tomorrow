"""Old Restate application with a model result and a durable approval wait."""

import os

import psycopg
import restate

from all_tomorrow.harness.agent import create_deterministic_agent
from .otel_file_exporter import tracer_for


service = restate.Workflow("AllTomorrowUpgradeProbe")
tracer = tracer_for(os.environ["AT_TEST_OTEL_SPANS"])


@service.main()
async def run(ctx: restate.WorkflowContext, payload: dict) -> dict:
    workflow_id = payload["workflow_id"]
    correlation_id = payload["correlation_id"]
    async def decision() -> dict:
        output = (await create_deterministic_agent().run("Check stock before approval")).output
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                """INSERT INTO upgrade_probe (workflow_id, model_calls, finalized)
                   VALUES (%s, 1, FALSE)
                   ON CONFLICT (workflow_id) DO UPDATE SET model_calls = upgrade_probe.model_calls + 1""",
                (workflow_id,),
            )
            conn.commit()
        if os.environ.get("AT_TEST_CRASH_BEFORE_MODEL_PERSIST") == "1":
            os._exit(78)
        return {"stock": output.stock_confirmed}

    model = await ctx.run("decision", decision)
    if os.environ.get("AT_TEST_CRASH_AFTER_MODEL_PERSIST") == "1":
        os._exit(79)

    async def mark_waiting() -> bool:
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                "INSERT INTO signal_probe (workflow_id, waiting) VALUES (%s, TRUE) ON CONFLICT (workflow_id) DO NOTHING",
                (workflow_id,),
            )
            conn.commit()
        return True

    await ctx.run("mark_waiting", mark_waiting)
    with tracer.start_as_current_span("restate_v1_wait_started") as span:
        span.set_attribute("all_tomorrow.correlation_id", correlation_id)
    approved = await ctx.promise("approval", type_hint=bool)
    return {"stock": model["stock"], "approved": approved, "schema": 1}


@service.handler()
async def approve(ctx: restate.WorkflowSharedContext, approved: bool) -> None:
    await ctx.promise("approval", type_hint=bool).resolve(approved)


app = restate.app([service], protocol="request_response")
