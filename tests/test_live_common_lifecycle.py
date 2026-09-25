"""Same lifecycle acceptance procedure for every process adapter."""
import json
import os
import time

import pytest
import psycopg

from tests.support.live_process_adapters import CANDIDATES
from tests.test_live_common_d01 import _payload, _prepare_fixture, _assert_common_result


@pytest.fixture(params=CANDIDATES, ids=lambda cls: cls.candidate)
def execution(request, tmp_path):
    if not all(os.environ.get(key) for key in (
        "AT_TEST_FIXTURE_URL", "AT_TEST_POSTGRES_URL", "AT_TEST_RESTATE_ADMIN", "AT_TEST_RESTATE_INGRESS",
    )):
        pytest.skip("Run inside the live lab")
    _prepare_fixture(os.environ["AT_TEST_FIXTURE_URL"])
    adapter = request.param(_payload("lifecycle"), tmp_path)
    try:
        yield adapter
    finally:
        adapter.close()


def test_timer_retains_original_deadline(execution):
    execution.payload["input"]["timer_delay_seconds"] = 20
    first = execution.start()
    execution.wait_span("common_timer_started")
    started = time.monotonic()
    # Give the durable timer command time to be committed after its entry span.
    time.sleep(2)
    execution.kill()
    time.sleep(12)
    recovered = time.monotonic()
    result = execution.finish()
    finished = time.monotonic()
    _assert_common_result(execution.fixture_url, execution.payload, result)
    assert finished - started >= 19
    assert finished - recovered < 19, "Timer was restarted with its full duration"
    spans = [json.loads(line) for line in execution.span_file.read_text().splitlines()]
    completion = next(s for s in spans if s["name"] == "common_timer_finished")
    assert completion["pid"] != first.pid
    assert completion["trace_id"] == execution.payload["trace"]["trace_id"]


def test_cancel_survives_restart_and_later_signal(execution):
    execution.payload["input"]["wait_for_signal_name"] = "approval"
    execution.start()
    execution.wait_span("_wait_started")
    execution.kill()
    execution.cancel()
    for _ in range(100):
        if execution.state() == "CANCELLED":
            break
        time.sleep(.1)
    assert execution.state() == "CANCELLED"
    execution.signal()
    time.sleep(1)
    assert execution.state() == "CANCELLED"
    with psycopg.connect(execution.fixture_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM common_followup_probe WHERE idempotency_key=%s", (execution.payload["input"]["mutation_key"],)).fetchone() == (0,)


def test_application_and_dependency_upgrade_replays_old_model(execution):
    old_package = "/opt/all-tomorrow-pydantic-ai-2.45.0"
    from pathlib import Path
    if not Path(old_package).is_dir():
        pytest.skip("Install isolated pydantic-ai-slim 2.45.0 for the upgrade probe")
    execution.payload["input"]["wait_for_signal_name"] = "approval"
    execution.environment["PYTHONPATH"] = old_package
    first = execution.start()
    execution.wait_span("_wait_started")
    execution.kill()
    execution.environment.pop("PYTHONPATH")
    execution.environment["AT_TEST_APP_REVISION"] = "2"
    execution.signal()
    if execution.process.poll() is None:
        execution.kill()
    output = execution.finish()
    _assert_common_result(execution.fixture_url, execution.payload, output)
    assert execution.process.pid != first.pid
    spans = [json.loads(line) for line in execution.span_file.read_text().splitlines()]
    assert {s["attributes"]["pydantic_ai.version"] for s in spans} == {"2.45.0", "2.46.0"}
    with psycopg.connect(execution.fixture_url) as conn:
        key = execution.payload["input"]["mutation_key"]
        assert conn.execute("SELECT calls FROM common_model_probe WHERE idempotency_key=%s", (key,)).fetchone() == (1,)
        assert conn.execute("SELECT schema_version FROM common_upgrade_probe WHERE idempotency_key=%s", (key,)).fetchone() == (2,)
