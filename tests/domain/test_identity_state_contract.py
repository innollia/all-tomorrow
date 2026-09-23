from __future__ import annotations

import pytest

from all_tomorrow.domain import (
    ActiveRunLimitExceededError,
    CanonicalError,
    CompletionEvidence,
    ErrorCategory,
    EventRecord,
    ExecutionRef,
    GoalRecord,
    GoalStatus,
    InvalidStateTransitionError,
    MissingCompletionEvidenceError,
    OutcomeRecord,
    OutcomeStatus,
    ProjectRecord,
    ProjectStatus,
    RunRecord,
    RunStatus,
    SourceRef,
    TargetType,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
    WorkRecord,
    WorkStatus,
    assert_active_runs_invariant,
    new_event_id,
    new_goal_id,
    new_outcome_id,
    new_project_id,
    new_run_id,
    new_work_id,
    transition_goal,
    transition_run,
    transition_work,
    utc_now,
)


class TestStateTransitions:
    """S0-00B1-01: Goal/Work/Run transition table tests."""

    def test_goal_happy_path_transitions(self) -> None:
        goal = GoalRecord(
            goal_id=new_goal_id(),
            user_id="user_123",
            title="Implement resilient researcher",
        )
        assert goal.status == GoalStatus.ACTIVE
        assert not goal.is_terminal()

        # ACTIVE -> WAITING
        waiting_goal = transition_goal(goal, GoalStatus.WAITING)
        assert waiting_goal.status == GoalStatus.WAITING
        assert waiting_goal.revision == goal.revision + 1

        # WAITING -> ACTIVE
        active_goal = transition_goal(waiting_goal, GoalStatus.ACTIVE)
        assert active_goal.status == GoalStatus.ACTIVE

        # ACTIVE -> SUCCEEDED requires evidence
        evidence = CompletionEvidence(
            criterion_ref="crit_researcher_done_v1",
            evaluator_ref="eval_human_operator",
            evaluator_version="1.0.0",
            observed_values={"reports_generated": 5},
        )
        succeeded_goal = transition_goal(active_goal, GoalStatus.SUCCEEDED, evidence=evidence)
        assert succeeded_goal.status == GoalStatus.SUCCEEDED
        assert succeeded_goal.is_terminal()
        assert succeeded_goal.terminal_at is not None

    def test_work_happy_path_transitions(self) -> None:
        work = WorkRecord(
            work_id=new_work_id(),
            goal_id=new_goal_id(),
            title="Spike durable backend",
        )
        assert work.status == WorkStatus.PENDING
        assert not work.is_terminal()

        # PENDING -> RUNNING
        running_work = transition_work(work, WorkStatus.RUNNING)
        assert running_work.status == WorkStatus.RUNNING

        # RUNNING -> WAITING
        waiting_work = transition_work(running_work, WorkStatus.WAITING)
        assert waiting_work.status == WorkStatus.WAITING

        # WAITING -> RUNNING
        resumed_work = transition_work(waiting_work, WorkStatus.RUNNING)
        assert resumed_work.status == WorkStatus.RUNNING

        # RUNNING -> SUCCEEDED requires evidence
        evidence = CompletionEvidence(
            criterion_ref="crit_spike_dbos_matrix",
            evaluator_ref="eval_harness_test_suite",
            evaluator_version="2.0",
            observed_values={"tests_passed": 12, "failures": 0},
        )
        succeeded_work = transition_work(resumed_work, WorkStatus.SUCCEEDED, evidence=evidence)
        assert succeeded_work.status == WorkStatus.SUCCEEDED
        assert succeeded_work.is_terminal()
        assert succeeded_work.terminal_at is not None

    def test_run_transitions(self) -> None:
        run = RunRecord(
            run_id=new_run_id(),
            work_id=new_work_id(),
            status=RunStatus.STARTING,
        )
        assert run.status == RunStatus.STARTING
        assert run.is_active()
        assert not run.is_terminal()

        # Attach execution ref during transition to RUNNING
        ref = ExecutionRef(backend="dbos", execution_id="wf_exec_999", execution_version=1)
        running_run = transition_run(run, RunStatus.RUNNING, execution_ref=ref)
        assert running_run.status == RunStatus.RUNNING
        assert running_run.execution_ref == ref

        # RUNNING -> WAITING
        waiting_run = transition_run(running_run, RunStatus.WAITING)
        assert waiting_run.status == RunStatus.WAITING

        # WAITING -> CANCEL_REQUESTED -> CANCELLED
        canceling_run = transition_run(waiting_run, RunStatus.CANCEL_REQUESTED)
        assert canceling_run.status == RunStatus.CANCEL_REQUESTED
        assert canceling_run.is_active()

        cancelled_run = transition_run(canceling_run, RunStatus.CANCELLED)
        assert cancelled_run.status == RunStatus.CANCELLED
        assert not cancelled_run.is_active()
        assert cancelled_run.is_terminal()
        assert cancelled_run.terminal_at is not None


class TestActiveRunInvariant:
    """S0-00B1-02: Active Run invariant (default max 1 active Run per Work)."""

    def test_single_active_run_allowed(self) -> None:
        work_id = new_work_id()
        r1 = RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.STARTING)
        assert_active_runs_invariant([r1], max_active=1)

    def test_terminal_and_active_run_allowed(self) -> None:
        work_id = new_work_id()
        r1 = RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.FAILED, terminal_at=utc_now())
        r2 = RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.STARTING)
        assert_active_runs_invariant([r1, r2], max_active=1)

    def test_two_active_runs_forbidden_negative_fixture(self) -> None:
        work_id = new_work_id()
        r1 = RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.RUNNING)
        r2 = RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.STARTING)
        with pytest.raises(ActiveRunLimitExceededError, match="Active run limit exceeded"):
            assert_active_runs_invariant([r1, r2], max_active=1)


class TestCompletionEvidenceRequirements:
    """S0-00B1-03: CompletionEvidence required for Work/Goal SUCCEEDED."""

    def test_work_success_without_evidence_forbidden(self) -> None:
        work = WorkRecord(work_id=new_work_id(), goal_id=new_goal_id(), title="Work item", status=WorkStatus.RUNNING)
        with pytest.raises(MissingCompletionEvidenceError, match="Cannot transition WORK"):
            transition_work(work, WorkStatus.SUCCEEDED, evidence=None)

    def test_goal_success_without_evidence_forbidden(self) -> None:
        goal = GoalRecord(goal_id=new_goal_id(), user_id="user_1", title="Goal item", status=GoalStatus.ACTIVE)
        with pytest.raises(MissingCompletionEvidenceError, match="Cannot transition GOAL"):
            transition_goal(goal, GoalStatus.SUCCEEDED, evidence=None)

    def test_unsatisfied_outcome_record_forbidden(self) -> None:
        work_id = new_work_id()
        work = WorkRecord(work_id=work_id, goal_id=new_goal_id(), title="Work item", status=WorkStatus.RUNNING)
        outcome = OutcomeRecord(
            outcome_id=new_outcome_id(),
            target_type=TargetType.WORK,
            target_id=str(work_id),
            status=OutcomeStatus.NOT_SATISFIED,
            evidence=None,
        )
        with pytest.raises(MissingCompletionEvidenceError, match="is not SATISFIED"):
            transition_work(work, WorkStatus.SUCCEEDED, evidence=outcome)

    def test_run_success_does_not_imply_work_success(self) -> None:
        work = WorkRecord(work_id=new_work_id(), goal_id=new_goal_id(), title="Work item", status=WorkStatus.RUNNING)
        run = RunRecord(run_id=new_run_id(), work_id=work.work_id, status=RunStatus.RUNNING)
        succeeded_run = transition_run(run, RunStatus.SUCCEEDED)
        assert succeeded_run.status == RunStatus.SUCCEEDED
        # Work remains RUNNING until verified CompletionEvidence is provided
        assert work.status == WorkStatus.RUNNING


class TestNegativeFixtures:
    """Negative fixtures required by 00B-1."""

    def test_terminal_revive_forbidden(self) -> None:
        # Goal terminal revive
        evidence = CompletionEvidence(criterion_ref="c", evaluator_ref="e", evaluator_version="1")
        goal = GoalRecord(goal_id=new_goal_id(), user_id="u", title="g", status=GoalStatus.ACTIVE)
        succeeded_goal = transition_goal(goal, GoalStatus.SUCCEEDED, evidence=evidence)
        with pytest.raises(TerminalReviveError, match="Cannot transition terminal Goal"):
            transition_goal(succeeded_goal, GoalStatus.ACTIVE)

        # Work terminal revive
        work = WorkRecord(work_id=new_work_id(), goal_id=new_goal_id(), title="w", status=WorkStatus.PENDING)
        cancelled_work = transition_work(work, WorkStatus.CANCELLED)
        with pytest.raises(TerminalReviveError, match="Cannot transition terminal Work"):
            transition_work(cancelled_work, WorkStatus.RUNNING)

        # Run terminal revive
        run = RunRecord(run_id=new_run_id(), work_id=new_work_id(), status=RunStatus.STARTING)
        failed_run = transition_run(run, RunStatus.FAILED)
        with pytest.raises(TerminalReviveError, match="Cannot transition terminal Run"):
            transition_run(failed_run, RunStatus.RUNNING)

    def test_work_level_execution_ref_forbidden(self) -> None:
        with pytest.raises(WorkExecutionRefForbiddenError, match="Work records must not contain external execution references"):
            WorkRecord(
                work_id=new_work_id(),
                goal_id=new_goal_id(),
                title="Invalid work",
                execution_ref=ExecutionRef(backend="dbos", execution_id="123"),  # type: ignore[call-arg]
            )

        with pytest.raises(WorkExecutionRefForbiddenError, match="Work records must not contain external execution references"):
            WorkRecord(
                work_id=new_work_id(),
                goal_id=new_goal_id(),
                title="Invalid work",
                execution_backend="dbos",  # type: ignore[call-arg]
            )


class TestSchemasAndCanonicalContracts:
    """S0-00B1-04: Canonical schemas for Event, Error, SourceRef, Project."""

    def test_event_record_schema_and_ordering(self) -> None:
        e1 = EventRecord(
            event_id=new_event_id(),
            event_type="work.started",
            actor_ref="orchestrator",
            correlation_id="corr_abc",
            schema_version=1,
            subject_refs={"work_id": "w_1"},
        )
        e2 = EventRecord(
            event_id=new_event_id(),
            event_type="work.completed",
            actor_ref="evaluator",
            correlation_id="corr_abc",
            schema_version=1,
            subject_refs={"work_id": "w_1"},
        )
        events = sorted([e2, e1], key=lambda x: x.sort_key())
        assert events[0].event_type == "work.started"
        assert events[1].event_type == "work.completed"

    def test_canonical_error_schema(self) -> None:
        err = CanonicalError(
            category=ErrorCategory.RATE_LIMITED,
            code="openai_429",
            retryability=True,
            ambiguity=False,
            safe_message="Upstream provider rate limited",
        )
        assert err.category == ErrorCategory.RATE_LIMITED
        assert err.retryability is True
        assert err.ambiguity is False

    def test_source_ref_and_project_record(self) -> None:
        source = SourceRef(
            source_owner_id="github_org",
            source_type="git_repo",
            source_id="repo_1",
            version="commit_sha_abc",
            canonical_locator="https://github.com/org/repo.git",
        )
        proj = ProjectRecord(
            project_id=new_project_id(),
            owner_user_id="user_admin",
            title="All Tomorrow",
            status=ProjectStatus.ACTIVE,
            source_refs=(source,),
        )
        assert proj.status == ProjectStatus.ACTIVE
        assert len(proj.source_refs) == 1
        assert proj.source_refs[0].source_id == "repo_1"
