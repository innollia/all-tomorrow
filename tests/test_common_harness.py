"""Tests for 00A-1 Common Harness."""

import pytest

from all_tomorrow.harness import (
    BaselineMemoryAdapter,
    DuplicateMutationError,
    FailPoint,
    KillException,
    RetryMatrix,
    ScenarioId,
    ScenarioResult,
    ScenarioRunner,
    SideEffectFixtureStore,
)


@pytest.mark.asyncio
async def test_canonical_scenarios_d01_to_d12():
    """Verify that all D01-D12 canonical scenarios execute cleanly with BaselineMemoryAdapter."""
    adapter = BaselineMemoryAdapter(candidate_name="baseline-reference", version="1.0.0")
    runner = ScenarioRunner(adapter=adapter)

    results = await runner.run_all()
    assert len(results) == 12

    for res in results:
        assert isinstance(res, ScenarioResult)
        assert res.passed is True, f"Scenario {res.scenario_id} failed: {res.recovery_notes}"
        assert res.candidate == "baseline-reference"
        assert res.adapter_loc is None
        assert res.processes_required is None
        if res.scenario_id == "D10":
            assert res.version == "2.0.0"
        else:
            assert res.version == "1.0.0"


@pytest.mark.asyncio
async def test_side_effect_fixture_strict_idempotency():
    """Verify that SideEffectFixtureStore prevents illegal conflicting mutations under strict mode."""
    store = SideEffectFixtureStore(strict_idempotency=True)

    # First call
    rec1 = store.record_mutation("key-abc", "val-1")
    assert rec1.call_count == 1
    assert rec1.application_count == 1
    assert rec1.committed_value == "val-1"

    # Second call with same value (reconciliation)
    rec2 = store.record_mutation("key-abc", "val-1")
    assert rec2.call_count == 2
    assert rec2.application_count == 1
    assert rec2.committed_value == "val-1"

    # Third call with conflicting value -> must raise DuplicateMutationError
    with pytest.raises(DuplicateMutationError):
        store.record_mutation("key-abc", "conflicting-val")


def test_retry_matrix_single_ownership():
    """Verify that each critical failure class is assigned to exactly one retry layer owner."""
    matrix = RetryMatrix.standard_harness_matrix()

    # Rate limiting owned by gateway
    assert matrix.validate_single_ownership("http_429") is True
    assert matrix.validate_single_ownership("rate_limit") is True

    # Process crash / worker recovery owned by durable backend
    assert matrix.validate_single_ownership("process_crash") is True

    # Pydantic validation owned by pydantic_ai
    assert matrix.validate_single_ownership("validation_error") is True


@pytest.mark.asyncio
async def test_individual_scenarios():
    """Verify key individual scenarios in isolation."""
    adapter = BaselineMemoryAdapter()
    runner = ScenarioRunner(adapter=adapter)

    # Test D01
    d01_res = await runner.run_d01()
    assert d01_res.scenario_id == "D01"
    assert d01_res.passed is True

    # Test D04 (Kill immediately after side effect)
    d04_res = await runner.run_d04()
    assert d04_res.scenario_id == "D04"
    assert d04_res.passed is True

    # Test D06 (Signal wait & resume)
    d06_res = await runner.run_d06()
    assert d06_res.scenario_id == "D06"
    assert d06_res.passed is True

    # Test D08 (Cancellation)
    d08_res = await runner.run_d08()
    assert d08_res.scenario_id == "D08"
    assert d08_res.passed is True

    # Test D11 (Distinct runs for same work)
    d11_res = await runner.run_d11()
    assert d11_res.scenario_id == "D11"
    assert d11_res.passed is True

    # Test D12 (OTel correlation survives recovery)
    d12_res = await runner.run_d12()
    assert d12_res.scenario_id == "D12"
    assert d12_res.passed is True
