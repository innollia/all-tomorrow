"""Real Restate SDK endpoint used by the Linux substrate probe."""

import restate
from datetime import timedelta
import os

from all_tomorrow.harness.types import HarnessInput
from .live_common import apply_mutation


probe = restate.Workflow("AllTomorrowProbe")


@probe.main()
async def run(ctx: restate.WorkflowContext, value: str | dict) -> str:
    if isinstance(value, dict) and value.get("kind") == "concurrent-start":
        await ctx.sleep(timedelta(seconds=2))
    async def record() -> str:
        if isinstance(value, dict) and value.get("kind") == "concurrent-start":
            data = HarnessInput(
                task_name="Concurrent Restate start",
                mutation_key=value["mutation_key"],
                mutation_value="concurrent-start",
            )
            return apply_mutation(os.environ["AT_TEST_FIXTURE_URL"], data)
        return value

    return await ctx.run("record_result", record)


app = restate.app([probe], protocol="request_response")
