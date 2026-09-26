"""Deterministic PydanticAI Agent and structured output definitions for 00A-1 Common Harness.

Uses PydanticAI Agent and TestModel to provide fully deterministic, repeatable
model reasoning and structured decision-making without calling external LLM APIs.
"""

from __future__ import annotations

from typing import Any, Dict
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from .tools import read_inventory_tool
from .types import ModelDecision


def create_deterministic_agent() -> Agent[None, ModelDecision]:
    """Builds a PydanticAI agent backed by TestModel with structured output."""
    model = TestModel(
        custom_output_args={
            "task_summary": "Deterministic evaluation completed via TestModel",
            "stock_confirmed": 42,
            "should_commit_mutation": True,
            "confidence_score": 0.99,
            "planned_mutation_value": "committed-by-pydanticai",
        }
    )

    agent: Agent[None, ModelDecision] = Agent(
        model,
        output_type=ModelDecision,
        system_prompt="You are a deterministic verification agent for the 00A-1 walking skeleton harness.",
    )

    @agent.tool_plain
    def check_inventory(item_id: str) -> Dict[str, Any]:
        """Read-only tool hooked to the agent."""
        return read_inventory_tool(item_id)

    return agent
