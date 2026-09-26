"""Stage 3.4B — Milestone / Artifact Progress verification (S3-34B-01..03)."""

from __future__ import annotations

import pytest

from all_tomorrow.milestones import (
    ArtifactProvenance,
    MilestoneCriterion,
    MilestoneError,
    MilestoneError_ActivityOnly,
    ProgressEvidence,
    evaluate_progress,
    freeze_plan,
)


def _plan(**crit_kw):
    c = MilestoneCriterion(criterion_id="c1", description="ship feature", **crit_kw)
    return freeze_plan("g1", [c], version="1")


def _art():
    return ArtifactProvenance(artifact_id="a1", content_hash="h1", source="repo", license="MIT")


# S3-34B-01: plan is versioned and frozen.
def test_34b_01_plan_frozen_versioned() -> None:
    p = _plan()
    assert p.version == "1" and p.frozen_at is not None and len(p.criteria) == 1


# S3-34B-03: activity-only progress is rejected.
def test_34b_03_activity_only_rejected() -> None:
    p = _plan(requires_artifact=True)
    with pytest.raises(MilestoneError_ActivityOnly):
        evaluate_progress(p, "c1", ProgressEvidence(criterion_id="c1", outcome_satisfied=True,
                                                    work_count=50, tokens=10000))  # no artifact


# S3-34B-02: artifact-backed progress with provenance passes.
def test_34b_02_artifact_backed_progress() -> None:
    p = _plan(requires_artifact=True)
    ok = evaluate_progress(p, "c1", ProgressEvidence(criterion_id="c1", outcome_satisfied=True,
                                                     artifact_refs=(_art(),)))
    assert ok is True


def test_34b_artifact_missing_provenance_rejected() -> None:
    p = _plan(requires_artifact=True)
    bad = ArtifactProvenance(artifact_id="a1", content_hash="", source="")
    with pytest.raises(MilestoneError):
        evaluate_progress(p, "c1", ProgressEvidence(criterion_id="c1", outcome_satisfied=True,
                                                    artifact_refs=(bad,)))


def test_34b_test_pass_required() -> None:
    p = _plan(requires_artifact=True, requires_test_pass=True)
    e_no_test = ProgressEvidence(criterion_id="c1", outcome_satisfied=True, artifact_refs=(_art(),))
    assert evaluate_progress(p, "c1", e_no_test) is False
    e_test = ProgressEvidence(criterion_id="c1", outcome_satisfied=True, artifact_refs=(_art(),), tests_passed=True)
    assert evaluate_progress(p, "c1", e_test) is True


def test_34b_outcome_not_satisfied_false() -> None:
    p = _plan()
    assert evaluate_progress(p, "c1", ProgressEvidence(criterion_id="c1", outcome_satisfied=False,
                                                       artifact_refs=(_art(),))) is False
