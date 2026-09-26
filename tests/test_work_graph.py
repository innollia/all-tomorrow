"""Stage 3.4A — Dynamic Work Graph verification (S3-34A-01,02)."""

from __future__ import annotations

import pytest

from all_tomorrow.work_graph import (
    CycleError,
    DependencyOutcome,
    DependentState,
    Relation,
    WorkGraph,
)


# S3-34A-01: a depends_on cycle is rejected.
def test_34a_01_cycle_rejected() -> None:
    g = WorkGraph()
    g.add_relation("b", Relation.DEPENDS_ON, "a")   # b depends on a
    g.add_relation("c", Relation.DEPENDS_ON, "b")   # c depends on b
    with pytest.raises(CycleError):
        g.add_relation("a", Relation.DEPENDS_ON, "c")   # a->c would cycle a->c->b->a
    with pytest.raises(CycleError):
        g.add_relation("x", Relation.DEPENDS_ON, "x")   # self-cycle


# S3-34A-02: a failed dependency blocks the dependent, never fakes success.
def test_34a_02_dependency_failure_blocks() -> None:
    g = WorkGraph()
    g.add_relation("dependent", Relation.DEPENDS_ON, "dep1")
    g.add_relation("dependent", Relation.DEPENDS_ON, "dep2")
    state = g.resolve_state("dependent", {
        "dep1": DependencyOutcome.SUCCEEDED,
        "dep2": DependencyOutcome.FAILED,
    })
    assert state == DependentState.BLOCKED_BY_FAILURE   # NOT succeeded


def test_34a_pending_waits() -> None:
    g = WorkGraph()
    g.add_relation("d", Relation.DEPENDS_ON, "dep")
    assert g.resolve_state("d", {"dep": DependencyOutcome.PENDING}) == DependentState.WAITING_DEPENDENCY


def test_34a_all_succeeded_ready() -> None:
    g = WorkGraph()
    g.add_relation("d", Relation.DEPENDS_ON, "dep1")
    g.add_relation("d", Relation.DEPENDS_ON, "dep2")
    state = g.resolve_state("d", {"dep1": DependencyOutcome.SUCCEEDED, "dep2": DependencyOutcome.SUCCEEDED})
    assert state == DependentState.READY


def test_34a_no_deps_ready() -> None:
    g = WorkGraph()
    assert g.resolve_state("solo", {}) == DependentState.READY


def test_34a_non_depends_relations_allowed() -> None:
    g = WorkGraph()
    # parent/blocks/supersedes/generated_by don't participate in the depends cycle check
    g.add_relation("child", Relation.PARENT, "parent")
    g.add_relation("a", Relation.SUPERSEDES, "b")
    assert g.dependencies("child") == set()
