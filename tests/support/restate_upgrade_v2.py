"""New Restate application accepting the V1 journal and adding finalization."""

import os

import psycopg
import restate
from .otel_file_exporter import tracer_for
from all_tomorrow.harness.agent import create_deterministic_agent


service = restate.Workflow("AllTomorrowUpgradeProbe")
tracer = tracer_for(os.environ["AT_TEST_OTEL_SPANS"])


@service.main()
async def run(ctx: restate.WorkflowContext, payload: dict) -> dict:
    workflow_id = payload["workflow_id"]
    correlation_id = payload["correlation_id"]
    async def decision() -> dict:
        # Completed V1 decisions replay without entering this action. If V1
        # died before its journal record, the model is called again here.
        output = (await create_deterministic_agent().run("Check stock before approval")).output
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                "UPDATE upgrade_probe SET model_calls=model_calls+1 WHERE workflow_id=%s",
                (workflow_id,),
            )
            conn.commit()
        return {"stock": output.stock_confirmed, "source": "v2"}

    model = await ctx.run("decision", decision)

    async def mark_waiting() -> bool:
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                "INSERT INTO signal_probe (workflow_id, waiting) VALUES (%s, TRUE) ON CONFLICT (workflow_id) DO NOTHING",
                (workflow_id,),
            )
            conn.commit()
        return True

    await ctx.run("mark_waiting", mark_waiting)
    approved = await ctx.promise("approval", type_hint=bool)
    with tracer.start_as_current_span("restate_v2_recovered") as span:
        span.set_attribute("all_tomorrow.correlation_id", correlation_id)
        span.set_attribute("all_tomorrow.transient_caller_id", os.environ["AT_TEST_TRANSIENT_CORR"])

    async def finalize() -> bool:
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute("UPDATE upgrade_probe SET finalized=TRUE WHERE workflow_id=%s", (workflow_id,))
            conn.commit()
        return True

    await ctx.run("finalize_v2", finalize)
    return {
        "stock": model["stock"],
        "approved": approved,
        "schema": 2,
        "source": model.get("source", "v1-replayed"),
    }


@service.handler()
async def approve(ctx: restate.WorkflowSharedContext, approved: bool) -> None:
    await ctx.promise("approval", type_hint=bool).resolve(approved)


app = restate.app([service], protocol="request_response")
