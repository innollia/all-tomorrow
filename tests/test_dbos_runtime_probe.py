"""A real DBOS persistence probe, separate from the simulated harness adapter."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg
from dbos import DBOS, SetWorkflowID

from all_tomorrow.harness.types import HarnessInput
from tests.support.live_common import apply_mutation


def _assert_persisted_step_replay(database_url: str) -> None:
    workflow_id = f"probe-{uuid4()}"
    calls: list[str] = []

    @DBOS.step(name="probe_step")
    def record_once(value: str) -> str:
        calls.append(value)
        return value

    @DBOS.workflow(name="probe_workflow")
    def workflow(value: str) -> str:
        return record_once(value)

    try:
        DBOS(config={"name": "all-tomorrow-probe", "system_database_url": database_url})
        DBOS.launch()
        with SetWorkflowID(workflow_id):
            assert workflow("first") == "first"
        assert calls == ["first"]
        DBOS.destroy()

        DBOS(config={"name": "all-tomorrow-probe", "system_database_url": database_url})
        DBOS.launch()
        with SetWorkflowID(workflow_id):
            assert workflow("first") == "first"
        assert calls == ["first"]
    finally:
        DBOS.destroy(destroy_registry=True)


def test_dbos_sqlite_workflow_persists_step_across_restart(tmp_path: Path) -> None:
    _assert_persisted_step_replay(f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}")


def test_dbos_postgres_workflow_persists_step_across_restart() -> None:
    database_url = os.environ.get("AT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL to run the PostgreSQL DBOS probe")
    _assert_persisted_step_replay(database_url)


def test_duplicate_start_and_distinct_run_ids(tmp_path: Path) -> None:
    """A repeated workflow ID reuses its result; a new Run executes independently."""
    database_url = f"sqlite:///{(tmp_path / 'identity.sqlite').as_posix()}"
    first_id, second_id = (f"identity-{uuid4()}" for _ in range(2))
    calls: list[str] = []

    @DBOS.step(name="identity_probe_step")
    def record(value: str) -> str:
        calls.append(value)
        return value

    @DBOS.workflow(name="identity_probe_workflow")
    def workflow(value: str) -> str:
        return record(value)

    try:
        DBOS(config={"name": "all-tomorrow-identity-probe", "system_database_url": database_url})
        DBOS.launch()
        with SetWorkflowID(first_id):
            assert workflow("first") == "first"
        with SetWorkflowID(first_id):
            assert workflow("first") == "first"
        with SetWorkflowID(second_id):
            assert workflow("second") == "second"
        assert calls == ["first", "second"]
    finally:
        DBOS.destroy(destroy_registry=True)


def test_concurrent_duplicate_start_uses_one_persisted_workflow() -> None:
    database_url = os.environ.get("AT_TEST_POSTGRES_URL")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not database_url or not fixture_url:
        pytest.skip("Set AT_TEST_POSTGRES_URL and AT_TEST_FIXTURE_URL for concurrent DBOS start")
    workflow_id = f"concurrent-{uuid4()}"
    data = HarnessInput(task_name="Concurrent start", mutation_key=workflow_id, mutation_value="shared-result")
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS common_mutation_probe (
                idempotency_key TEXT PRIMARY KEY, call_count INTEGER NOT NULL,
                application_count INTEGER NOT NULL, committed_value TEXT NOT NULL
            )"""
        )
    barrier = Barrier(2)
    lock = Lock()
    calls = 0

    @DBOS.step(name="concurrent_identity_step")
    def record() -> str:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(1)
        return apply_mutation(fixture_url, data)

    @DBOS.workflow(name="concurrent_identity_workflow")
    def workflow() -> str:
        return record()

    def start() -> str:
        barrier.wait(timeout=5)
        with SetWorkflowID(workflow_id):
            return workflow()

    try:
        DBOS(config={"name": "all-tomorrow-concurrent-probe", "system_database_url": database_url})
        DBOS.launch()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(start)
            second = pool.submit(start)
            assert [first.result(timeout=15), second.result(timeout=15)] == ["shared-result"] * 2
        assert calls == 1
        with psycopg.connect(fixture_url) as conn:
            row = conn.execute(
                "SELECT call_count, application_count FROM common_mutation_probe WHERE idempotency_key=%s",
                (workflow_id,),
            ).fetchone()
        assert row == (1, 1)
    finally:
        DBOS.destroy(destroy_registry=True)
