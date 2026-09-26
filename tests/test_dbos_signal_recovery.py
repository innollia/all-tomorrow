"""Live DBOS durable wait, killed worker, signal and completion."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


def test_signal_reaches_waiting_workflow_after_worker_restart() -> None:
    if not os.environ.get("AT_TEST_POSTGRES_URL"):
        pytest.skip("Set AT_TEST_POSTGRES_URL")
    worker = Path(__file__).parent / "support" / "dbos_signal_worker.py"
    env = os.environ.copy()
    env["AT_TEST_WORKFLOW_ID"] = f"signal-{uuid4()}"
    env["AT_TEST_PHASE"] = "wait"
    first = subprocess.Popen(
        [sys.executable, str(worker)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert first.stdout is not None
        marker = first.stdout.readline().strip()
        assert marker.startswith("waiting_pid="), marker
        first.kill()
        first.wait(timeout=10)

        env["AT_TEST_PHASE"] = "resume"
        second = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=45)
        assert second.returncode == 0, (second.stdout, second.stderr)
        assert "approved=True" in second.stdout
        assert marker.removeprefix("waiting_pid=") != second.stdout.split("resumed_pid=")[1].split()[0]
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=10)
