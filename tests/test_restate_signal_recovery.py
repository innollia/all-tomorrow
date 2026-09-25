"""Restate durable promise after worker death and external signal."""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import psycopg
import pytest


def _worker() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.support.restate_signal_service:app", "--host", "127.0.0.1", "--port", "9085"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ready() -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(100):
            try:
                if client.get("http://127.0.0.1:9085/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
    pytest.fail("Restate signal service did not start")


def test_signal_after_worker_restart() -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")

    workflow_id = f"signal-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS signal_effect_probe (workflow_id TEXT PRIMARY KEY)")

    first = _worker()
    second = None
    try:
        _ready()
        with httpx.Client(timeout=10) as client:
            registration = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9085", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text

        base = f"{ingress.rstrip('/')}/AllTomorrowSignalProbe/{workflow_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(f"{base}/run", json=workflow_id, timeout=60))
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM signal_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restate workflow never entered the wait section")

            first.kill()
            first.wait(timeout=5)
            second = _worker()
            _ready()
            signal = httpx.post(f"{base}/approve", json=True, timeout=20)
            assert signal.status_code == 200, signal.text
            result = future.result(timeout=45)
        assert result.status_code == 200, result.text
        assert result.json() is True
        assert first.pid != second.pid
        with psycopg.connect(fixture_url) as conn:
            applied = conn.execute(
                "SELECT COUNT(*) FROM signal_effect_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert applied == (1,)
    finally:
        for worker in (first, second):
            if worker is not None and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
