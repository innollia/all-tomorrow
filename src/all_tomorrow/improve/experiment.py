"""03C — Generic Sandbox Experiment.

Compares baseline vs candidate on the SAME frozen case set + frozen criteria,
before any production change. The core runner knows no target-specific detail; a
per-target adapter runs cases in isolation (no production credential, disposable
workspace for code). The ExperimentSpec is an immutable content-hashed artifact
so a run is reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from all_tomorrow.domain.errors import DomainError


class ExperimentError(DomainError):
    pass


class UnsupportedTargetError(ExperimentError):
    pass


class CriteriaTamperError(ExperimentError):
    """Candidate touched the frozen criteria/case fixture → experiment invalid."""


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    proposal_id: str
    target_type: str
    baseline_ref: str
    candidate_ref: str
    case_set_ref: str
    case_set_hash: str
    frozen_criteria_ref: str
    frozen_criteria_hash: str
    timeout_seconds: float = 60.0
    network_allowed: bool = False

    def spec_hash(self) -> str:
        return _hash({
            "proposal": self.proposal_id, "target": self.target_type,
            "baseline": self.baseline_ref, "candidate": self.candidate_ref,
            "cases": self.case_set_hash, "criteria": self.frozen_criteria_hash,
        })


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    case_id: str
    baseline_result_ref: str
    candidate_result_ref: str


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    spec_hash: str
    proposal_id: str
    baseline_ref: str
    candidate_ref: str
    case_outcomes: tuple[CaseOutcome, ...]
    artifact_refs: tuple[str, ...]
    failure_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure_reason is None


class ExperimentAdapter(Protocol):
    """Target-specific runner. MUST isolate from production (no prod secret)."""

    target_type: str

    async def run_case(self, ref: str, case_id: str, *, network_allowed: bool) -> str:
        """Run one case against ``ref`` (baseline or candidate); return a result ref."""
        ...

    def touches_protected(self, candidate_ref: str) -> bool:
        """True if the candidate would touch the evaluator/case fixture/protected config."""
        ...


class SandboxRunner:
    """Core runner: identical frozen cases for baseline+candidate, isolated."""

    def __init__(self, adapters: dict[str, ExperimentAdapter]) -> None:
        self._adapters = adapters

    async def run(
        self,
        spec: ExperimentSpec,
        case_ids: list[str],
        *,
        observed_case_set_hash: str,
        observed_criteria_hash: str,
    ) -> ExperimentResult:
        adapter = self._adapters.get(spec.target_type)
        if adapter is None:
            raise UnsupportedTargetError(f"no adapter for target {spec.target_type}")

        # 03C-02: baseline and candidate run the EXACT frozen case set.
        if observed_case_set_hash != spec.case_set_hash:
            raise ExperimentError("case set hash drift; not the frozen cases")
        # 03C-03: criteria tamper invalidates the experiment.
        if observed_criteria_hash != spec.frozen_criteria_hash:
            raise CriteriaTamperError("frozen criteria hash changed")
        if adapter.touches_protected(spec.candidate_ref):
            raise CriteriaTamperError("candidate touches evaluator/case fixture/protected config")

        outcomes: list[CaseOutcome] = []
        try:
            for cid in case_ids:
                # SAME case id for both refs → apples-to-apples comparison.
                base = await adapter.run_case(spec.baseline_ref, cid, network_allowed=spec.network_allowed)
                cand = await adapter.run_case(spec.candidate_ref, cid, network_allowed=spec.network_allowed)
                outcomes.append(CaseOutcome(cid, base, cand))
        except Exception as exc:  # 03C-01: candidate failure never touches production
            return ExperimentResult(
                spec_hash=spec.spec_hash(), proposal_id=spec.proposal_id,
                baseline_ref=spec.baseline_ref, candidate_ref=spec.candidate_ref,
                case_outcomes=tuple(outcomes), artifact_refs=(),
                failure_reason=f"candidate case error: {exc}",
            )

        return ExperimentResult(
            spec_hash=spec.spec_hash(), proposal_id=spec.proposal_id,
            baseline_ref=spec.baseline_ref, candidate_ref=spec.candidate_ref,
            case_outcomes=tuple(outcomes),
            artifact_refs=tuple(f"result:{o.case_id}" for o in outcomes),
        )
