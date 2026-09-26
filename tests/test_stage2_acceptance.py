"""Stage 2 — Assistant acceptance (wires §01-§04 end to end, L0/L1)."""

from __future__ import annotations

import pytest

from all_tomorrow.api.control import AccessDenied, ControlAPI
from all_tomorrow.cross_system import FallbackAction, decide_fallback
from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.ingress_adapters import discord_ingress, web_api_ingress
from all_tomorrow.ingress_policy import Escalation, PreflightInputs
from all_tomorrow.outbound import DeliveryStatus, OutboundDelivery, OutboundStore
from all_tomorrow.questions import Question, QuestionService, QuestionStatus
from all_tomorrow.requests import RequestStore
from all_tomorrow.resources import ResourceKind, ResourceRecord, ResourceRegistry
from all_tomorrow.routing_policy import select
from all_tomorrow.domain.ids import new_id, utc_now


# Flow: authenticated web request → canonical Request → routed to a resource.
async def test_stage2_request_to_routing() -> None:
    store = RequestStore()
    res = await web_api_ingress(store, user_id="u1", text="summarize", client_idempotency_key="k1")
    assert res.request.user_id == "u1"
    reg = ResourceRegistry()
    reg.register(ResourceRecord("m1", ResourceKind.MODEL, frozenset({"chat"}),
                                health_status="healthy", health_checked_at=utc_now(),
                                remaining_quota=100, cost_per_unit=1.0))
    avail = reg.available(required_capabilities=frozenset({"chat"}))
    chosen = select(avail)
    assert chosen.resource.resource_id == "m1"


# Flow: duplicate delivery → one Request; control API isolates by user.
async def test_stage2_dedup_and_authz() -> None:
    store = RequestStore()
    await discord_ingress(store, user_id="alice", text="x", message_id="m1")
    await discord_ingress(store, user_id="alice", text="x", message_id="m1")
    assert store.request_count() == 1
    rid = list(store._requests.keys())[0]
    api = ControlAPI(owner_lookup=lambda t, i: "alice" if i == rid else None, store=store)
    assert api.get("alice", "request", rid).ok
    with pytest.raises(AccessDenied):
        api.get("mallory", "request", rid)


# Flow: question answered → outbound delivered once; failure isolated.
def test_stage2_question_answer_outbound() -> None:
    qs = QuestionService()
    q = qs.create(Question(question_id=new_id("q"), work_id="w1", prompt="Approve?"))
    _, sig = qs.answer(q.question_id, "ans:yes")
    assert sig is not None
    ob = OutboundStore()
    d = ob.enqueue(OutboundDelivery(delivery_id=new_id("dlv"), channel="email",
                                    recipient_id="u1", idempotency_key=sig.signal_id,
                                    payload_ref="answer"))
    delivered = ob.deliver(d.delivery_id, transport_ok=True)
    assert delivered.status == DeliveryStatus.DELIVERED


# Flow: ambiguous cross-system effect → reconcile, never blind fallback.
def test_stage2_ambiguous_reconcile() -> None:
    assert decide_fallback(ErrorCategory.AMBIGUOUS_EFFECT) == FallbackAction.RECONCILE_FIRST
    assert decide_fallback(ErrorCategory.UNAVAILABLE) == FallbackAction.NEW_RUN_FALLBACK


# Flow: durable/cross-project request escalates to central resolution.
async def test_stage2_escalation() -> None:
    store = RequestStore()
    r = await discord_ingress(store, user_id="u1", text="deploy", message_id="m9",
                              preflight_inputs=PreflightInputs(cross_project_mutation=True))
    assert r.escalation == Escalation.CENTRAL_RESOLUTION and r.central_work
