"""One canonical typed D01 payload and assertions against both live candidates."""

import json
import base64
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import psycopg
import pytest

from all_tomorrow.harness.types import ExecutionIdentity, FailPoint, HarnessInput, HarnessOutput, TraceContext


def _payload(candidate: str, *, wait_for_signal: bool = False, fail_point: FailPoint = FailPoint.NONE) -> dict:
    run_id = str(uuid4())
    return {
        "input": HarnessInput(
            task_name="Check inventory and commit a value",
            query_item_id="item-01",
            mutation_key=f"d01-{candidate}-{run_id}",
            mutation_value="d01-committed",
            metadata={"privacy_canary": f"payload-canary-{uuid4().hex}"},
            wait_for_signal_name="approval" if wait_for_signal else None,
            injected_fail_point=fail_point,
        ).model_dump(mode="json"),
        "identity": ExecutionIdentity(work_id="work-d01", run_id=run_id).model_dump(mode="json"),
        "trace": TraceContext(
            trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
        ).model_dump(mode="json"),
    }


def _assert_common_result(fixture_url: str, payload: dict, raw: dict, *, expected_calls: int = 1) -> None:
    result = HarnessOutput.model_validate(raw)
    assert result.task_name == payload["input"]["task_name"]
    assert result.read_item_data == {
        "item_id": "item-01", "name": "Inventory item item-01", "read_only": True, "stock": 42,
    }
    assert result.model_decision is not None
    assert result.model_decision.stock_confirmed == 42
    assert result.mutation_committed is True
    assert result.mutation_value == "d01-committed"
    assert result.execution_identity == ExecutionIdentity.model_validate(payload["identity"])
    assert result.correlation_id == payload["trace"]["correlation_id"]
    if payload["input"]["wait_for_signal_name"]:
        assert result.signal_received_payload == {"approved": True}
    with psycopg.connect(fixture_url) as conn:
        row = conn.execute(
            "SELECT call_count, application_count, committed_value FROM common_mutation_probe WHERE idempotency_key=%s",
            (payload["input"]["mutation_key"],),
        ).fetchone()
    assert row == (expected_calls, 1, "d01-committed")


def _prepare_fixture(fixture_url: str) -> None:
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS common_mutation_probe (
                idempotency_key TEXT PRIMARY KEY,
                call_count INTEGER NOT NULL,
                application_count INTEGER NOT NULL,
                committed_value TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS common_followup_probe (idempotency_key TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS common_upgrade_probe (idempotency_key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS common_model_probe (idempotency_key TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS common_wait_probe (workflow_id TEXT PRIMARY KEY, waiting BOOLEAN NOT NULL)"
        )


def test_dbos_live_common_d01() -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL")
    _prepare_fixture(fixture_url)
    payload = _payload("dbos")
    env = os.environ.copy()
    env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
    run = subprocess.run(
        [sys.executable, "-m", "tests.support.dbos_common_worker"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    raw = json.loads(run.stdout.strip().splitlines()[-1])
    _assert_common_result(fixture_url, payload, raw)
    canary = payload["input"]["metadata"]["privacy_canary"]
    assert canary not in run.stdout + run.stderr
    workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"
    with psycopg.connect(system_url) as conn:
        state = conn.execute(
            "SELECT status FROM dbos.workflow_status WHERE workflow_uuid=%s", (workflow_id,)
        ).fetchone()
        steps = conn.execute(
            "SELECT function_name FROM dbos.operation_outputs WHERE workflow_uuid=%s", (workflow_id,)
        ).fetchall()
        encoded_input = conn.execute(
            "SELECT inputs FROM dbos.workflow_input WHERE workflow_uuid=%s", (workflow_id,)
        ).fetchone()
    assert state == ("SUCCESS",)
    assert len(steps) == 3, steps
    assert encoded_input is not None
    assert canary.encode() in base64.b64decode(encoded_input[0])
    second_payload = _payload("dbos")
    env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(second_payload)
    second = subprocess.run(
        [sys.executable, "-m", "tests.support.dbos_common_worker"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert second.returncode == 0, second.stderr[-2000:]
    _assert_common_result(fixture_url, second_payload, json.loads(second.stdout.strip().splitlines()[-1]))
    second_workflow_id = f"{second_payload['identity']['work_id']}:{second_payload['identity']['run_id']}"
    assert second_workflow_id != workflow_id
    with psycopg.connect(system_url) as conn:
        states = conn.execute(
            "SELECT workflow_uuid, status FROM dbos.workflow_status WHERE workflow_uuid IN (%s, %s)",
            (workflow_id, second_workflow_id),
        ).fetchall()
    assert set(states) == {(workflow_id, "SUCCESS"), (second_workflow_id, "SUCCESS")}


def test_restate_live_common_d01() -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not fixture_url or not admin or not ingress:
        pytest.skip("Set fixture, Restate admin and ingress URLs")
    _prepare_fixture(fixture_url)
    payload = _payload("restate")
    worker = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.support.restate_common_service:app", "--host", "127.0.0.1", "--port", "9093"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(timeout=5) as client:
            for _ in range(300):
                assert worker.poll() is None, f"Restate D01 worker exited {worker.returncode}"
                try:
                    if client.get("http://127.0.0.1:9093/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Restate D01 worker did not start")
            registered = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9093", "use_http_11": True},
            )
            assert registered.status_code in (200, 201), registered.text
        workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"
        completed = httpx.post(
            f"{ingress.rstrip('/')}/AllTomorrowCommonD01/{workflow_id}/run",
            json=payload, timeout=30,
        )
        assert completed.status_code == 200, completed.text
        _assert_common_result(fixture_url, payload, completed.json())
        invocation_id = completed.headers["x-restate-id"]
        persisted = httpx.get(f"{ingress.rstrip('/')}/restate/output/{invocation_id}", timeout=10)
        assert persisted.status_code == 200, persisted.text
        assert persisted.json() == completed.json()
        second_payload = _payload("restate")
        second_workflow_id = f"{second_payload['identity']['work_id']}:{second_payload['identity']['run_id']}"
        second = httpx.post(
            f"{ingress.rstrip('/')}/AllTomorrowCommonD01/{second_workflow_id}/run",
            json=second_payload, timeout=30,
        )
        assert second.status_code == 200, second.text
        _assert_common_result(fixture_url, second_payload, second.json())
        assert second.headers["x-restate-id"] != invocation_id
        second_persisted = httpx.get(
            f"{ingress.rstrip('/')}/restate/output/{second.headers['x-restate-id']}", timeout=10,
        )
        assert second_persisted.status_code == 200, second_persisted.text
        assert second_persisted.json() == second.json()
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)


def test_dbos_live_common_d06_wait_restart_signal(tmp_path) -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL")
    _prepare_fixture(fixture_url)
    payload = _payload("dbos-wait", wait_for_signal=True)
    env = os.environ.copy()
    env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
    env["AT_TEST_COMMON_PHASE"] = "wait"
    span_file = tmp_path / "dbos-common-spans.jsonl"
    env["AT_TEST_OTEL_SPANS"] = str(span_file)
    first = subprocess.Popen(
        [sys.executable, "-m", "tests.support.dbos_common_worker"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert first.stdout is not None
        marker = first.stdout.readline().strip()
        assert marker.startswith("waiting_pid="), marker
        for _ in range(300):
            if span_file.exists() and "common_dbos_wait_started" in span_file.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        else:
            pytest.fail("DBOS wait span was not exported before worker kill")
        first.kill()
        first.wait(timeout=10)
        env["AT_TEST_COMMON_PHASE"] = "resume"
        second = subprocess.run(
            [sys.executable, "-m", "tests.support.dbos_common_worker"],
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert second.returncode == 0, second.stderr[-2000:]
        raw = json.loads(second.stdout.strip().splitlines()[-1])
        _assert_common_result(fixture_url, payload, raw)
        resumed_pid = second.stdout.split("resumed_pid=")[1].splitlines()[0]
        assert marker.removeprefix("waiting_pid=") != resumed_pid
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT call_count, application_count FROM common_mutation_probe WHERE idempotency_key=%s",
                (payload["input"]["mutation_key"],),
            ).fetchone()
        assert row == (1, 1)
        workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"
        with psycopg.connect(system_url) as conn:
            status = conn.execute(
                "SELECT status FROM dbos.workflow_status WHERE workflow_uuid=%s", (workflow_id,)
            ).fetchone()
        assert status == ("SUCCESS",)
        spans = [json.loads(line) for line in span_file.read_text(encoding="utf-8").splitlines()]
        relevant = [s for s in spans if s["name"] in ("common_dbos_wait_started", "common_dbos_recovered")]
        assert {s["name"] for s in relevant} == {"common_dbos_wait_started", "common_dbos_recovered"}
        assert len({s["pid"] for s in relevant}) == 2
        assert all(s["trace_id"] == payload["trace"]["trace_id"] for s in relevant)
        assert all(s["parent_id"] == payload["trace"]["span_id"] for s in relevant)
        assert len({s["span_id"] for s in relevant}) == len(relevant)
        assert all(s["attributes"]["all_tomorrow.correlation_id"] == payload["trace"]["correlation_id"] for s in relevant)
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=10)


def test_restate_live_common_d06_wait_restart_signal(tmp_path, monkeypatch) -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not fixture_url or not admin or not ingress:
        pytest.skip("Set fixture and Restate URLs")
    _prepare_fixture(fixture_url)
    payload = _payload("restate-wait", wait_for_signal=True)
    span_file = tmp_path / "restate-common-spans.jsonl"
    monkeypatch.setenv("AT_TEST_OTEL_SPANS", str(span_file))
    workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"

    def worker() -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.support.restate_common_service:app", "--host", "127.0.0.1", "--port", "9093"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def ready(process: subprocess.Popen[bytes]) -> None:
        with httpx.Client(timeout=2) as client:
            for _ in range(300):
                assert process.poll() is None, f"Restate common worker exited {process.returncode}"
                try:
                    if client.get("http://127.0.0.1:9093/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
        pytest.fail("Restate common worker did not start")

    first = worker()
    second = None
    try:
        ready(first)
        registration = httpx.post(
            f"{admin.rstrip('/')}/deployments",
            json={"uri": "http://127.0.0.1:9093", "use_http_11": True}, timeout=10,
        )
        assert registration.status_code in (200, 201), registration.text
        base = f"{ingress.rstrip('/')}/AllTomorrowCommonD01/{workflow_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(f"{base}/run", json=payload, timeout=60))
            for _ in range(300):
                with psycopg.connect(fixture_url) as conn:
                    waiting = conn.execute(
                        "SELECT waiting FROM common_wait_probe WHERE workflow_id=%s", (workflow_id,),
                    ).fetchone()
                if waiting == (True,):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restate common workflow did not reach wait")
            for _ in range(300):
                if span_file.exists() and "common_restate_wait_started" in span_file.read_text(encoding="utf-8"):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Restate wait span was not exported before worker kill")
            first.kill()
            first.wait(timeout=5)
            second = worker()
            ready(second)
            approval = httpx.post(f"{base}/approve", json={"approved": True}, timeout=20)
            assert approval.status_code == 200, approval.text
            completed = future.result(timeout=45)
        assert completed.status_code == 200, completed.text
        _assert_common_result(fixture_url, payload, completed.json())
        assert first.pid != second.pid
        stored = httpx.get(
            f"{ingress.rstrip('/')}/restate/output/{completed.headers['x-restate-id']}", timeout=10,
        )
        assert stored.status_code == 200 and stored.json() == completed.json()
        spans = [json.loads(line) for line in span_file.read_text(encoding="utf-8").splitlines()]
        relevant = [s for s in spans if s["name"] in ("common_restate_wait_started", "common_restate_recovered")]
        assert {s["name"] for s in relevant} == {"common_restate_wait_started", "common_restate_recovered"}
        assert len({s["pid"] for s in relevant}) == 2
        assert all(s["trace_id"] == payload["trace"]["trace_id"] for s in relevant)
        assert all(s["parent_id"] == payload["trace"]["span_id"] for s in relevant)
        assert len({s["span_id"] for s in relevant}) == len(relevant)
        assert all(s["attributes"]["all_tomorrow.correlation_id"] == payload["trace"]["correlation_id"] for s in relevant)
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize("fail_point,exit_code,model_calls,mutation_calls", [
    (FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, 2, 1),
    (FailPoint.AFTER_MODEL_RESULT_PERSIST, 79, 1, 1),
    (FailPoint.AFTER_MUTATION_SIDE_EFFECT, 77, 1, 2),
])
def test_dbos_live_common_crash(tmp_path, fail_point, exit_code, model_calls, mutation_calls) -> None:
    system_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not system_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL")
    _prepare_fixture(fixture_url)
    span_file = tmp_path / "crash-spans.jsonl"
    payload = _payload("dbos-crash", fail_point=fail_point)
    env = os.environ.copy()
    env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
    env["AT_TEST_COMMON_PHASE"] = "crash"
    env["AT_TEST_OTEL_SPANS"] = str(span_file)
    first = subprocess.run(
        [sys.executable, "-m", "tests.support.dbos_common_worker"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert first.returncode == exit_code, first.stderr[-2000:]
    with psycopg.connect(fixture_url) as conn:
        before = conn.execute(
            "SELECT call_count, application_count FROM common_mutation_probe WHERE idempotency_key=%s",
            (payload["input"]["mutation_key"],),
        ).fetchone()
    assert before == ((1, 1) if mutation_calls == 2 else None)
    env["AT_TEST_COMMON_PHASE"] = "normal"
    second = subprocess.run(
        [sys.executable, "-m", "tests.support.dbos_common_worker"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert second.returncode == 0, second.stderr[-2000:]
    _assert_common_result(
        fixture_url, payload, json.loads(second.stdout.strip().splitlines()[-1]), expected_calls=mutation_calls,
    )
    workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"
    with psycopg.connect(system_url) as conn:
        status = conn.execute(
            "SELECT status FROM dbos.workflow_status WHERE workflow_uuid=%s", (workflow_id,),
        ).fetchone()
    assert status == ("SUCCESS",)
    _assert_crash_evidence(fixture_url, payload, span_file, model_calls)


@pytest.mark.parametrize("fail_point,exit_code,model_calls,mutation_calls", [
    (FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, 2, 1),
    (FailPoint.AFTER_MODEL_RESULT_PERSIST, 79, 1, 1),
    (FailPoint.AFTER_MUTATION_SIDE_EFFECT, 77, 1, 2),
])
def test_restate_live_common_crash(tmp_path, fail_point, exit_code, model_calls, mutation_calls) -> None:
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not fixture_url or not admin or not ingress:
        pytest.skip("Set fixture and Restate URLs")
    _prepare_fixture(fixture_url)
    span_file = tmp_path / "crash-spans.jsonl"
    payload = _payload("restate-crash", fail_point=fail_point)
    workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"

    def worker(*, crash: bool) -> subprocess.Popen[bytes]:
        env = os.environ.copy()
        env["AT_TEST_OTEL_SPANS"] = str(span_file)
        if crash:
            env["AT_TEST_COMMON_PHASE"] = "crash"
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.support.restate_common_service:app", "--host", "127.0.0.1", "--port", "9093"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )

    def ready(process: subprocess.Popen[bytes]) -> None:
        with httpx.Client(timeout=2) as client:
            for _ in range(300):
                assert process.poll() is None, f"Restate common worker exited {process.returncode}"
                try:
                    if client.get("http://127.0.0.1:9093/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
        pytest.fail("Restate common worker did not start")

    first = worker(crash=True)
    second = None
    try:
        ready(first)
        registration = httpx.post(
            f"{admin.rstrip('/')}/deployments",
            json={"uri": "http://127.0.0.1:9093", "use_http_11": True}, timeout=10,
        )
        assert registration.status_code in (200, 201), registration.text
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: httpx.post(
                f"{ingress.rstrip('/')}/AllTomorrowCommonD01/{workflow_id}/run",
                json=payload, timeout=60,
            ))
            assert first.wait(timeout=20) == exit_code
            with psycopg.connect(fixture_url) as conn:
                before = conn.execute(
                    "SELECT call_count, application_count FROM common_mutation_probe WHERE idempotency_key=%s",
                    (payload["input"]["mutation_key"],),
                ).fetchone()
            assert before == ((1, 1) if mutation_calls == 2 else None)
            second = worker(crash=False)
            ready(second)
            completed = future.result(timeout=45)
        assert completed.status_code == 200, completed.text
        _assert_common_result(fixture_url, payload, completed.json(), expected_calls=mutation_calls)
        assert first.pid != second.pid
        stored = httpx.get(
            f"{ingress.rstrip('/')}/restate/output/{completed.headers['x-restate-id']}", timeout=10,
        )
        assert stored.status_code == 200 and stored.json() == completed.json()
        _assert_crash_evidence(fixture_url, payload, span_file, model_calls)
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _assert_crash_evidence(fixture_url, payload, span_file, model_calls):
    with psycopg.connect(fixture_url) as conn:
        assert conn.execute("SELECT calls FROM common_model_probe WHERE idempotency_key=%s", (payload["input"]["mutation_key"],)).fetchone() == (model_calls,)
    spans = [json.loads(line) for line in span_file.read_text().splitlines()]
    injected = [s for s in spans if s["name"].startswith("injected_")]
    completed = [s for s in spans if s["name"] == "common_completed"]
    assert len(injected) == len(completed) == 1
    assert injected[0]["pid"] != completed[0]["pid"]
    assert all(s["trace_id"] == payload["trace"]["trace_id"] for s in spans)
    assert all(s["parent_id"] == payload["trace"]["span_id"] for s in spans)
