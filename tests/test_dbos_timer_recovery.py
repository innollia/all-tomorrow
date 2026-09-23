"""DBOS durable timer retains its original due time across a worker kill."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest


def test_timer_uses_original_due_time_after_restart() -> None:
    if not os.environ.get("AT_TEST_POSTGRES_URL"):
        pytest.skip("Set AT_TEST_POSTGRES_URL")
    worker = Path(__file__).parent / "support" / "dbos_timer_worker.py"
    env = os.environ.copy()
    env["AT_TEST_WORKFLOW_ID"] = f"timer-{uuid4()}"
    env["AT_TEST_PHASE"] = "start"
    first = subprocess.Popen(
        [sys.executable, str(worker)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert first.stdout is not None
        marker = first.stdout.readline().strip()
        assert marker.startswith("started="), marker
        started = float(marker.split()[0].split("=")[1])
        # The event is recorded before DBOS.sleep; let the sleep command itself
        # enter the durable journal before killing the process.
        time.sleep(1.5)
        first.kill()
        first.wait(timeout=5)
        time.sleep(3)

        env["AT_TEST_PHASE"] = "recover"
        second = subprocess.run([sys.executable, str(worker)], env=env, capture_output=True, text=True, timeout=30)
        assert second.returncode == 0, (second.stdout, second.stderr)
        launched = float(second.stdout.strip().split()[0].split("=")[1])
        finished = float(second.stdout.strip().split()[1].split("=")[1])
        assert finished >= started + 5
        assert finished < launched + 3, (started, launched, finished)
        assert marker.split("pid=")[1] != second.stdout.split("pid=")[1].strip()
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=5)
