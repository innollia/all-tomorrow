"""Feature 11 -- durable request idempotency: a client retry after a server
restart still collapses to the SAME Request, verified against a real Postgres
(only when AT_TEST_POSTGRES_URL is set -- see docs/plans/web-full-features.md)."""
import os

import pytest

from all_tomorrow.requests import IdempotencyKey, PostgresRequestStore
from all_tomorrow.storage.postgres import PostgresStore


def _pg_url() -> str | None:
    return os.environ.get("AT_TEST_POSTGRES_URL")


async def test_same_key_returns_same_request_across_a_fresh_store_instance() -> None:
    url = _pg_url()
    if not url:
        pytest.skip("Set AT_TEST_POSTGRES_URL")

    migrator = PostgresStore(url)
    await migrator.open()
    await migrator.migrate("migrations")
    await migrator.close()

    key = IdempotencyKey(namespace="api", version="1", value="dup-key-restart-test", user_id="alice")

    store1 = PostgresRequestStore(url)
    await store1.open()
    try:
        req1, _, is_new1 = await store1.ingest(
            user_id="alice", text="재시작 후에도 중복 방지", ingress="api",
            source_event_id="dup-key-restart-test", idempotency_key=key,
        )
        assert is_new1 is True
    finally:
        await store1.close()

    # A brand-new store instance -- simulating a server restart -- with the SAME
    # idempotency key must return the SAME Request, not create a second one.
    store2 = PostgresRequestStore(url)
    await store2.open()
    try:
        req2, _, is_new2 = await store2.ingest(
            user_id="alice", text="재시작 후에도 중복 방지", ingress="api",
            source_event_id="dup-key-restart-test", idempotency_key=key,
        )
        assert is_new2 is False
        assert req2.request_id == req1.request_id

        fetched = await store2.get_request(req1.request_id)
        assert fetched is not None and fetched.request_id == req1.request_id

        deliveries = await store2.deliveries_for(req1.request_id)
        assert len(deliveries) == 2  # one per ingest() call, same Request both times
    finally:
        await store2.close()


async def test_different_users_with_the_same_key_value_get_different_requests() -> None:
    url = _pg_url()
    if not url:
        pytest.skip("Set AT_TEST_POSTGRES_URL")

    migrator = PostgresStore(url)
    await migrator.open()
    await migrator.migrate("migrations")
    await migrator.close()

    store = PostgresRequestStore(url)
    await store.open()
    try:
        key_a = IdempotencyKey(namespace="api", version="1", value="shared-value", user_id="a1")
        key_b = IdempotencyKey(namespace="api", version="1", value="shared-value", user_id="b1")
        req_a, _, _ = await store.ingest(
            user_id="a1", text="a1의 요청", ingress="api", source_event_id="e1", idempotency_key=key_a,
        )
        req_b, _, _ = await store.ingest(
            user_id="b1", text="b1의 요청", ingress="api", source_event_id="e2", idempotency_key=key_b,
        )
        assert req_a.request_id != req_b.request_id
    finally:
        await store.close()
