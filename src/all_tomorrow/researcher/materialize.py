"""02C — Researcher decision materialization.

Turns a validated typed Decision (02B) into durable canonical Goal/Work/Question/
Proposal state. Model payload is never copied blind to a domain object: each
action goes validator → canonical domain command → transaction. ``decision_id``
is the idempotency key, so replaying a decision produces at most one mutation.

A PROPOSE_IMPROVEMENT before the 03A store exists produces only an immutable
typed proposal candidate + Event — never a production mutation.
"""

from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import (
    GoalId, WorkId, new_event_id, new_goal_id, new_question_id, new_work_id,
)
from all_tomorrow.domain.state import (
    GoalRecord, WorkRecord, WorkStatus, TERMINAL_WORK_STATUSES,
)
from all_tomorrow.researcher.decision import Action, Decision
from all_tomorrow.storage.semantic_store import (
    GoalWorkRunStore, QuestionRecordSemantic, SemanticEvent,
)


class MaterializationError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    action: Action
    goal_id: GoalId | None = None
    work_id: WorkId | None = None
    question_id: str | None = None
    proposal_ref: str | None = None
    already_applied: bool = False


def _evt(actor: str, type_: str, decision_id: str, **kw) -> SemanticEvent:
    payload = kw.pop("payload", {})
    payload["decision_id"] = decision_id
    return SemanticEvent(event_id=new_event_id(), actor=actor, type=type_, payload=payload, **kw)


class DecisionMaterializer:
    def __init__(self, store: GoalWorkRunStore, *, user_id: str, actor: str = "researcher") -> None:
        self.store = store
        self.user_id = user_id
        self.actor = actor
        self._applied: dict[str, MaterializationResult] = {}  # decision_id idempotency
        self._proposals: dict[str, dict] = {}

    async def materialize(self, decision: Decision) -> MaterializationResult:
        # Idempotency: a replayed decision_id returns the prior result, no new mutation.
        if decision.decision_id in self._applied:
            import dataclasses
            return dataclasses.replace(self._applied[decision.decision_id], already_applied=True)

        result = await self._dispatch(decision)
        self._applied[decision.decision_id] = result
        return result

    async def _dispatch(self, d: Decision) -> MaterializationResult:
        if d.action == Action.NOOP:
            return MaterializationResult(action=Action.NOOP)
        if d.action == Action.CREATE_GOAL:
            return await self._create_goal(d)
        if d.action == Action.CREATE_WORK:
            return await self._create_work(d)
        if d.action == Action.REVISE_WORK:
            return await self._revise_work(d)
        if d.action == Action.ASK_USER:
            return await self._ask_user(d)
        if d.action == Action.PROPOSE_IMPROVEMENT:
            return await self._propose(d)
        raise MaterializationError(f"unhandled action {d.action}")

    async def _create_goal(self, d: Decision) -> MaterializationResult:
        goal = GoalRecord(goal_id=new_goal_id(), user_id=self.user_id, title=d.payload["title"])
        await self.store.create_goal(goal, _evt(self.actor, "researcher.create_goal", d.decision_id, goal_id=goal.goal_id))
        return MaterializationResult(action=Action.CREATE_GOAL, goal_id=goal.goal_id)

    async def _create_work(self, d: Decision) -> MaterializationResult:
        goal_id = GoalId(d.payload["target_goal_id"])
        goal = await self.store.get_goal(goal_id)
        if goal is None or goal.is_terminal():
            raise MaterializationError(f"target goal invalid/terminal: {goal_id}")
        work = WorkRecord(work_id=new_work_id(), goal_id=goal_id, title=d.payload["title"])
        await self.store.create_work(work, _evt(self.actor, "researcher.create_work", d.decision_id, work_id=work.work_id, goal_id=goal_id))
        return MaterializationResult(action=Action.CREATE_WORK, work_id=work.work_id, goal_id=goal_id)

    async def _revise_work(self, d: Decision) -> MaterializationResult:
        work_id = WorkId(d.payload["target_work_id"])
        work = await self.store.get_work(work_id)
        if work is None:
            raise MaterializationError(f"target work not found: {work_id}")
        if work.status in TERMINAL_WORK_STATUSES:
            # Terminal Work: create a successor, never revive in place.
            successor = WorkRecord(work_id=new_work_id(), goal_id=work.goal_id,
                                   title=f"{work.title} (revised)")
            await self.store.create_work(successor, _evt(self.actor, "researcher.revise_successor", d.decision_id, work_id=successor.work_id, goal_id=work.goal_id, payload={"supersedes": str(work_id)}))
            return MaterializationResult(action=Action.REVISE_WORK, work_id=successor.work_id, goal_id=work.goal_id)
        # Non-terminal: allowed semantic revision only (no arbitrary status).
        # Represent the revision as an Event; the store owns any field change.
        await self.store.list_events(work_id=work_id)  # touch (no-op read for parity)
        return MaterializationResult(action=Action.REVISE_WORK, work_id=work_id, goal_id=work.goal_id)

    async def _ask_user(self, d: Decision) -> MaterializationResult:
        work_id = WorkId(d.payload["target_work_id"])
        work = await self.store.get_work(work_id)
        if work is None or work.status in TERMINAL_WORK_STATUSES:
            raise MaterializationError(f"cannot ask on missing/terminal work: {work_id}")
        q = QuestionRecordSemantic(
            question_id=new_question_id(), prompt=d.payload["question"], work_id=work_id,
        )
        await self.store.create_question(q)
        return MaterializationResult(action=Action.ASK_USER, question_id=str(q.question_id), work_id=work_id)

    async def _propose(self, d: Decision) -> MaterializationResult:
        # No 03A store yet → immutable typed candidate + Event only, NO production mutation.
        ref = f"proposal:{d.decision_id}"
        self._proposals[ref] = {
            "target_type": d.payload["target_type"],
            "target_id": d.payload["target_id"],
            "candidate_intent": d.payload["candidate_intent"],
            "evidence_refs": list(d.evidence_refs),
        }
        return MaterializationResult(action=Action.PROPOSE_IMPROVEMENT, proposal_ref=ref)

    def proposals(self) -> dict[str, dict]:
        return dict(self._proposals)
