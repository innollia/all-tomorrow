"""Stage 2.1B + 2.1C — Web/API, Discord, and CLI ingress adapters.

Each transport maps an authenticated inbound event to a canonical Request via the
2.1A RequestStore, deriving a per-transport idempotency key so a retry / duplicate
event collapses to one Request. Local-only chatter does not create central Work;
a durable/cross-project request escalates with provenance (2.1D preflight).
"""

from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.ingress_policy import Escalation, PreflightInputs, preflight
from all_tomorrow.requests import IdempotencyKey, Request, RequestStore

API_SCHEMA_VERSION = "1"
# Unknown/new request fields are ignored (forward-compatible), not rejected.
UNKNOWN_FIELD_POLICY = "ignore"


@dataclass(frozen=True, slots=True)
class IngressResult:
    request: Request
    is_new: bool
    escalation: Escalation
    central_work: bool


async def _ingest(store, *, user_id, text, ingress, source_event_id, key_value, key_ns,
                  preflight_inputs, attachment_refs=()):
    key = IdempotencyKey(namespace=key_ns, version="1", value=key_value, user_id=user_id)
    request, _delivery, is_new = await store.ingest(
        user_id=user_id, text=text, ingress=ingress, source_event_id=source_event_id,
        idempotency_key=key, attachment_refs=attachment_refs,
    )
    esc = preflight(preflight_inputs)
    central = esc in (Escalation.DURABLE, Escalation.CENTRAL_RESOLUTION, Escalation.NEED_USER)
    return IngressResult(request=request, is_new=is_new, escalation=esc, central_work=central)


# --- 2.1B Web / API -----------------------------------------------------------
async def web_api_ingress(
    store: RequestStore, *, user_id: str, text: str, client_idempotency_key: str,
    request_id_hint: str = "", preflight_inputs: PreflightInputs | None = None,
    extra_fields: dict | None = None,
) -> IngressResult:
    # Forward-compat: unknown/new fields are ignored, not rejected (S2-21B-04).
    _ = extra_fields
    return await _ingest(
        store, user_id=user_id, text=text, ingress="api",
        source_event_id=request_id_hint or client_idempotency_key,
        key_value=client_idempotency_key, key_ns="api",
        preflight_inputs=preflight_inputs or PreflightInputs(),
    )


# --- 2.1C Discord -------------------------------------------------------------
async def discord_ingress(
    store: RequestStore, *, user_id: str, text: str, message_id: str,
    is_local_only: bool = False, preflight_inputs: PreflightInputs | None = None,
) -> IngressResult:
    # Discord message id is the delivery/idempotency key (S2-21C-01).
    res = await _ingest(
        store, user_id=user_id, text=text, ingress="discord",
        source_event_id=message_id, key_value=message_id, key_ns="discord",
        preflight_inputs=preflight_inputs or PreflightInputs(),
    )
    if is_local_only:
        # Local-only conversation → no central Work (S2-21C-02).
        return IngressResult(request=res.request, is_new=res.is_new,
                             escalation=Escalation.INLINE, central_work=False)
    return res


# --- 2.1C CLI -----------------------------------------------------------------
async def cli_ingress(
    store: RequestStore, *, user_id: str, text: str, cli_idempotency_key: str,
    preflight_inputs: PreflightInputs | None = None,
) -> IngressResult:
    # The CLI generates/shows an idempotency key; retry reuses it (S2-21C-04).
    return await _ingest(
        store, user_id=user_id, text=text, ingress="cli",
        source_event_id=cli_idempotency_key, key_value=cli_idempotency_key, key_ns="cli",
        preflight_inputs=preflight_inputs or PreflightInputs(),
    )
