"""03B — Mixed Evaluator.

Combines common metrics + pre-frozen dynamic criteria + user evidence into an
ACCEPT / REJECT / NEED_MORE_EVIDENCE decision, where a hard regression is NEVER
offset by an average improvement. An LLM evaluator may supply a reason but cannot
override this hard policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Direction(StrEnum):
    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEED_MORE_EVIDENCE = "NEED_MORE_EVIDENCE"


UNKNOWN = None  # a metric value of None means UNKNOWN, never treated as 0.


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    direction: Direction
    required: bool
    is_hard_invariant: bool          # a hard invariant failure = immediate REJECT
    tolerance: float = 0.0           # allowed regression before it counts as a fail
    optional_unknown_ok: bool = False  # required metric may be UNKNOWN only if pre-declared


@dataclass(frozen=True, slots=True)
class MetricObservation:
    criterion_id: str
    baseline: float | None
    candidate: float | None


@dataclass(frozen=True, slots=True)
class UserEvidence:
    contradicts: bool = False        # explicit user feedback opposing the change
    correction_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationDecision:
    decision: Decision
    reasons: tuple[str, ...]
    improved_signals: tuple[str, ...]
    unknown_criteria: tuple[str, ...]


def _improved(c: Criterion, o: MetricObservation) -> bool | None:
    if o.baseline is None or o.candidate is None:
        return None
    if c.direction == Direction.HIGHER_BETTER:
        return o.candidate > o.baseline
    return o.candidate < o.baseline


def _regressed_beyond_tolerance(c: Criterion, o: MetricObservation) -> bool | None:
    if o.baseline is None or o.candidate is None:
        return None
    if c.direction == Direction.HIGHER_BETTER:
        drop = o.baseline - o.candidate
    else:
        drop = o.candidate - o.baseline
    return drop > c.tolerance


def evaluate(
    criteria: list[Criterion],
    observations: dict[str, MetricObservation],
    *,
    user: UserEvidence | None = None,
    integrity_ok: bool = True,
    candidate_tampered_criteria: bool = False,
    case_sets_match: bool = True,
    protected_violation: bool = False,
) -> EvaluationDecision:
    reasons: list[str] = []
    improved: list[str] = []
    unknown: list[str] = []

    # --- Immediate REJECT conditions (hard, cannot be offset) --------------
    if not integrity_ok:
        return EvaluationDecision(Decision.REJECT, ("evidence integrity failure",), (), ())
    if candidate_tampered_criteria:
        return EvaluationDecision(Decision.REJECT, ("candidate tampered frozen criteria/evaluator",), (), ())
    if not case_sets_match:
        return EvaluationDecision(Decision.REJECT, ("baseline/candidate case set mismatch",), (), ())
    if protected_violation:
        return EvaluationDecision(Decision.REJECT, ("protected/security boundary violation",), (), ())

    for c in criteria:
        o = observations.get(c.id)
        if o is None or o.baseline is None or o.candidate is None:
            unknown.append(c.id)
            if c.is_hard_invariant:
                # hard invariant cannot be UNKNOWN
                reasons.append(f"hard invariant {c.id} UNKNOWN")
            continue
        if _regressed_beyond_tolerance(c, o):
            if c.is_hard_invariant or c.required:
                reasons.append(f"hard regression on {c.id}")
        if _improved(c, o):
            improved.append(c.id)

    # A hard regression anywhere → REJECT regardless of other improvements.
    if any(r.startswith("hard regression") for r in reasons):
        return EvaluationDecision(Decision.REJECT, tuple(reasons), tuple(improved), tuple(unknown))
    if any("hard invariant" in r for r in reasons):
        return EvaluationDecision(Decision.REJECT, tuple(reasons), tuple(improved), tuple(unknown))

    # --- Required-metric UNKNOWN handling ---------------------------------
    for c in criteria:
        if c.required and c.id in unknown and not c.optional_unknown_ok:
            reasons.append(f"required criterion {c.id} UNKNOWN (not pre-declared optional)")
            return EvaluationDecision(Decision.NEED_MORE_EVIDENCE, tuple(reasons), tuple(improved), tuple(unknown))

    # --- User contradiction preserved -------------------------------------
    if user is not None and user.contradicts:
        reasons.append("user evidence contradicts; needs more evidence to resolve")
        return EvaluationDecision(Decision.NEED_MORE_EVIDENCE, tuple(reasons), tuple(improved), tuple(unknown))

    # --- ACCEPT requires at least one real predeclared improvement signal --
    if not improved:
        reasons.append("no observed predeclared improvement signal")
        return EvaluationDecision(Decision.NEED_MORE_EVIDENCE, tuple(reasons), tuple(improved), tuple(unknown))

    return EvaluationDecision(Decision.ACCEPT, ("required pass, no hard regression, improvement observed",),
                              tuple(improved), tuple(unknown))
