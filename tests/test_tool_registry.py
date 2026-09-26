from __future__ import annotations

import pytest

from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.ports.tools import SideEffectClass, ToolDescriptor
from all_tomorrow.ports.workers import WorkerDescriptor
from all_tomorrow.tools.registry import ToolRegistry, WorkerRegistry


class TestToolRegistry:
    """Requirements S0-00B5-01 and S0-00B5-04."""

    def test_canonical_tool_registration_and_lookup(self) -> None:
        """S0-00B5-01: Canonical descriptors owned by All Tomorrow, not transport gateway."""
        registry = ToolRegistry()
        tool = ToolDescriptor(
            tool_id="search_codebase",
            version="1.0.0",
            source_owner="all-tomorrow",
            capabilities=frozenset({"code_search", "read"}),
            side_effect_class=SideEffectClass.READ_ONLY,
            required_authority="repo.read",
        )
        registry.register(tool)
        assert registry.get("search_codebase") == tool

        # Duplicate same-version registration fails
        with pytest.raises(InvariantViolationError, match="already registered"):
            registry.register(tool)

    def test_zero_core_name_branching_for_tools_and_workers(self) -> None:
        """S0-00B5-04: Capability-based discovery works purely on sets without hardcoded name branches."""
        tool_reg = ToolRegistry()
        worker_reg = WorkerRegistry()

        # Register arbitrarily named tools
        t1 = ToolDescriptor(
            tool_id="custom_scanner_x",
            version="1.0.0",
            source_owner="third_party",
            capabilities=frozenset({"ast_analysis", "read"}),
            side_effect_class=SideEffectClass.READ_ONLY,
            required_authority="ast.read",
        )
        t2 = ToolDescriptor(
            tool_id="custom_generator_y",
            version="2.1.0",
            source_owner="third_party",
            capabilities=frozenset({"ast_analysis", "code_generation", "write"}),
            side_effect_class=SideEffectClass.IDEMPOTENT_REPLAY,
            required_authority="ast.write",
        )
        tool_reg.register(t1)
        tool_reg.register(t2)

        # Discovery by capability (no 'if tool_id == ...')
        matching_tools = tool_reg.find_by_capabilities(frozenset({"ast_analysis"}))
        assert len(matching_tools) == 2

        code_gen_tools = tool_reg.find_by_capabilities(frozenset({"code_generation"}))
        assert len(code_gen_tools) == 1
        assert code_gen_tools[0].tool_id == "custom_generator_y"

        # Register arbitrarily named workers
        w1 = WorkerDescriptor(
            worker_id="remote_node_alpha",
            version="1.0.0",
            capabilities=frozenset({"docker_run", "cuda"}),
            health_status="healthy",
        )
        w2 = WorkerDescriptor(
            worker_id="remote_node_beta",
            version="1.0.0",
            capabilities=frozenset({"docker_run"}),
            health_status="degraded",
        )
        worker_reg.register(w1)
        worker_reg.register(w2)

        # Discovery by capability and health
        docker_workers = worker_reg.find_by_capabilities(frozenset({"docker_run"}), only_healthy=True)
        assert len(docker_workers) == 1
        assert docker_workers[0].worker_id == "remote_node_alpha"
