"""Stage 2.4B — Selection Policy.

Deterministic pipeline: hard filter (authority + capability + health/quota) →
rank (cost, then a stable tiebreak) → select. The result is independent of the
registry's insertion order. An explicit user resource choice is honored and is
never overridden by an inferred preference.
"""

from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.resources import ResourceRecord

ROUTING_POLICY_VERSION = "1"


class NoResourceError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class SelectionResult:
    resource: ResourceRecord
    policy_version: str
    reason: str


def _rank_key(r: ResourceRecord) -> tuple:
    # Unknown cost sorts LAST (conservative: prefer known-cheap). Stable tiebreak
    # on resource_id makes the result insertion-order independent.
    cost = r.cost_per_unit if r.cost_per_unit is not None else float("inf")
    return (cost, r.resource_id)


def select(
    candidates: list[ResourceRecord],
    *,
    explicit_choice_id: str | None = None,
    inferred_preference_id: str | None = None,
) -> SelectionResult:
    """Select one resource from the already hard-filtered candidates.

    ``explicit_choice_id`` (a user's stated resource) wins if it is among the
    valid candidates; an ``inferred_preference_id`` never overrides it.
    """
    if not candidates:
        raise NoResourceError("no resource satisfies the hard filter")

    by_id = {r.resource_id: r for r in candidates}

    # Explicit user choice is preserved (must still have passed the hard filter).
    if explicit_choice_id is not None:
        if explicit_choice_id in by_id:
            return SelectionResult(by_id[explicit_choice_id], ROUTING_POLICY_VERSION,
                                   "explicit user choice")
        raise NoResourceError(f"explicit resource {explicit_choice_id} not available")

    # Inferred preference only applies when the user made no explicit choice.
    if inferred_preference_id is not None and inferred_preference_id in by_id:
        return SelectionResult(by_id[inferred_preference_id], ROUTING_POLICY_VERSION,
                               "inferred preference")

    ranked = sorted(candidates, key=_rank_key)
    return SelectionResult(ranked[0], ROUTING_POLICY_VERSION, "ranked cheapest")
