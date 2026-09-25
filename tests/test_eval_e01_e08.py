"""Verification for D-EVAL-01: E-01 through E-08 expected property evaluations."""

import json
from pathlib import Path
import pytest

from all_tomorrow.eval.runner import run_evaluation_suite


@pytest.mark.asyncio
async def test_d_eval_01_all_cases_pass_and_generate_artifact(tmp_path: Path) -> None:
    """D-EVAL-01: Run deterministic contract cases E-01~E-08 and verify Stage 0 gate."""
    # Also write to repository artifact location
    repo_artifact = Path(".artifacts/eval/eval_report.json")
    test_artifact = tmp_path / "eval_report.json"

    report = await run_evaluation_suite(artifact_path=test_artifact)

    # Copy to repo artifact path as verified record
    repo_artifact.parent.mkdir(parents=True, exist_ok=True)
    repo_artifact.write_text(test_artifact.read_text(encoding="utf-8"), encoding="utf-8")

    # Gate verification
    assert report.total_cases == 8
    assert report.passed_cases == 8
    assert report.failed_cases == 0
    assert report.hard_gate_failures == 0
    assert report.gate_cleared is True

    # Verify hard gate cases specifically
    hard_cases = {r.id: r for r in report.results if r.is_hard_gate}
    assert set(hard_cases.keys()) == {"E-05", "E-06", "E-07", "E-08"}
    for case_id, res in hard_cases.items():
        assert res.passed is True, f"Hard gate case {case_id} failed: {res.details}"

    # Verify persisted artifact file
    assert test_artifact.exists()
    saved_data = json.loads(test_artifact.read_text(encoding="utf-8"))
    assert saved_data["gate_cleared"] is True
    assert len(saved_data["results"]) == 8
