"""Stage 3.1C — Personal Query & Brief Projection.

Assembles central Work plus owner schedule/task/school SourceRefs with their
freshness into a ContextPack, answers "뭐 해야 돼?" only with source-backed items
(stale/unknown surfaced, never guessed), and projects a proactive brief that
reuses the Trigger/OutboundDelivery idempotency so the same logical brief is not
delivered twice. Owner truth is referenced, not centrally duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.owners import OwnerFact, Truthiness, read_fact


class PersonalError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ContextItem:
    label: str
    value: str | None
    truthiness: Truthiness
    source_id: str | None       # a REFERENCE, not a copy of owner truth


@dataclass(frozen=True, slots=True)
class ContextPack:
    central_work_ids: tuple[str, ...]
    items: tuple[ContextItem, ...]

    def actionable(self) -> tuple[ContextItem, ...]:
        # Only source-backed CURRENT items are actionable answers.
        return tuple(i for i in self.items if i.truthiness == Truthiness.CURRENT and i.value)

    def needs_attention(self) -> tuple[ContextItem, ...]:
        return tuple(i for i in self.items if i.truthiness != Truthiness.CURRENT)


def assemble_context(central_work_ids: list[str],
                     owner_facts: dict[str, list[OwnerFact]]) -> ContextPack:
    items: list[ContextItem] = []
    for label, candidates in owner_facts.items():
        best, t = read_fact(candidates)
        items.append(ContextItem(
            label=label,
            value=best.value if (best and t == Truthiness.CURRENT) else None,
            truthiness=t,
            source_id=best.source.source_id if best else None,
        ))
    return ContextPack(central_work_ids=tuple(central_work_ids), items=tuple(items))


def answer_what_should_i_do(pack: ContextPack) -> dict:
    """Source-backed answer. Stale/unknown items are flagged, not fabricated."""
    return {
        "do": [f"{i.label}: {i.value} (src={i.source_id})" for i in pack.actionable()],
        "attention": [f"{i.label}: {i.truthiness}" for i in pack.needs_attention()],
    }


# --- proactive brief (reuses trigger/outbound idempotency) ---

def brief_delivery_key(*, owner_id: str, logical_period: str) -> str:
    """Idempotency key so a re-fired brief for the same period is a duplicate."""
    return f"brief:{owner_id}:{logical_period}"


class BriefProjector:
    def __init__(self) -> None:
        self._delivered: set[str] = set()

    def project(self, *, owner_id: str, logical_period: str, pack: ContextPack) -> dict | None:
        key = brief_delivery_key(owner_id=owner_id, logical_period=logical_period)
        if key in self._delivered:
            return None   # S3-31C-03: idempotent — no duplicate outbound
        self._delivered.add(key)
        return {"key": key, "answer": answer_what_should_i_do(pack)}
