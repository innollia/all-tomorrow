"""Stage 3.4B — Milestone / Artifact Progress.

A Goal starts with a versioned, frozen milestone/evaluation plan. Real progress
is an Outcome backed by immutable ArtifactRefs and/or tests — a raw activity
count (Work created, tokens, files touched) is NOT progress and is rejected as
such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class MilestoneError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class MilestoneCriterion:
    criterion_id: str
    description: str
    requires_artifact: bool = True
    requires_test_pass: bool = False


@dataclass(frozen=True, slots=True)
class MilestonePlan:
    plan_id: str
    goal_id: str
    version: str
    criteria: tuple[MilestoneCriterion, ...]
    frozen_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    artifact_id: str
    content_hash: str
    source: str
    license: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressEvidence:
    criterion_id: str
    outcome_satisfied: bool
    artifact_refs: tuple[ArtifactProvenance, ...] = ()
    tests_passed: bool = False
    # activity metrics are recorded but NEVER count as progress
    work_count: int = 0
    tokens: int = 0


class MilestoneError_ActivityOnly(MilestoneError):
    pass


def freeze_plan(goal_id: str, criteria: list[MilestoneCriterion], *, version: str = "1") -> MilestonePlan:
    return MilestonePlan(plan_id=new_id("mplan"), goal_id=goal_id, version=version,
                         criteria=tuple(criteria))


def evaluate_progress(plan: MilestonePlan, criterion_id: str, evidence: ProgressEvidence) -> bool:
    """Return True only if the frozen criterion is met by real evidence.

    Activity-only evidence (no artifact / no test, just counts) is rejected.
    """
    crit = next((c for c in plan.criteria if c.criterion_id == criterion_id), None)
    if crit is None:
        raise MilestoneError(f"unknown criterion {criterion_id}")
    if not evidence.outcome_satisfied:
        return False
    if crit.requires_artifact and not evidence.artifact_refs:
        raise MilestoneError_ActivityOnly(
            f"criterion {criterion_id} needs an artifact; activity counts are not progress"
        )
    if crit.requires_test_pass and not evidence.tests_passed:
        return False
    # An artifact ref must carry provenance (hash + source).
    for a in evidence.artifact_refs:
        if not a.content_hash or not a.source:
            raise MilestoneError("artifact missing hash/source provenance")
    return True
