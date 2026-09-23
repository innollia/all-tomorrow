"""Real Restate worker death and external idempotency recovery on Linux."""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import psycopg
import pytest


def _start_worker(crash: bool) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["AT_TEST_RESTATE_CRASH"] = "1" if crash else "0"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.support.restate_crash_service:app", "--host", "127.0.0.1", "--port", "9083"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _wait_worker() -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(100):
            try:
                if client.get("http://127.0.0.1:9083/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
    pytest.fail("Restate crash probe worker did not become ready")


def test_external_effect_reconciles_after_restate_worker_death() -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")

    workflow_id = f"restate-crash-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS crash_probe (
                idempotency_key TEXT PRIMARY KEY,
                call_count INTEGER NOT NULL,
                application_count INTEGER NOT NULL,
                committed_value TEXT NOT NULL
            )"""
        )

    first = _start_worker(crash=True)
    second = None
    try:
        _wait_worker()
        with httpx.Client(timeout=10) as client:
            registered = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9083", "use_http_11": True},
            )
            assert registered.status_code in (200, 201), registered.text

        url = f"{ingress.rstrip('/')}/AllTomorrowCrashProbe/{workflow_id}/run"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(url, json=workflow_id, timeout=60))
            assert first.wait(timeout=25) == 77
            second = _start_worker(crash=False)
            _wait_worker()
            response = future.result(timeout=45)
        assert response.status_code == 200, response.text
        assert response.json() == "committed"
        assert first.pid != second.pid

        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT call_count, application_count FROM crash_probe WHERE idempotency_key=%s",
                (workflow_id,),
            ).fetchone()
        assert row == (2, 1)
    finally:
        for worker in (first, second):
            if worker is not None and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
