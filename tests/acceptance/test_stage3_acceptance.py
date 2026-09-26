"""Stage 3 — Manager acceptance suite (01D / 02E / 03D / 04E).

End-to-end wiring of the Stage 3 packets with a single owner/source provenance,
demonstrating the load-bearing invariants hold together across sub-stages.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now

# personal ops (01)
from all_tomorrow.owners import OwnerFact, SourceKind, SourceRef, Truthiness, read_fact, write_fact, AuthorityError
from all_tomorrow.personal import BriefProjector, assemble_context, answer_what_should_i_do
from all_tomorrow.personal.school import ExtractedField, SchoolArtifactPipeline

# triggers & knowledge (02)
from all_tomorrow.watchers import ConditionWatcher, WatchMode, WebhookReceiver, WebhookError
from all_tomorrow.knowledge import KnowledgeStore, Lesson, LessonConflictError
from all_tomorrow.knowledge_outcomes import record_reuse, apply_outcome, ReuseOutcome, counts_as_success

# discovery & resources (03)
from all_tomorrow.discovery import run_discovery, DiscoverySource, SandboxPolicy, CredentialCanaryTripped
from all_tomorrow.workspaces import Workspace, WorkspaceProvenance, WorkspaceState, DirtyResetRefused

# long-horizon (04)
from all_tomorrow.work_graph import WorkGraph, Relation, DependencyOutcome, DependentState, CycleError
from all_tomorrow.milestones import MilestoneCriterion, ArtifactProvenance, ProgressEvidence, evaluate_progress, freeze_plan
from all_tomorrow.long_horizon import GoalRuntime
from all_tomorrow.feedback import Feedback, FeedbackKind, make_followup, ArtifactMismatchError


OWNER = "innollia"
SOURCE = "https://school.example/portal"


# ---- 01D personal operations acceptance ----

def test_01d_owner_conflict_and_freshness() -> None:
    canonical = OwnerFact("next_class", "Math 9am",
                          SourceRef("s-owner", SourceKind.OWNER_CANONICAL, utc_now()))
    stale = OwnerFact("homework", "essay",
                      SourceRef("s-cache", SourceKind.CACHE, utc_now() - timedelta(hours=9)))
    pack = assemble_context(["w1"], {"next_class": [canonical], "homework": [stale]})
    ans = answer_what_should_i_do(pack)
    assert any("Math 9am" in d for d in ans["do"])           # source-backed
    assert any("STALE_UNKNOWN" in a for a in ans["attention"])  # stale surfaced
    # derived summary cannot overwrite owner truth
    summary = OwnerFact("next_class", "wrong", SourceRef("sum", SourceKind.DERIVED_SUMMARY, utc_now()))
    with pytest.raises(Exception):
        write_fact(summary, has_owner_authority=True)


def test_01d_school_lineage_and_brief() -> None:
    p = SchoolArtifactPipeline()
    res = p.process(upload_artifact_id="u1", content_hash="h1",
                    fields=[ExtractedField("due", "2026-10-01", 0.95, 1, (0, 5), "v1"),
                            ExtractedField("blur", None, 0.0, 2, (0, 0), "v1")])
    assert res.work_id is not None                            # confident field → Work
    assert SchoolArtifactPipeline.unknown_regions(res)        # low-confidence surfaced
    brief = BriefProjector()
    first = brief.project(owner_id=OWNER, logical_period="2026-09-27",
                          pack=assemble_context([res.work_id], {}))
    dup = brief.project(owner_id=OWNER, logical_period="2026-09-27",
                        pack=assemble_context([res.work_id], {}))
    assert first is not None and dup is None                  # idempotent brief


# ---- 02E triggers & knowledge acceptance ----

def test_02e_watchers_and_lessons() -> None:
    w = ConditionWatcher(mode=WatchMode.EDGE)
    assert w.observe(condition=True, cursor="c1") is True
    assert w.observe(condition=None, cursor="c2") is False    # poll failure ≠ false
    ks = KnowledgeStore()
    c = ks.propose(Lesson("l1", "global", "prefer X", ("e1", "e2"), 0.5))
    with pytest.raises(LessonConflictError):
        ks.accept("l1", conflicts_with=("l0",))               # conflict not merged
    acc = ks.accept("l1")
    rec = record_reuse("l1", "w1", "run1")
    updated, linked = apply_outcome(acc, rec, ReuseOutcome.SUCCESS, outcome_ref="oc1")
    assert counts_as_success(linked) and updated.confidence > acc.confidence


# ---- 03D discovery & resources acceptance ----

def test_03d_discovery_and_workspace() -> None:
    with pytest.raises(CredentialCanaryTripped):
        run_discovery(DiscoverySource("lib", "1.0", "hh", "http://x"),
                      SandboxPolicy(), accessed_credential_names=["~/.aws/credentials"])
    ws = Workspace("wt1", "hostA", WorkspaceState.READY_DIRTY,
                   WorkspaceProvenance(SOURCE, "main", "abc", True, "/ws", "fleet"))
    with pytest.raises(DirtyResetRefused):
        ws.prepare_clean()                                    # no auto-reset
    assert ws.state == WorkspaceState.RECONCILIATION_REQUIRED


# ---- 04E long-horizon acceptance ----

def test_04e_graph_milestone_multiday_feedback() -> None:
    g = WorkGraph()
    g.add_relation("b", Relation.DEPENDS_ON, "a")
    with pytest.raises(CycleError):
        g.add_relation("a", Relation.DEPENDS_ON, "b")
    assert g.resolve_state("b", {"a": DependencyOutcome.FAILED}) == DependentState.BLOCKED_BY_FAILURE

    plan = freeze_plan("g1", [MilestoneCriterion("c1", "ship", requires_artifact=True)])
    art = ArtifactProvenance("a1", "h1", "repo", "MIT")
    assert evaluate_progress(plan, "c1", ProgressEvidence("c1", True, (art,)))

    rt = GoalRuntime("g1", plan.plan_id, ("b",), ("h1",))
    run1 = rt.reconcile_resource_change(new_executor="codex", reason="quota")
    assert rt.goal_id == "g1" and run1                        # identity preserved

    fb = Feedback("f1", "a1", "h1", FeedbackKind.EXPLICIT, "make it blue")
    with pytest.raises(ArtifactMismatchError):
        make_followup(fb, current_artifact_hash="DIFFERENT")
    sw = make_followup(fb, current_artifact_hash="h1")
    assert sw.from_feedback_id == "f1"
