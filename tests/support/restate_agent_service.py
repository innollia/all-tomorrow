"""Actual RestateAgent/PydanticAI TestModel integration endpoint."""

import restate
from restate.ext.pydantic import RestateAgent

from all_tomorrow.harness.agent import create_deterministic_agent


agent = RestateAgent(create_deterministic_agent(), auto_wrap_tools=True)
service = restate.Workflow("AllTomorrowAgentProbe")


@service.main()
async def run(ctx: restate.WorkflowContext, prompt: str) -> dict:
    result = await agent.run(prompt)
    return result.output.model_dump()


app = restate.app([service], protocol="request_response")
