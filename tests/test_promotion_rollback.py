"""03D — Promotion & Rollback verification (03D-01,02,04,05,06,07)."""

from __future__ import annotations

import pytest

from all_tomorrow.improve.promotion import (
    DeploymentPlan,
    DeploymentRef,
    MissingMonitoringPolicyError,
    MonitoringPolicy,
    Promoter,
    ProtectedChangeError,
    ProtectionClass,
    StaleBaselineError,
)


class FakePromptTarget:
    """Prompt/config alias-switch target with immutable versions."""

    def __init__(self, current="v1", verify_ok=True):
        self.current = current
        self.verify_ok = verify_ok
        self.applied = None
        self.rollbacks = 0

    def inspect_current(self):
        return self.current

    def validate_candidate(self, candidate_ref):
        return True

    def plan(self, candidate_ref, current_ref):
        return DeploymentPlan(candidate_ref=candidate_ref, previous_ref=current_ref,
                              steps=("create-version", "switch-alias"))

    def apply(self, plan):
        self.applied = plan
        self.current = plan.candidate_ref  # alias switched
        return DeploymentRef("d1", plan.candidate_ref, plan.previous_ref)

    def verify(self, deployment):
        return self.verify_ok

    def rollback(self, previous_ref, deployment):
        self.current = previous_ref  # idempotent: setting to the same value repeatedly
        self.rollbacks += 1
        return previous_ref


_POLICY = MonitoringPolicy(min_observations=3, hard_rollback_signals=("error_rate",))


# 03D-02: prompt/config atomic switch on success.
def test_03d_02_atomic_switch() -> None:
    t = FakePromptTarget(current="v1")
    p = Promoter(t)
    res = p.promote(candidate_ref="v2", accepted_baseline_ref="v1",
                    protection_class=ProtectionClass.ORDINARY, monitoring_policy=_POLICY)
    assert res.promoted and t.current == "v2"


# 03D-01: stale baseline blocks promotion.
def test_03d_01_stale_baseline_blocks() -> None:
    t = FakePromptTarget(current="v1-CHANGED")   # drifted from accepted "v1"
    p = Promoter(t)
    with pytest.raises(StaleBaselineError):
        p.promote(candidate_ref="v2", accepted_baseline_ref="v1",
                  protection_class=ProtectionClass.ORDINARY, monitoring_policy=_POLICY)


# 03D-04: verify failure rolls back, not recorded as success.
def test_03d_04_verify_failure_rolls_back() -> None:
    t = FakePromptTarget(current="v1", verify_ok=False)
    p = Promoter(t)
    res = p.promote(candidate_ref="v2", accepted_baseline_ref="v1",
                    protection_class=ProtectionClass.ORDINARY, monitoring_policy=_POLICY)
    assert not res.promoted and res.rolled_back
    assert t.current == "v1"  # rolled back to previous


# 03D-05: no monitoring policy → cannot auto-promote.
def test_03d_05_missing_policy_blocks() -> None:
    t = FakePromptTarget(current="v1")
    p = Promoter(t)
    with pytest.raises(MissingMonitoringPolicyError):
        p.promote(candidate_ref="v2", accepted_baseline_ref="v1",
                  protection_class=ProtectionClass.ORDINARY, monitoring_policy=None)


# 03D-07: protected/unknown classification cannot auto-apply.
def test_03d_07_protected_blocks() -> None:
    t = FakePromptTarget(current="v1")
    p = Promoter(t)
    for pc in (ProtectionClass.PROTECTED, ProtectionClass.UNKNOWN):
        with pytest.raises(ProtectedChangeError):
            p.promote(candidate_ref="v2", accepted_baseline_ref="v1",
                      protection_class=pc, monitoring_policy=_POLICY)


# 03D-06: repeated rollback is idempotent (same previous ref).
def test_03d_06_rollback_idempotent() -> None:
    t = FakePromptTarget(current="v2")
    p = Promoter(t)
    dep = DeploymentRef("d1", "v2", "v1")
    r1 = p.rollback("v1", dep)
    r2 = p.rollback("v1", dep)
    assert r1 == r2 == "v1"
    assert t.current == "v1"
