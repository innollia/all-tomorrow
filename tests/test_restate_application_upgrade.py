"""A different V2 Restate handler process resumes a V1 journal in place."""

import os
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import psycopg
import pytest


def _worker(
    version: int, *, crash_before_model_persist: bool = False,
    crash_after_model_persist: bool = False,
) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    if crash_before_model_persist:
        env["AT_TEST_CRASH_BEFORE_MODEL_PERSIST"] = "1"
    if crash_after_model_persist:
        env["AT_TEST_CRASH_AFTER_MODEL_PERSIST"] = "1"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", f"tests.support.restate_upgrade_v{version}:app", "--host", "127.0.0.1", "--port", "9088"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def _ready(process: subprocess.Popen[bytes]) -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(100):
            assert process.poll() is None, f"Restate upgrade worker exited with {process.returncode}"
            try:
                if client.get("http://127.0.0.1:9088/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
    pytest.fail("Restate upgrade worker did not start")


def test_v1_inflight_workflow_resumes_on_v2_code(tmp_path) -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")
    workflow_id = f"upgrade-{uuid4()}"
    correlation_id = f"origin-{uuid4()}"
    transient_id = f"transient-{uuid4()}"
    span_file = tmp_path / "restate-spans.jsonl"
    previous_span_path = os.environ.get("AT_TEST_OTEL_SPANS")
    previous_transient = os.environ.get("AT_TEST_TRANSIENT_CORR")
    os.environ["AT_TEST_OTEL_SPANS"] = str(span_file)
    os.environ["AT_TEST_TRANSIENT_CORR"] = transient_id
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS upgrade_probe (
                workflow_id TEXT PRIMARY KEY, model_calls INTEGER NOT NULL, finalized BOOLEAN NOT NULL
            )"""
        )

    old = _worker(1)
    new = None
    try:
        _ready(old)
        with httpx.Client(timeout=10) as client:
            registration = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9088", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text

        base = f"{ingress.rstrip('/')}/AllTomorrowUpgradeProbe/{workflow_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(
                f"{base}/run",
                json={"workflow_id": workflow_id, "correlation_id": correlation_id},
                timeout=60,
            ))
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM signal_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("V1 did not reach durable wait")
            for _ in range(100):
                if span_file.exists() and "restate_v1_wait_started" in span_file.read_text(encoding="utf-8"):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("V1 wait span was not exported before worker kill")
            old.kill()
            old.wait(timeout=5)
            new = _worker(2)
            _ready(new)
            approval = httpx.post(f"{base}/approve", json=True, timeout=20)
            assert approval.status_code == 200, approval.text
            completed = future.result(timeout=45)
        assert completed.status_code == 200, completed.text
        assert completed.json() == {
            "stock": 42, "approved": True, "schema": 2, "source": "v1-replayed"
        }
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT model_calls, finalized FROM upgrade_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert row == (1, True)
        assert old.pid != new.pid
        spans = [json.loads(line) for line in span_file.read_text(encoding="utf-8").splitlines()]
        relevant = [s for s in spans if s["name"] in ("restate_v1_wait_started", "restate_v2_recovered")]
        assert {s["name"] for s in relevant} == {"restate_v1_wait_started", "restate_v2_recovered"}
        assert len({s["pid"] for s in relevant}) == 2
        assert all(s["attributes"]["all_tomorrow.correlation_id"] == correlation_id for s in relevant)
        assert relevant[-1]["attributes"]["all_tomorrow.transient_caller_id"] == transient_id
    finally:
        if previous_span_path is None:
            os.environ.pop("AT_TEST_OTEL_SPANS", None)
        else:
            os.environ["AT_TEST_OTEL_SPANS"] = previous_span_path
        if previous_transient is None:
            os.environ.pop("AT_TEST_TRANSIENT_CORR", None)
        else:
            os.environ["AT_TEST_TRANSIENT_CORR"] = previous_transient
        for process in (old, new):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_model_reexecutes_when_v1_dies_before_journal_commit(tmp_path, monkeypatch) -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")
    workflow_id = f"model-before-{uuid4()}"
    monkeypatch.setenv("AT_TEST_OTEL_SPANS", str(tmp_path / "spans.jsonl"))
    monkeypatch.setenv("AT_TEST_TRANSIENT_CORR", f"transient-{uuid4()}")
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS upgrade_probe (
                workflow_id TEXT PRIMARY KEY, model_calls INTEGER NOT NULL, finalized BOOLEAN NOT NULL
            )"""
        )

    old = _worker(1, crash_before_model_persist=True)
    new = None
    try:
        _ready(old)
        registration = httpx.post(
            f"{admin.rstrip('/')}/deployments",
            json={"uri": "http://127.0.0.1:9088", "use_http_11": True}, timeout=10,
        )
        assert registration.status_code in (200, 201), registration.text
        base = f"{ingress.rstrip('/')}/AllTomorrowUpgradeProbe/{workflow_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(
                f"{base}/run",
                json={"workflow_id": workflow_id, "correlation_id": f"origin-{uuid4()}"},
                timeout=60,
            ))
            assert old.wait(timeout=20) == 78
            new = _worker(2)
            _ready(new)
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM signal_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("V2 did not resume the old workflow")
            approval = httpx.post(f"{base}/approve", json=True, timeout=20)
            assert approval.status_code == 200, approval.text
            completed = future.result(timeout=45)
        assert completed.status_code == 200, completed.text
        assert completed.json()["source"] == "v2"
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT model_calls, finalized FROM upgrade_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert row == (2, True)
    finally:
        for process in (old, new):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_model_result_replays_when_v1_dies_after_journal_commit(tmp_path, monkeypatch) -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not all((fixture_url, admin, ingress)):
        pytest.skip("Set AT_TEST_FIXTURE_URL, AT_TEST_RESTATE_ADMIN, AT_TEST_RESTATE_INGRESS")
    workflow_id = f"model-after-{uuid4()}"
    monkeypatch.setenv("AT_TEST_OTEL_SPANS", str(tmp_path / "spans.jsonl"))
    monkeypatch.setenv("AT_TEST_TRANSIENT_CORR", f"transient-{uuid4()}")
    with psycopg.connect(fixture_url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS upgrade_probe (
                workflow_id TEXT PRIMARY KEY, model_calls INTEGER NOT NULL, finalized BOOLEAN NOT NULL
            )"""
        )
    old = _worker(1, crash_after_model_persist=True)
    new = None
    try:
        _ready(old)
        registration = httpx.post(
            f"{admin.rstrip('/')}/deployments",
            json={"uri": "http://127.0.0.1:9088", "use_http_11": True}, timeout=10,
        )
        assert registration.status_code in (200, 201), registration.text
        base = f"{ingress.rstrip('/')}/AllTomorrowUpgradeProbe/{workflow_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(
                f"{base}/run",
                json={"workflow_id": workflow_id, "correlation_id": f"origin-{uuid4()}"},
                timeout=60,
            ))
            assert old.wait(timeout=20) == 79
            new = _worker(2)
            _ready(new)
            for _ in range(100):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM signal_probe WHERE workflow_id=%s", (workflow_id,)
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("V2 did not resume after persisted model result")
            approval = httpx.post(f"{base}/approve", json=True, timeout=20)
            assert approval.status_code == 200, approval.text
            completed = future.result(timeout=45)
        assert completed.status_code == 200, completed.text
        assert completed.json()["source"] == "v1-replayed"
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT model_calls, finalized FROM upgrade_probe WHERE workflow_id=%s", (workflow_id,)
            ).fetchone()
        assert row == (1, True)
    finally:
        for process in (old, new):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
