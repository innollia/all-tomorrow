"""Restate workflow with a durable approval promise."""

import os

import psycopg
import restate


service = restate.Workflow("AllTomorrowSignalProbe")


@service.main()
async def run(ctx: restate.WorkflowContext, workflow_id: str) -> bool:
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

    async def record_post_signal() -> bool:
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                "INSERT INTO signal_effect_probe (workflow_id) VALUES (%s) ON CONFLICT (workflow_id) DO NOTHING",
                (workflow_id,),
            )
            conn.commit()
        return approved

    return await ctx.run("post_signal_mutation", record_post_signal)


@service.handler()
async def approve(ctx: restate.WorkflowSharedContext, approved: bool) -> None:
    await ctx.promise("approval", type_hint=bool).resolve(approved)


app = restate.app([service], protocol="request_response")
