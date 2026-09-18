from pathlib import Path

import pytest

from all_tomorrow.contracts import ContractError
from all_tomorrow.pipeline import load_pipeline, parse_pipeline


def test_loads_demo_yaml() -> None:
    spec = load_pipeline(Path("pipelines/demo.yaml"))
    assert spec.identity == "demo_request@1"
    assert [step.id for step in spec.steps] == ["resolve_project", "confirm_project", "finish"]


def test_retry_attempts_must_be_positive() -> None:
    with pytest.raises(ContractError, match="max_retries"):
        parse_pipeline(
            {
                "id": "bad",
                "version": 1,
                "status": "active",
                "steps": [{"id": "x", "type": "test", "retry": {"max_attempts": 0}}],
            }
        )

