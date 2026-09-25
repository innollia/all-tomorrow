"""A genuinely different V2 application resumes a V1 DBOS workflow."""

import os
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


def test_old_inflight_workflow_completes_on_new_application_code(tmp_path: Path) -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL")
    workflow_id = f"upgrade-{uuid4()}"
    support = Path(__file__).parent / "support"
    env = os.environ.copy()
    env["AT_TEST_WORKFLOW_ID"] = workflow_id
    env["AT_TEST_ORIGINAL_CORR"] = f"origin-{uuid4()}"
    env["AT_TEST_TRANSIENT_CORR"] = f"transient-{uuid4()}"
    span_file = tmp_path / "spans.jsonl"
    env["AT_TEST_OTEL_SPANS"] = str(span_file)
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS upgrade_probe (
                workflow_id TEXT PRIMARY KEY,
                model_calls INTEGER NOT NULL,
                finalized BOOLEAN NOT NULL
            )"""
        )

    old = subprocess.Popen(
        [sys.executable, str(support / "dbos_upgrade_v1.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert old.stdout is not None
        marker = old.stdout.readline().strip()
        assert marker.startswith("v1_waiting_pid="), (marker, old.stderr.read() if old.stderr else "")
        old.kill()
        old.wait(timeout=10)
        new = subprocess.run(
            [sys.executable, str(support / "dbos_upgrade_v2.py")],
            env=env, capture_output=True, text=True, timeout=45,
        )
        assert new.returncode == 0, (new.stdout, new.stderr)
        assert "'schema': 2" in new.stdout
        assert "'source': 'v1-replayed'" in new.stdout
        assert "'stock': 42" in new.stdout
        assert marker.removeprefix("v1_waiting_pid=") != new.stdout.split("v2_pid=")[1].split()[0]
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT model_calls, finalized FROM upgrade_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert row == (1, True)
        spans = [json.loads(line) for line in span_file.read_text(encoding="utf-8").splitlines()]
        relevant = [s for s in spans if s["name"] in ("v1_wait_started", "v2_recovered")]
        assert {s["name"] for s in relevant} == {"v1_wait_started", "v2_recovered"}
        assert len({s["pid"] for s in relevant}) == 2
        assert all(s["attributes"]["all_tomorrow.correlation_id"] == env["AT_TEST_ORIGINAL_CORR"] for s in relevant)
        assert relevant[-1]["attributes"]["all_tomorrow.transient_caller_id"] == env["AT_TEST_TRANSIENT_CORR"]
    finally:
        if old.poll() is None:
            old.kill()
            old.wait(timeout=10)
