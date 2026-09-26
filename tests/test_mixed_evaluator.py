"""03B — Mixed Evaluator verification (03B-01..06)."""

from __future__ import annotations

from all_tomorrow.improve.evaluator import (
    Criterion,
    Decision,
    Direction,
    MetricObservation,
    UserEvidence,
    evaluate,
)


def _c(cid, direction=Direction.HIGHER_BETTER, required=True, hard=False, tol=0.0, opt_unknown=False):
    return Criterion(cid, direction, required, hard, tol, opt_unknown)


def _o(cid, base, cand):
    return MetricObservation(cid, base, cand)


# 03B-01: a hard regression is not offset by average improvement.
def test_03b_01_hard_regression_not_offset() -> None:
    criteria = [
        _c("success_rate", Direction.HIGHER_BETTER, required=True, hard=True),
        _c("latency", Direction.LOWER_BETTER, required=True),
    ]
    obs = {
        "success_rate": _o("success_rate", 0.9, 0.5),   # big regression (hard)
        "latency": _o("latency", 200, 50),              # big improvement
    }
    d = evaluate(criteria, obs)
    assert d.decision == Decision.REJECT


# 03B-02: candidate tampering with frozen criteria → REJECT.
def test_03b_02_candidate_tamper_rejects() -> None:
    d = evaluate([_c("x")], {"x": _o("x", 1, 2)}, candidate_tampered_criteria=True)
    assert d.decision == Decision.REJECT


# 03B-03: missing metric is UNKNOWN, not 0.
def test_03b_03_missing_is_unknown() -> None:
    criteria = [_c("success_rate", required=True)]
    d = evaluate(criteria, {"success_rate": _o("success_rate", 0.9, None)})
    assert "success_rate" in d.unknown_criteria
    assert d.decision == Decision.NEED_MORE_EVIDENCE


# 03B-04: user contradiction preserved → NEED_MORE_EVIDENCE, not silent accept.
def test_03b_04_user_conflict_preserved() -> None:
    criteria = [_c("latency", Direction.LOWER_BETTER)]
    obs = {"latency": _o("latency", 200, 100)}  # improved
    d = evaluate(criteria, obs, user=UserEvidence(contradicts=True))
    assert d.decision == Decision.NEED_MORE_EVIDENCE


# 03B-05: no automatic ACCEPT without an observed improvement signal.
def test_03b_05_no_accept_without_improvement() -> None:
    criteria = [_c("latency", Direction.LOWER_BETTER, tol=100)]
    obs = {"latency": _o("latency", 200, 200)}  # unchanged (within tolerance, no improvement)
    d = evaluate(criteria, obs)
    assert d.decision == Decision.NEED_MORE_EVIDENCE


# Happy ACCEPT: required pass, no hard regression, improvement observed.
def test_03b_accept_path() -> None:
    criteria = [_c("latency", Direction.LOWER_BETTER)]
    obs = {"latency": _o("latency", 200, 120)}
    d = evaluate(criteria, obs)
    assert d.decision == Decision.ACCEPT
    assert "latency" in d.improved_signals


# 03B: protected boundary violation → immediate REJECT (LLM reason cannot override).
def test_03b_protected_violation_rejects() -> None:
    d = evaluate([_c("x")], {"x": _o("x", 1, 2)}, protected_violation=True)
    assert d.decision == Decision.REJECT


# 03B-03: required UNKNOWN allowed only when pre-declared optional_unknown_ok.
def test_03b_required_unknown_allowed_if_predeclared() -> None:
    criteria = [
        _c("optional_metric", required=True, opt_unknown=True),
        _c("latency", Direction.LOWER_BETTER),
    ]
    obs = {
        "optional_metric": _o("optional_metric", None, None),  # UNKNOWN but pre-declared ok
        "latency": _o("latency", 200, 100),
    }
    d = evaluate(criteria, obs)
    assert d.decision == Decision.ACCEPT
