"""Real Restate cancellation of a waiting workflow."""

import os
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
import pytest


def test_cancel_waiting_workflow_prevents_later_mutation() -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")

    workflow_id = f"cancel-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS signal_effect_probe (workflow_id TEXT PRIMARY KEY)")

    worker = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.support.restate_signal_service:app", "--host", "127.0.0.1", "--port", "9085"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(timeout=10) as client:
            for _ in range(100):
                try:
                    if client.get("http://127.0.0.1:9085/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Restate signal service did not start")
            registration = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9085", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text

            sent = client.post(
                f"{ingress.rstrip('/')}/restate/send/AllTomorrowSignalProbe/{workflow_id}/run",
                json=workflow_id,
            )
            assert sent.status_code in (200, 202), sent.text
            invocation_id = sent.json()["invocationId"]
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM signal_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restate workflow did not enter wait")

            cancelled = client.patch(f"{admin.rstrip('/')}/invocations/{invocation_id}/cancel")
            assert cancelled.status_code in (200, 202), cancelled.text
            client.post(
                f"{ingress.rstrip('/')}/AllTomorrowSignalProbe/{workflow_id}/approve",
                json=True,
            )
            time.sleep(1)
            output = client.get(f"{ingress.rstrip('/')}/restate/output/{invocation_id}")
            assert output.status_code == 409, output.text
            assert output.json()["message"] == "cancelled"
        with psycopg.connect(fixture_url) as conn:
            applied = conn.execute(
                "SELECT COUNT(*) FROM signal_effect_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert applied == (0,)
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
