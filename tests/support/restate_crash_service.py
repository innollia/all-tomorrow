"""Restate workflow that can die immediately after an external commit."""

import os

import psycopg
import restate


service = restate.Workflow("AllTomorrowCrashProbe")


@service.main()
async def run(ctx: restate.WorkflowContext, workflow_id: str) -> str:
    async def mutate() -> str:
        with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
            row = conn.execute(
                """INSERT INTO crash_probe (idempotency_key, call_count, application_count, committed_value)
                   VALUES (%s, 1, 1, 'committed')
                   ON CONFLICT (idempotency_key) DO UPDATE
                   SET call_count = crash_probe.call_count + 1
                   RETURNING call_count, application_count""",
                (workflow_id,),
            ).fetchone()
            conn.commit()
        if os.environ.get("AT_TEST_RESTATE_CRASH") == "1" and row[0] == 1:
            os._exit(77)
        assert row[1] == 1
        return "committed"

    return await ctx.run("external_mutation", mutate)


app = restate.app([service], protocol="request_response")
