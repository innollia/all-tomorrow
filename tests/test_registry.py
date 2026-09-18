from all_tomorrow.contracts import Tool, Worker
from all_tomorrow.registry import CapabilityRegistry, SelectionRequest


def test_worker_selection_requires_capabilities_availability_and_privacy() -> None:
    registry = CapabilityRegistry()
    registry.register_worker(
        Worker(
            worker_id="offline-best",
            capabilities=frozenset({"coding", "repo_edit"}),
            status="offline",
            evaluation_score=1.0,
            privacy_tags=frozenset({"private_code"}),
        )
    )
    registry.register_worker(
        Worker(
            worker_id="available",
            capabilities=frozenset({"coding", "repo_edit"}),
            status="available",
            evaluation_score=0.8,
            privacy_tags=frozenset({"private_code"}),
        )
    )
    selected = registry.select_worker(
        SelectionRequest(
            required_capabilities=frozenset({"repo_edit"}),
            privacy_tags=frozenset({"private_code"}),
        )
    )
    assert selected.worker_id == "available"


def test_tool_selection_enforces_risk_ceiling() -> None:
    registry = CapabilityRegistry()
    registry.register_tool(
        Tool("repo.read", "git", frozenset({"repo"}), "low", status="available", latency_ms=10)
    )
    registry.register_tool(
        Tool("repo.delete", "git", frozenset({"repo"}), "critical", status="available", latency_ms=1)
    )
    selected = registry.select_tools(
        SelectionRequest(required_capabilities=frozenset({"repo"}), maximum_risk="high")
    )
    assert [tool.tool_id for tool in selected] == ["repo.read"]

