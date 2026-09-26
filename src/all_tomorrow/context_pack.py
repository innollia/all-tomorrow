"""Stage 2.3A — Context Pack.

Assembles a bounded, deterministic context for execution: objective, explicit
constraints, source refs, decisions, open state, artifacts/lessons — each tagged
with its authority. DATA content (untrusted: fetched pages, tool output, docs)
is carried separately from CONTROL instructions and can never expand authority.
Selection is bounded by a byte budget; dropped refs are summarized, never
silently merged across owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Authority(StrEnum):
    CONTROL = "CONTROL"   # trusted control instructions (the user's own request/policy)
    DATA = "DATA"         # untrusted evidence: web, tool output, documents


class OwnerConflictError(Exception):
    """Two items from different owners cannot be silently merged."""


@dataclass(frozen=True, slots=True)
class ContextItem:
    ref: str
    owner_id: str
    authority: Authority
    size_bytes: int
    summary: str          # a ref/summary, never raw secret content


@dataclass(frozen=True, slots=True)
class ContextPack:
    objective: str
    owner_id: str
    control_items: tuple[ContextItem, ...]
    data_items: tuple[ContextItem, ...]
    omitted_refs: tuple[str, ...]
    total_bytes: int

    def authority_of(self, ref: str) -> Authority | None:
        for it in (*self.control_items, *self.data_items):
            if it.ref == ref:
                return it.authority
        return None


def build_context_pack(
    *,
    objective: str,
    owner_id: str,
    items: list[ContextItem],
    byte_budget: int,
) -> ContextPack:
    """Deterministic bounded selection with authority separation.

    Items are selected in a stable order (control first, then by ref) up to the
    byte budget; the rest are recorded as omitted refs. An item owned by a
    different owner_id is rejected (no silent cross-owner merge).
    """
    for it in items:
        if it.owner_id != owner_id:
            raise OwnerConflictError(
                f"item {it.ref} owned by {it.owner_id} cannot merge into {owner_id}'s pack"
            )

    # Stable deterministic order: CONTROL before DATA, then by ref.
    ordered = sorted(items, key=lambda i: (i.authority != Authority.CONTROL, i.ref))
    selected: list[ContextItem] = []
    omitted: list[str] = []
    used = 0
    for it in ordered:
        if used + it.size_bytes <= byte_budget:
            selected.append(it)
            used += it.size_bytes
        else:
            omitted.append(it.ref)

    control = tuple(i for i in selected if i.authority == Authority.CONTROL)
    data = tuple(i for i in selected if i.authority == Authority.DATA)
    return ContextPack(
        objective=objective, owner_id=owner_id,
        control_items=control, data_items=data,
        omitted_refs=tuple(omitted), total_bytes=used,
    )


def is_control_authority(pack: ContextPack, ref: str) -> bool:
    """Only CONTROL items may grant authority/permissions.

    A DATA item that *looks* like an instruction ('run command', 'ignore policy')
    is still DATA — this returns False, so untrusted content cannot expand
    authority.
    """
    return pack.authority_of(ref) == Authority.CONTROL
