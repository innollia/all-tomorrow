"""Restate D09 probe with a real server outage and same-state restart."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest


ADMIN = "http://127.0.0.1:9070"
INGRESS = "http://127.0.0.1:8080"


def _wait_http(url: str, expected: int = 200) -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(150):
            try:
                if client.get(url).status_code == expected:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
    pytest.fail(f"Service did not become ready: {url}")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def test_server_outage_then_reconnect_preserves_waiting_workflow(tmp_path: Path) -> None:
    server_bin = os.environ.get("AT_TEST_RESTATE_SERVER_BIN")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if os.environ.get("AT_TEST_ALLOW_RESTATE_STOP") != "1":
        pytest.skip("Set AT_TEST_ALLOW_RESTATE_STOP=1 only in the disposable WSL lab")
    if not server_bin or fixture_url != "postgresql:///at_external_fixture":
        pytest.fail("Dedicated server binary and named disposable fixture DB are required")
    if not Path(server_bin).is_file():
        pytest.fail("Restate Server binary not found")
    try:
        httpx.get(f"{ADMIN}/health", timeout=1)
    except httpx.TransportError:
        pass
    else:
        pytest.fail("The default Restate ports must be free before this isolated outage test")

    workflow_id = f"server-outage-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS signal_effect_probe (workflow_id TEXT PRIMARY KEY)")

    base_dir = tmp_path / "restate-data"

    def start_server() -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [server_bin, "--base-dir", str(base_dir), "--no-logo"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    server = start_server()
    worker = None
    try:
        _wait_http(f"{ADMIN}/health")
        worker = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.support.restate_signal_service:app", "--host", "127.0.0.1", "--port", "9085"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http("http://127.0.0.1:9085/health")
        with httpx.Client(timeout=10) as client:
            registration = client.post(
                f"{ADMIN}/deployments",
                json={"uri": "http://127.0.0.1:9085", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text
            sent = client.post(
                f"{INGRESS}/restate/send/AllTomorrowSignalProbe/{workflow_id}/run",
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
            pytest.fail("Workflow never entered durable wait")

        _stop(server)
        with pytest.raises(httpx.TransportError):
            httpx.get(f"{ADMIN}/health", timeout=2)

        server = start_server()
        _wait_http(f"{ADMIN}/health")
        signal = httpx.post(
            f"{INGRESS}/AllTomorrowSignalProbe/{workflow_id}/approve", json=True, timeout=20
        )
        assert signal.status_code == 200, signal.text
        attached = httpx.get(f"{INGRESS}/restate/attach/{invocation_id}", timeout=30)
        assert attached.status_code == 200, attached.text
        assert attached.json() is True
        with psycopg.connect(fixture_url) as conn:
            applied = conn.execute(
                "SELECT COUNT(*) FROM signal_effect_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert applied == (1,)
    finally:
        if worker is not None:
            _stop(worker)
        _stop(server)
