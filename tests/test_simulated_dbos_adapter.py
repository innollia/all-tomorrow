"""Contract exercise for an in-memory adapter, not a DBOS runtime test."""

import pytest

from all_tomorrow.adapters.simulated_dbos_adapter import SimulatedDBOSAdapter
from all_tomorrow.harness import ScenarioRunner, SideEffectFixtureStore


@pytest.mark.asyncio
async def test_simulated_adapter_canonical_scenarios_d01_to_d12():
    """Exercise the harness against an in-memory DBOS-shaped adapter."""
    adapter = SimulatedDBOSAdapter()
    store = SideEffectFixtureStore(strict_idempotency=True)
    runner = ScenarioRunner(adapter=adapter, store=store)

    results = await runner.run_all()
    assert len(results) == 12

    for res in results:
        assert res.passed is True, f"Simulation scenario {res.scenario_id} failed: {res.recovery_notes}"
        assert res.candidate == "dbos-simulation"
        if res.scenario_id == "D10":
            assert res.version == "2.0.0"
        else:
            assert res.version == "simulation"


@pytest.mark.asyncio
async def test_simulated_workflow_id_determinism():
    """Verify only the proposed identity mapping in the simulation."""
    adapter = SimulatedDBOSAdapter()
    from all_tomorrow.harness.types import ExecutionIdentity

    id1 = ExecutionIdentity(work_id="work-abc", run_id="run-001")
    id2 = ExecutionIdentity(work_id="work-abc", run_id="run-001")
    id3 = ExecutionIdentity(work_id="work-abc", run_id="run-002")

    assert adapter._workflow_id(id1) == adapter._workflow_id(id2)
    assert adapter._workflow_id(id1) != adapter._workflow_id(id3)
