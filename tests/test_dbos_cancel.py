"""Live DBOS cancellation of a waiting workflow."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


def test_cancel_waiting_workflow_persists_cancelled_state() -> None:
    if not os.environ.get("AT_TEST_POSTGRES_URL"):
        pytest.skip("Set AT_TEST_POSTGRES_URL")
    worker = Path(__file__).parent / "support" / "dbos_signal_worker.py"
    env = os.environ.copy()
    env["AT_TEST_WORKFLOW_ID"] = f"cancel-{uuid4()}"
    env["AT_TEST_PHASE"] = "wait"
    first = subprocess.Popen(
        [sys.executable, str(worker)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert first.stdout is not None
        marker = first.stdout.readline().strip()
        assert marker.startswith("waiting_pid="), marker
        env["AT_TEST_PHASE"] = "cancel"
        cancelled = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=30)
        assert cancelled.returncode == 0, (cancelled.stdout, cancelled.stderr)
        assert "CANCELLED" in cancelled.stdout.upper(), cancelled.stdout
        assert "mutated=None" in cancelled.stdout, cancelled.stdout
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=5)
