"""Restate timer retains its due time while its handler process is absent."""

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
        [sys.executable, "-m", "uvicorn", "tests.support.restate_timer_service:app", "--host", "127.0.0.1", "--port", "9086"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ready() -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(100):
            try:
                if client.get("http://127.0.0.1:9086/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
    pytest.fail("Restate timer service did not start")


def test_timer_survives_worker_death() -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")

    workflow_id = f"timer-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS timer_probe (workflow_id TEXT PRIMARY KEY, started DOUBLE PRECISION NOT NULL)")

    first = _worker()
    second = None
    try:
        _ready()
        with httpx.Client(timeout=10) as client:
            registration = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9086", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text

        url = f"{ingress.rstrip('/')}/AllTomorrowTimerProbe/{workflow_id}/run"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(url, json=workflow_id, timeout=60))
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    marker = conn.execute(
                        "SELECT started FROM timer_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if marker:
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restate timer was not reached")
            started = marker[0]
            time.sleep(1.5)
            first.kill()
            first.wait(timeout=5)
            time.sleep(3)
            second = _worker()
            _ready()
            ready_at = time.time()
            result = future.result(timeout=30)
        assert result.status_code == 200, result.text
        finished = result.json()
        assert finished >= started + 5
        assert finished < ready_at + 3, (started, ready_at, finished)
        assert first.pid != second.pid
    finally:
        for worker in (first, second):
            if worker is not None and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
