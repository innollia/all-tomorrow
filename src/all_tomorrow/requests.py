"""Stage 2.1A — Request / Delivery schema.

A Request is the logical thing a user asked for; a Delivery is one inbound
transport of it (web/discord/api). Duplicate deliveries of the same request
(same idempotency key in the same namespace/user scope) collapse to ONE Request,
while every ingress is preserved in the delivery history. Attachments are
ArtifactRefs, never inline bytes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class RequestError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    namespace: str        # e.g. "api", "discord"
    version: str          # key scheme version
    value: str
    user_id: str          # scopes the key to a user (no cross-user collision)
    expires_at: datetime | None = None

    def scope(self) -> tuple[str, str, str, str]:
        return (self.user_id, self.namespace, self.version, self.value)

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


@dataclass(frozen=True, slots=True)
class Request:
    request_id: str
    user_id: str
    text: str
    created_at: datetime = field(default_factory=utc_now)
    attachment_refs: tuple[str, ...] = ()   # ArtifactRefs only


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    request_id: str
    ingress: str                 # web / discord / api / cli
    source_event_id: str
    idempotency_key: IdempotencyKey
    received_at: datetime = field(default_factory=utc_now)


class RequestStore:
    """In-memory reference store with atomic inbound dedup."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, Request] = {}
        self._deliveries: dict[str, Delivery] = {}
        self._key_to_request: dict[tuple[str, str, str, str], str] = {}

    async def ingest(
        self,
        *,
        user_id: str,
        text: str,
        ingress: str,
        source_event_id: str,
        idempotency_key: IdempotencyKey,
        attachment_refs: tuple[str, ...] = (),
    ) -> tuple[Request, Delivery, bool]:
        """Atomically create-or-attach. Returns (request, delivery, is_new_request).

        A duplicate key in the same (user, namespace, version, value) scope reuses
        the existing Request; the new Delivery is still recorded (history preserved).
        """
        if idempotency_key.user_id != user_id:
            raise RequestError("idempotency key user scope mismatch")
        async with self._lock:
            if idempotency_key.is_expired(utc_now()):
                raise RequestError("idempotency key expired")
            scope = idempotency_key.scope()
            existing_req_id = self._key_to_request.get(scope)
            if existing_req_id is not None:
                request = self._requests[existing_req_id]
                is_new = False
            else:
                request = Request(
                    request_id=new_id("req"), user_id=user_id, text=text,
                    attachment_refs=attachment_refs,
                )
                self._requests[request.request_id] = request
                self._key_to_request[scope] = request.request_id
                is_new = True
            delivery = Delivery(
                delivery_id=new_id("dlv"), request_id=request.request_id,
                ingress=ingress, source_event_id=source_event_id,
                idempotency_key=idempotency_key,
            )
            self._deliveries[delivery.delivery_id] = delivery
            return request, delivery, is_new

    def deliveries_for(self, request_id: str) -> list[Delivery]:
        return [d for d in self._deliveries.values() if d.request_id == request_id]

    def get_request(self, request_id: str) -> Request | None:
        return self._requests.get(request_id)

    def request_count(self) -> int:
        return len(self._requests)
