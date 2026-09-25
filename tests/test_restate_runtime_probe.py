"""A narrow real Restate ingress probe; requires a registered local endpoint."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import httpx
import psycopg
import pytest


def test_restate_workflow_ingress_and_duplicate_run_contract() -> None:
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not ingress:
        pytest.skip("Set AT_TEST_RESTATE_INGRESS when the local Restate probe endpoint is registered")

    workflow_id = f"probe-{uuid4()}"
    url = f"{ingress.rstrip('/')}/AllTomorrowProbe/{workflow_id}/run"
    with httpx.Client(timeout=20) as client:
        first = client.post(url, json="typed-result")
        assert first.status_code == 200, first.text
        assert first.json() == "typed-result"
        assert first.headers.get("x-restate-id")

        duplicate = client.post(url, json="typed-result")
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.headers.get("x-restate-id") == first.headers["x-restate-id"]

        second_run = client.post(
            f"{ingress.rstrip('/')}/AllTomorrowProbe/probe-{uuid4()}/run",
            json="another-run-for-the-same-logical-work",
        )
        assert second_run.status_code == 200, second_run.text
        assert second_run.json() == "another-run-for-the-same-logical-work"
        assert second_run.headers["x-restate-id"] != first.headers["x-restate-id"]


def test_concurrent_duplicate_start_reuses_one_invocation() -> None:
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    fixture_url = os.environ.get("AT_TEST_FIXTURE_URL")
    if not ingress or not fixture_url:
        pytest.skip("Set AT_TEST_RESTATE_INGRESS and AT_TEST_FIXTURE_URL")
    workflow_id = f"concurrent-{uuid4()}"
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS common_mutation_probe (
                idempotency_key TEXT PRIMARY KEY, call_count INTEGER NOT NULL,
                application_count INTEGER NOT NULL, committed_value TEXT NOT NULL
            )"""
        )
    url = f"{ingress.rstrip('/')}/AllTomorrowProbe/{workflow_id}/run"
    barrier = Barrier(2)

    def call() -> httpx.Response:
        barrier.wait(timeout=5)
        return httpx.post(url, json={"kind": "concurrent-start", "mutation_key": workflow_id}, timeout=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(call)
        b = pool.submit(call)
        responses = [a.result(timeout=25), b.result(timeout=25)]
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len({response.headers["x-restate-id"] for response in responses}) == 1
    assert next(response for response in responses if response.status_code == 200).json() == "concurrent-start"
    invocation_id = responses[0].headers["x-restate-id"]
    persisted = httpx.get(f"{ingress.rstrip('/')}/restate/output/{invocation_id}", timeout=10)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json() == "concurrent-start"
    with psycopg.connect(fixture_url) as conn:
        row = conn.execute(
            "SELECT call_count, application_count FROM common_mutation_probe WHERE idempotency_key=%s",
            (workflow_id,),
        ).fetchone()
    assert row == (1, 1)
