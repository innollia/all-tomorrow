"""Restate workflow with durable five-second timer."""

import os
import time
from datetime import timedelta

import psycopg
import restate


service = restate.Workflow("AllTomorrowTimerProbe")


@service.main()
async def run(ctx: restate.WorkflowContext, workflow_id: str) -> float:
    async def mark_start() -> float:
        started = time.time()
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            conn.execute(
                "INSERT INTO timer_probe (workflow_id, started) VALUES (%s, %s) ON CONFLICT (workflow_id) DO NOTHING",
                (workflow_id, started),
            )
            conn.commit()
        return started

    await ctx.run("mark_start", mark_start)
    await ctx.sleep(timedelta(seconds=5), name="wait_five_seconds")
    return time.time()


app = restate.app([service], protocol="request_response")
