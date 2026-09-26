"""Stage 3.4C — Multi-day resume & resource change (S3-34C-01..04)."""

from __future__ import annotations

import pytest

from all_tomorrow.long_horizon import (
    GoalRuntime,
    ReplanStormError,
    ResumeContextPack,
)


def _rt(**kw):
    return GoalRuntime(goal_id="g1", milestone_plan_id="mp1",
                       open_work_ids=("w1", "w2"), artifact_hashes=("h1",), **kw)


# S3-34C-01: resume pack is built from durable state, not the transcript.
def test_34c_01_resume_from_durable_state() -> None:
    pack = _rt().resume()
    assert isinstance(pack, ResumeContextPack)
    assert pack.built_from == "durable_state"
    assert pack.goal_id == "g1" and pack.open_work_ids == ("w1", "w2")


# S3-34C-02: executor switch is recorded with provenance.
def test_34c_02_executor_switch_provenance() -> None:
    rt = _rt()
    rt.reconcile_resource_change(new_executor="codex", reason="quota")
    assert len(rt.switches) == 1
    sw = rt.switches[0]
    assert sw.from_executor == "default" and sw.to_executor == "codex" and sw.reason == "quota"


# S3-34C-03: resource failure preserves Goal + milestone identity; new Run.
def test_34c_03_identity_preserved() -> None:
    rt = _rt()
    run1 = rt.reconcile_resource_change(new_executor="codex", reason="offline")
    assert rt.goal_id == "g1" and rt.milestone_plan_id == "mp1"   # identity intact
    run2 = rt.reconcile_resource_change(new_executor="default", reason="recovered")
    assert run1 != run2                                            # each reconcile → new Run
    assert rt.goal_id == "g1"


# S3-34C-04: replan storm is bounded by budget.
def test_34c_04_replan_storm_bounded() -> None:
    rt = _rt(max_replans=3)
    for _ in range(3):
        rt.reconcile_resource_change(new_executor="codex", reason="flap")
    with pytest.raises(ReplanStormError):
        rt.reconcile_resource_change(new_executor="codex", reason="flap")
