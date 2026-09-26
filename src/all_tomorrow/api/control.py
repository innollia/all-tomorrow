"""Stage 2.2B — Store-backed Control API (authorization guard layer).

Every object fetch/mutation goes through user-scoped authorization — guessing an
id belonging to another user always fails (cross-user isolation). Mutating
actions (cancel, answer) emit a Delivery intent alongside the state change.
"""

from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.domain.errors import DomainError

API_VERSION = "1"


class AccessDenied(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ControlResult:
    ok: bool
    data: dict | None = None
    delivery_intent_emitted: bool = False


class ControlAPI:
    """Object-level authorization facade over the domain stores."""

    def __init__(self, *, owner_lookup, store) -> None:
        self._owner_lookup = owner_lookup   # callable(obj_type, obj_id) -> user_id | None
        self._store = store
        self._delivery_intents: list[dict] = []

    def _check(self, requester: str, obj_type: str, obj_id: str) -> None:
        owner = self._owner_lookup(obj_type, obj_id)
        if owner is None or owner != requester:
            raise AccessDenied(f"{obj_type}/{obj_id}: not owned by requester")

    def get(self, requester: str, obj_type: str, obj_id: str) -> ControlResult:
        self._check(requester, obj_type, obj_id)
        return ControlResult(ok=True, data={"type": obj_type, "id": obj_id})

    def cancel(self, requester: str, obj_type: str, obj_id: str) -> ControlResult:
        self._check(requester, obj_type, obj_id)
        self._delivery_intents.append({"action": "cancel", "type": obj_type, "id": obj_id})
        return ControlResult(ok=True, delivery_intent_emitted=True)

    def answer(self, requester: str, question_id: str, answer_ref: str) -> ControlResult:
        self._check(requester, "question", question_id)
        self._delivery_intents.append({"action": "answer", "question_id": question_id, "ref": answer_ref})
        return ControlResult(ok=True, delivery_intent_emitted=True)

    def delivery_intents(self) -> list[dict]:
        return list(self._delivery_intents)
