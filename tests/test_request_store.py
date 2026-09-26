"""Stage 2.1A — Request/Delivery schema verification (S2-21A-01..04)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.requests import IdempotencyKey, RequestError, RequestStore


def _key(value="k1", user="u1", ns="api", ver="1", expires=None):
    return IdempotencyKey(namespace=ns, version=ver, value=value, user_id=user, expires_at=expires)


# S2-21A-01: concurrent duplicate delivery → one Request.
async def test_21a_01_concurrent_duplicate_one_request() -> None:
    store = RequestStore()

    async def ingest(src):
        return await store.ingest(user_id="u1", text="hi", ingress="api",
                                  source_event_id=src, idempotency_key=_key("dup"))

    results = await asyncio.gather(ingest("e1"), ingest("e2"), ingest("e3"))
    request_ids = {r.request_id for r, _, _ in results}
    assert len(request_ids) == 1                 # one logical Request
    assert store.request_count() == 1
    new_flags = [is_new for _, _, is_new in results]
    assert sum(new_flags) == 1                   # exactly one creation


# S2-21A-02: delivery history preserves every ingress.
async def test_21a_02_delivery_history_preserved() -> None:
    store = RequestStore()
    r, d1, _ = await store.ingest(user_id="u1", text="hi", ingress="api",
                                  source_event_id="e1", idempotency_key=_key("dup"))
    await store.ingest(user_id="u1", text="hi", ingress="discord",
                       source_event_id="e2", idempotency_key=_key("dup"))
    deliveries = store.deliveries_for(r.request_id)
    assert len(deliveries) == 2
    assert {d.ingress for d in deliveries} == {"api", "discord"}


# S2-21A-03: key namespace/version/expiry stored + honored.
async def test_21a_03_key_namespace_version_expiry() -> None:
    store = RequestStore()
    # different namespace with same value → different Request
    await store.ingest(user_id="u1", text="a", ingress="api", source_event_id="e1",
                       idempotency_key=_key("same", ns="api"))
    await store.ingest(user_id="u1", text="b", ingress="discord", source_event_id="e2",
                       idempotency_key=_key("same", ns="discord"))
    assert store.request_count() == 2
    # expired key is refused
    with pytest.raises(RequestError):
        await store.ingest(user_id="u1", text="c", ingress="api", source_event_id="e3",
                           idempotency_key=_key("exp", expires=utc_now() - timedelta(seconds=1)))


# S2-21A-04: cross-user key collision → separate Requests.
async def test_21a_04_cross_user_no_collision() -> None:
    store = RequestStore()
    await store.ingest(user_id="alice", text="a", ingress="api", source_event_id="e1",
                       idempotency_key=_key("shared", user="alice"))
    await store.ingest(user_id="bob", text="b", ingress="api", source_event_id="e2",
                       idempotency_key=_key("shared", user="bob"))
    assert store.request_count() == 2  # same key value, different users → no collision


async def test_21a_key_user_scope_mismatch_refused() -> None:
    store = RequestStore()
    with pytest.raises(RequestError):
        await store.ingest(user_id="u1", text="x", ingress="api", source_event_id="e",
                           idempotency_key=_key("k", user="other"))
