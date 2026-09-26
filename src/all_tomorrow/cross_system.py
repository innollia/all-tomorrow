"""Stage 2.4C — Fallback & Cross-System Mutation.

Chooses between same-Run recovery and a new-Run fallback by failure class. An
AMBIGUOUS_EFFECT never triggers a blind replay on an alternate resource — the
effect must be reconciled first. A source mutation records expected version +
authorization + resulting hash, and optimistic-version conflicts fail closed.
Compensation is itself a new authorized mutation, not a silent undo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError, ErrorCategory


class CrossSystemError(DomainError):
    pass


class VersionConflictError(CrossSystemError):
    pass


class AmbiguousEffectError(CrossSystemError):
    """The effect's commit state is unknown; blind fallback is forbidden."""


class FallbackAction(StrEnum):
    SAME_RUN_RECOVERY = "SAME_RUN_RECOVERY"   # retryable transient on the same resource
    NEW_RUN_FALLBACK = "NEW_RUN_FALLBACK"     # resource unavailable → new Run elsewhere
    RECONCILE_FIRST = "RECONCILE_FIRST"       # ambiguous → probe before any retry
    NON_RETRYABLE = "NON_RETRYABLE"           # give up / NEED_USER


def decide_fallback(category: ErrorCategory) -> FallbackAction:
    if category in (ErrorCategory.TIMEOUT, ErrorCategory.RATE_LIMITED):
        return FallbackAction.SAME_RUN_RECOVERY
    if category == ErrorCategory.UNAVAILABLE:
        return FallbackAction.NEW_RUN_FALLBACK
    if category == ErrorCategory.AMBIGUOUS_EFFECT:
        return FallbackAction.RECONCILE_FIRST
    return FallbackAction.NON_RETRYABLE


@dataclass(frozen=True, slots=True)
class SourceMutation:
    source_id: str
    expected_version: str
    actor_authority: str
    payload_hash: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    source_id: str
    new_version: str
    result_hash: str


@dataclass(frozen=True, slots=True)
class CompensationSpec:
    target_source_id: str
    reason: str
    authority: str
    payload_hash: str


class CrossSystemMutator:
    """Applies source mutations with version/authorization/hash provenance."""

    def __init__(self) -> None:
        self._versions: dict[str, str] = {}
        self._authorized: set[str] = set()

    def seed(self, source_id: str, version: str) -> None:
        self._versions[source_id] = version

    def grant(self, authority: str) -> None:
        self._authorized.add(authority)

    def apply(self, m: SourceMutation, *, new_version: str, result_hash: str) -> MutationResult:
        if m.actor_authority not in self._authorized:
            raise CrossSystemError(f"unauthorized mutation by {m.actor_authority}")
        current = self._versions.get(m.source_id)
        if current is None:
            raise CrossSystemError(f"unknown source {m.source_id}")
        if current != m.expected_version:
            raise VersionConflictError(
                f"optimistic version conflict on {m.source_id}: expected {m.expected_version}, have {current}"
            )
        self._versions[m.source_id] = new_version
        return MutationResult(source_id=m.source_id, new_version=new_version, result_hash=result_hash)

    def fallback_on_ambiguous_must_reconcile(self, category: ErrorCategory) -> None:
        """Guard: refuse a blind fallback when the prior effect is ambiguous."""
        if decide_fallback(category) == FallbackAction.RECONCILE_FIRST:
            raise AmbiguousEffectError("ambiguous effect requires reconciliation before fallback")

    def compensate(self, spec: CompensationSpec, *, new_version: str, result_hash: str) -> MutationResult:
        """Compensation is a NEW authorized mutation (records its own provenance)."""
        m = SourceMutation(
            source_id=spec.target_source_id,
            expected_version=self._versions.get(spec.target_source_id, ""),
            actor_authority=spec.authority, payload_hash=spec.payload_hash,
        )
        return self.apply(m, new_version=new_version, result_hash=result_hash)
