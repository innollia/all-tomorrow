"""02D — Autonomous Lineage, Dedup and Budget.

Limits autonomous recursion/work-storms with a DB-enforceable dedup constraint
and a race-safe budget ledger — not application-level "select then insert".

- Dedup fingerprint is a versioned canonical key (action type + target ids +
  normalized objective semantic key + sorted stable evidence refs + materializer
  schema version), NOT a hash of the free-form title. Wording variation that
  maps to the same canonical key dedups to one Work; different stable evidence
  is allowed as a separate Work.
- Budget ledger reserves/consumes under a lock (stand-in for a DB transaction/
  CAS) so concurrent reservations cannot overcommit the ceiling. Unknown actual
  cost is NEVER settled as 0 — it is recorded as UNKNOWN and blocks further
  autonomous spending (fail-closed). Budget exhaustion never deletes state.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from all_tomorrow.domain.errors import DomainError, InvariantViolationError
from all_tomorrow.domain.ids import utc_now


FINGERPRINT_VERSION = "1"


class DedupConflictError(InvariantViolationError):
    """An open autonomous Work with the same fingerprint already exists."""


class BudgetExceededError(DomainError):
    """A reservation would exceed a lineage budget ceiling (fail-closed)."""


class UnknownCostError(DomainError):
    """An actual cost is unknown; further autonomous spend is blocked."""


# ---------------------------------------------------------------------------
# Lineage + fingerprint
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AutonomousLineage:
    root_autonomous_lineage_id: str
    origin: str
    source_snapshot_id: str
    decision_id: str
    parent_work_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


def _normalize_objective(objective: str) -> str:
    """Versioned normalization: lowercase, collapse whitespace, strip punctuation.

    Changing this is a fingerprint_version bump (documented conflict policy).
    """
    import re
    s = objective.strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def dedup_fingerprint(
    *,
    action_type: str,
    target_goal_id: str,
    target_project_id: str | None,
    objective: str,
    evidence_refs: list[str] | tuple[str, ...],
    materializer_schema_version: str,
    fingerprint_version: str = FINGERPRINT_VERSION,
) -> str:
    """Canonical dedup key. Wording variation collapses; stable evidence separates."""
    canonical = "\x1f".join([
        f"fpv={fingerprint_version}",
        f"action={action_type}",
        f"goal={target_goal_id}",
        f"project={target_project_id or ''}",
        f"obj={_normalize_objective(objective)}",
        "evidence=" + ",".join(sorted(evidence_refs)),
        f"mat={materializer_schema_version}",
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Budget ledger
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BudgetConfig:
    config_version: str
    max_created_work: int
    max_tokens: int
    max_concurrent_runs: int
    max_wall_clock_age: timedelta


@dataclass(slots=True)
class _LineageUsage:
    created_work: int = 0
    tokens_consumed: int = 0
    active_runs: int = 0
    has_unknown_cost: bool = False


class BudgetLedger:
    """Race-safe reserve/consume for one config. Lock stands in for a DB tx/CAS."""

    def __init__(self, config: BudgetConfig) -> None:
        self.config = config
        self._lock = asyncio.Lock()
        self._usage: dict[str, _LineageUsage] = {}
        self._created_at: dict[str, datetime] = {}

    def _u(self, lineage_id: str) -> _LineageUsage:
        return self._usage.setdefault(lineage_id, _LineageUsage())

    async def register_lineage(self, lineage_id: str, created_at: datetime | None = None) -> None:
        async with self._lock:
            self._created_at.setdefault(lineage_id, created_at or utc_now())
            self._u(lineage_id)

    async def reserve_work(self, lineage_id: str) -> None:
        async with self._lock:
            self._guard_no_unknown(lineage_id)
            self._guard_age(lineage_id)
            u = self._u(lineage_id)
            if u.created_work + 1 > self.config.max_created_work:
                raise BudgetExceededError(f"max_created_work exceeded for {lineage_id}")
            u.created_work += 1

    async def reserve_run_slot(self, lineage_id: str) -> None:
        async with self._lock:
            self._guard_no_unknown(lineage_id)
            u = self._u(lineage_id)
            if u.active_runs + 1 > self.config.max_concurrent_runs:
                raise BudgetExceededError(f"max_concurrent_runs exceeded for {lineage_id}")
            u.active_runs += 1

    async def release_run_slot(self, lineage_id: str) -> None:
        async with self._lock:
            u = self._u(lineage_id)
            u.active_runs = max(0, u.active_runs - 1)

    async def consume_tokens(self, lineage_id: str, tokens: int | None) -> None:
        """Consume known token cost; None means UNKNOWN → block further spend.

        A failed call that still incurred provider cost must pass its tokens here
        too. Unknown cost is never settled as 0.
        """
        async with self._lock:
            u = self._u(lineage_id)
            if tokens is None:
                u.has_unknown_cost = True
                return
            u.tokens_consumed += tokens
            if u.tokens_consumed > self.config.max_tokens:
                # Consume is recorded (cost really happened); further reserves fail.
                pass

    def _guard_no_unknown(self, lineage_id: str) -> None:
        if self._u(lineage_id).has_unknown_cost:
            raise UnknownCostError(
                f"lineage {lineage_id} has UNKNOWN cost; autonomous spend blocked (fail-closed)"
            )
        if self._u(lineage_id).tokens_consumed > self.config.max_tokens:
            raise BudgetExceededError(f"token budget exhausted for {lineage_id}")

    def _guard_age(self, lineage_id: str) -> None:
        created = self._created_at.get(lineage_id)
        if created is not None and utc_now() - created > self.config.max_wall_clock_age:
            raise BudgetExceededError(f"wall-clock age exceeded for {lineage_id}")

    def usage(self, lineage_id: str) -> _LineageUsage:
        return self._u(lineage_id)


class OpenWorkDedupIndex:
    """Transaction-safe dedup: at most one OPEN autonomous Work per fingerprint.

    ``claim`` is the single atomic operation (stand-in for a unique partial
    constraint); it never does select-then-insert. ``release`` frees the key when
    the Work terminates so a later distinct decision can reopen it.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._open: dict[str, str] = {}  # fingerprint -> work_id

    async def claim(self, fingerprint: str, work_id: str) -> None:
        async with self._lock:
            existing = self._open.get(fingerprint)
            if existing is not None and existing != work_id:
                raise DedupConflictError(
                    f"open autonomous Work already exists for fingerprint {fingerprint[:12]}…"
                )
            self._open[fingerprint] = work_id

    async def release(self, fingerprint: str) -> None:
        async with self._lock:
            self._open.pop(fingerprint, None)
