"""Real process boundary test for a DBOS workflow on PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


def test_external_effect_reconciles_after_worker_process_death() -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL for process recovery")
    if system_url == fixture_url:
        pytest.fail("DBOS system state and external fixture must use separate databases")

    workflow_id = f"crash-probe-{uuid4()}"
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

    env["AT_TEST_PHASE"] = "recover"
    second = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert "committed" in second.stdout
    assert first.stdout.splitlines()[0].startswith("worker_pid=")
    assert second.stdout.splitlines()[0].startswith("worker_pid=")
    assert first.stdout.splitlines()[0] != second.stdout.splitlines()[0]

    with psycopg.connect(fixture_url) as conn:
        row = conn.execute(
            "SELECT call_count, application_count, committed_value FROM crash_probe WHERE idempotency_key=%s",
            (workflow_id,),
        ).fetchone()
    assert row is not None
    # The first worker exited before the step journaled; recovery must call
    # the fixture again and reconcile the already committed idempotency key.
    assert row[0] == 2
    assert row[1:] == (1, "committed")
