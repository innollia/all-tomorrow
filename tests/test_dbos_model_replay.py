"""DBOS D02/D03 narrow probes with a real PydanticAI TestModel call."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


@pytest.mark.parametrize(
    ("fail_point", "exit_code", "expected_model_calls"),
    [("before_model_persist", 78, 2), ("after_model_persist", 79, 1)],
)
def test_model_step_replay_across_worker_death(
    fail_point: str, exit_code: int, expected_model_calls: int
) -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL")
    if system_url == fixture_url:
        pytest.fail("DBOS state and model call counter must use separate databases")

    workflow_id = f"model-{uuid4()}"
    worker = Path(__file__).parent / "support" / "dbos_model_crash_worker.py"
    env = os.environ.copy()
    env.update(AT_TEST_WORKFLOW_ID=workflow_id, AT_TEST_FAIL_POINT=fail_point)
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS model_probe (
                workflow_id TEXT PRIMARY KEY, model_call_count INTEGER NOT NULL
            )"""
        )

    env["AT_TEST_PHASE"] = "crash"
    first = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
    assert first.returncode == exit_code, (first.stdout, first.stderr)

    env["AT_TEST_PHASE"] = "recover"
    second = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert "stock_confirmed=42" in second.stdout
    assert first.stdout.splitlines()[0] != second.stdout.splitlines()[0]

    with psycopg.connect(fixture_url) as conn:
        calls = conn.execute("SELECT model_call_count FROM model_probe WHERE workflow_id=%s", (workflow_id,)).fetchone()
    assert calls == (expected_model_calls,)
