"""Web control surface (2.1B + 2.2B wiring).

Connects the web server to the canonical Goal/Work/Run store: a web request
becomes a Goal + its first Work (deduplicated by the client idempotency key),
and every read or mutation is scoped to the requesting user.
"""

from __future__ import annotations

import asyncio
from typing import Any

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import GoalId, QuestionId, new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, WorkRecord
from all_tomorrow.execution_service import ExecutionService
from all_tomorrow.ingress_adapters import web_api_ingress
from all_tomorrow.requests import RequestStore
from all_tomorrow.storage.semantic_store import GoalWorkRunStore, SemanticEvent

MAX_TEXT = 4000


class NotFound(DomainError):
    """Missing object, or one owned by another user (indistinguishable on purpose)."""


def _evt(actor: str, type_: str, **kw: Any) -> SemanticEvent:
    return SemanticEvent(event_id=new_event_id(), actor=actor, type=type_, **kw)


def _ts(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class WebControl:
    def __init__(self, store: GoalWorkRunStore, requests: RequestStore | None = None) -> None:
        self.store = store
        self.requests = requests or RequestStore()
        self._goal_for_request: dict[str, GoalId] = {}
        self._lock = asyncio.Lock()

    async def submit(self, user: str, text: str, idempotency_key: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("요청 내용이 비어 있습니다")
        text = text[:MAX_TEXT]
        async with self._lock:
            result = await web_api_ingress(
                self.requests, user_id=user, text=text, client_idempotency_key=idempotency_key
            )
            request_id = result.request.request_id
            goal_id = self._goal_for_request.get(request_id)
            if goal_id is None:
                goal = GoalRecord(goal_id=new_goal_id(), user_id=user, title=text)
                await self.store.create_goal(goal, _evt(user, "goal.created", goal_id=goal.goal_id,
                                                        external_ref=request_id))
                work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title=text)
                await self.store.create_work(work, _evt(user, "work.created", goal_id=goal.goal_id,
                                                        work_id=work.work_id))
                goal_id = goal.goal_id
                self._goal_for_request[request_id] = goal_id
        return {"goal_id": str(goal_id), "is_new": result.is_new}

    async def _owned_goal(self, user: str, goal_id: str) -> GoalRecord:
        goal = await self.store.get_goal(GoalId(goal_id))
        if goal is None or goal.user_id != user:
            raise NotFound(goal_id)
        return goal

    async def overview(self, user: str) -> dict[str, Any]:
        goals_out: list[dict[str, Any]] = []
        questions_out: list[dict[str, Any]] = []
        goals = sorted(await self.store.list_goals(user_id=user), key=lambda g: g.created_at, reverse=True)
        for goal in goals:
            works_out = []
            for work in await self.store.list_work(goal.goal_id):
                runs = await self.store.list_runs(work.work_id)
                for q in await self.store.list_questions(work.work_id):
                    if q.status == "PENDING":
                        questions_out.append({"question_id": str(q.question_id), "prompt": q.prompt,
                                              "goal_title": goal.title, "created_at": _ts(q.created_at)})
                works_out.append({
                    "work_id": str(work.work_id), "title": work.title, "status": str(work.status),
                    "runs": [{"run_id": str(r.run_id), "status": str(r.status),
                              "attempt": r.attempt_number} for r in runs],
                })
            goals_out.append({
                "goal_id": str(goal.goal_id), "title": goal.title, "status": str(goal.status),
                "revision": goal.revision, "terminal": goal.is_terminal(),
                "created_at": _ts(goal.created_at), "works": works_out,
            })
        return {"goals": goals_out, "questions": questions_out}

    async def cancel(self, user: str, goal_id: str) -> dict[str, Any]:
        goal = await self._owned_goal(user, goal_id)
        if goal.is_terminal() or str(goal.status) == "CANCEL_REQUESTED":
            return {"goal_id": goal_id, "status": str(goal.status)}
        return await ExecutionService(self.store, actor=user).cancel_goal(goal.goal_id, goal.revision)

    async def answer(self, user: str, question_id: str, answer: str) -> dict[str, Any]:
        answer = answer.strip()[:MAX_TEXT]
        if not answer:
            raise ValueError("답변이 비어 있습니다")
        q = await self.store.get_question(QuestionId(question_id))
        if q is None or q.work_id is None:
            raise NotFound(question_id)
        work = await self.store.get_work(q.work_id)
        if work is None:
            raise NotFound(question_id)
        await self._owned_goal(user, str(work.goal_id))
        updated = await self.store.answer_question(
            q.question_id, q.revision, answer, f"web:{new_event_id()}"
        )
        return {"question_id": question_id, "status": updated.status}
