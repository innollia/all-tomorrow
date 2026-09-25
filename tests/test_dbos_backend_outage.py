"""DBOS D09 probe that deliberately stops the dedicated local PostgreSQL cluster."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


def _pg_control(action: str) -> None:
    result = subprocess.run(["pg_ctlcluster", "16", "main", action], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (action, result.stdout, result.stderr)


def test_outage_then_reconnect_preserves_one_external_application() -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if os.environ.get("AT_TEST_ALLOW_POSTGRES_STOP") != "1":
        pytest.skip("Set AT_TEST_ALLOW_POSTGRES_STOP=1 only in the disposable WSL lab")
    if system_url != "postgresql:///at_dbos_probe" or fixture_url != "postgresql:///at_external_fixture":
        pytest.fail("Outage probe is restricted to the named disposable local lab databases")

    workflow_id = f"outage-{uuid4()}"
    worker = Path(__file__).parent / "support" / "dbos_crash_worker.py"
    env = os.environ.copy()
    env["AT_TEST_WORKFLOW_ID"] = workflow_id
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS crash_probe (
                idempotency_key TEXT PRIMARY KEY,
                call_count INTEGER NOT NULL,
                application_count INTEGER NOT NULL,
                committed_value TEXT NOT NULL
            )"""
        )

    env["AT_TEST_PHASE"] = "crash"
    first = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
    assert first.returncode == 77, (first.stdout, first.stderr)

    _pg_control("stop")
    try:
        env["AT_TEST_PHASE"] = "recover"
        try:
            unavailable = subprocess.run(
                [sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=12
            )
        except subprocess.TimeoutExpired:
            failure_observed = True
        else:
            failure_observed = unavailable.returncode != 0 and "committed" not in unavailable.stdout
        assert failure_observed, "Recovery unexpectedly succeeded while PostgreSQL was stopped"
    finally:
        _pg_control("start")

    recovered = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
    assert recovered.returncode == 0, (recovered.stdout, recovered.stderr)
    assert "committed" in recovered.stdout
    with psycopg.connect(fixture_url) as conn:
        row = conn.execute(
            "SELECT call_count, application_count FROM crash_probe WHERE idempotency_key=%s", (workflow_id,)
        ).fetchone()
    assert row == (2, 1)
