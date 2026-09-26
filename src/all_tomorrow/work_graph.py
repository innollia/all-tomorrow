"""Stage 3.4A — Dynamic Work Graph.

Relations between Work: parent/child, depends_on, blocks, supersedes,
generated_by. A depends_on edge that would form a cycle is rejected. A
dependency's failure never fakes the dependent's success — the dependent is held
WAITING with wait_reason=dependency_blocked (no separate BLOCKED enum in v1).
Dynamically generated children still pass budget/dedup (the 02D primitives).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError, InvariantViolationError


class WorkGraphError(DomainError):
    pass


class CycleError(InvariantViolationError):
    pass


class Relation(StrEnum):
    PARENT = "PARENT"
    DEPENDS_ON = "DEPENDS_ON"
    BLOCKS = "BLOCKS"
    SUPERSEDES = "SUPERSEDES"
    GENERATED_BY = "GENERATED_BY"


class DependencyOutcome(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DependentState(StrEnum):
    READY = "READY"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"    # wait_reason=dependency_blocked
    BLOCKED_BY_FAILURE = "BLOCKED_BY_FAILURE"    # dependency failed → NOT success


@dataclass(slots=True)
class WorkGraph:
    _depends: dict[str, set[str]] = field(default_factory=dict)   # work -> its dependencies
    _rel: list[tuple[str, Relation, str]] = field(default_factory=list)

    def add_relation(self, src: str, rel: Relation, dst: str) -> None:
        if rel == Relation.DEPENDS_ON:
            # Reject a dependency edge that would create a cycle.
            if self._would_cycle(src, dst):
                raise CycleError(f"depends_on {src}->{dst} would create a cycle")
            self._depends.setdefault(src, set()).add(dst)
        self._rel.append((src, rel, dst))

    def _would_cycle(self, src: str, dst: str) -> bool:
        # Adding src depends_on dst cycles iff src is already reachable from dst.
        if src == dst:
            return True
        stack = [dst]
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            if node == src:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._depends.get(node, ()))
        return False

    def dependencies(self, work_id: str) -> set[str]:
        return set(self._depends.get(work_id, set()))

    def resolve_state(self, work_id: str, outcomes: dict[str, DependencyOutcome]) -> DependentState:
        """Compute the dependent's state from its dependencies' outcomes.

        A FAILED dependency blocks the dependent (never fakes success); a PENDING
        one holds it WAITING; all SUCCEEDED makes it READY.
        """
        deps = self._depends.get(work_id, set())
        if not deps:
            return DependentState.READY
        statuses = [outcomes.get(d, DependencyOutcome.PENDING) for d in deps]
        if any(s == DependencyOutcome.FAILED for s in statuses):
            return DependentState.BLOCKED_BY_FAILURE
        if all(s == DependencyOutcome.SUCCEEDED for s in statuses):
            return DependentState.READY
        return DependentState.WAITING_DEPENDENCY
