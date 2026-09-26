"""Stage 2.1B + 2.1C — ingress adapters verification."""

from __future__ import annotations

import pytest

from all_tomorrow.ingress_adapters import (
    cli_ingress,
    discord_ingress,
    web_api_ingress,
)
from all_tomorrow.ingress_policy import Escalation, PreflightInputs
from all_tomorrow.requests import RequestStore


# S2-21B-01/02: authenticated request → canonical Request; retry same key → same Request.
async def test_21b_web_retry_same_request() -> None:
    store = RequestStore()
    r1 = await web_api_ingress(store, user_id="u1", text="hi", client_idempotency_key="k1")
    r2 = await web_api_ingress(store, user_id="u1", text="hi", client_idempotency_key="k1")
    assert r1.request.request_id == r2.request.request_id
    assert r1.is_new and not r2.is_new
    assert store.request_count() == 1


# S2-21B-04: unknown/new fields are ignored, not rejected.
async def test_21b_unknown_fields_ignored() -> None:
    store = RequestStore()
    r = await web_api_ingress(store, user_id="u1", text="hi", client_idempotency_key="k",
                              extra_fields={"future_field": 123})
    assert r.request.text == "hi"


# S2-21C-01: duplicate Discord event → one mutation (one Request).
async def test_21c_discord_duplicate_one_request() -> None:
    store = RequestStore()
    await discord_ingress(store, user_id="u1", text="do x", message_id="m1")
    await discord_ingress(store, user_id="u1", text="do x", message_id="m1")
    assert store.request_count() == 1


# S2-21C-02: local-only message → no central Work.
async def test_21c_local_only_no_central() -> None:
    store = RequestStore()
    r = await discord_ingress(store, user_id="u1", text="lol", message_id="m1", is_local_only=True)
    assert r.central_work is False


# S2-21C-03: durable/cross-project request → central escalation.
async def test_21c_durable_central_escalation() -> None:
    store = RequestStore()
    r = await discord_ingress(store, user_id="u1", text="deploy prod", message_id="m2",
                              preflight_inputs=PreflightInputs(cross_project_mutation=True))
    assert r.central_work is True
    assert r.escalation == Escalation.CENTRAL_RESOLUTION


# S2-21C-04: CLI retry reuses the idempotency key → same Request.
async def test_21c_cli_retry_identity() -> None:
    store = RequestStore()
    a = await cli_ingress(store, user_id="u1", text="run", cli_idempotency_key="cli-1")
    b = await cli_ingress(store, user_id="u1", text="run", cli_idempotency_key="cli-1")
    assert a.request.request_id == b.request.request_id
