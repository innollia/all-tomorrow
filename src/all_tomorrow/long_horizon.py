"""Stage 3.4C — Multi-day Resume & Resource Change.

A long-horizon Goal survives process/day boundaries: the resume ContextPack is
rebuilt from DURABLE state (Goal/Work/Milestone/Artifact records), never from a
chat transcript. A resource change (offline / quota / provider swap) reconciles
into a NEW Run under the SAME Goal — Goal and milestone identity are never lost —
and the executor switch is recorded with provenance. Replan/graph churn is bounded
by a per-Goal budget so a resource flap cannot storm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id


class LongHorizonError(DomainError):
    pass


class ReplanStormError(LongHorizonError):
    pass


@dataclass(frozen=True, slots=True)
class ResumeContextPack:
    goal_id: str
    milestone_plan_id: str
    open_work_ids: tuple[str, ...]
    last_artifact_hashes: tuple[str, ...]
    built_from: str = "durable_state"   # never "transcript"


@dataclass(frozen=True, slots=True)
class ExecutorSwitch:
    from_executor: str
    to_executor: str
    reason: str          # offline / quota / provider_change


@dataclass(slots=True)
class GoalRuntime:
    goal_id: str
    milestone_plan_id: str
    open_work_ids: tuple[str, ...] = ()
    artifact_hashes: tuple[str, ...] = ()
    current_executor: str = "default"
    run_id: str | None = None
    replan_count: int = 0
    max_replans: int = 20
    switches: list[ExecutorSwitch] = field(default_factory=list)

    def resume(self) -> ResumeContextPack:
        """Rebuild the context pack from durable fields only (S3-34C-01)."""
        return ResumeContextPack(
            goal_id=self.goal_id,
            milestone_plan_id=self.milestone_plan_id,
            open_work_ids=self.open_work_ids,
            last_artifact_hashes=self.artifact_hashes,
        )

    def reconcile_resource_change(self, *, new_executor: str, reason: str) -> str:
        """A resource change starts a NEW Run on the SAME Goal (S3-34C-02,03,04)."""
        # S3-34C-04: bound replan/graph churn.
        self.replan_count += 1
        if self.replan_count > self.max_replans:
            raise ReplanStormError(
                f"goal {self.goal_id} exceeded replan budget ({self.max_replans})"
            )
        # S3-34C-02: record the executor switch provenance.
        if new_executor != self.current_executor:
            self.switches.append(ExecutorSwitch(from_executor=self.current_executor,
                                                to_executor=new_executor, reason=reason))
            self.current_executor = new_executor
        # S3-34C-03: new Run, but Goal + milestone identity unchanged.
        self.run_id = new_id("run")
        return self.run_id
