"""Web control surface (2.1B + 2.2B wiring).

Connects the web server to the canonical Goal/Work/Run store: a web request
becomes a Goal + its first Work (deduplicated by the client idempotency key),
and every read or mutation is scoped to the requesting user.
"""

from __future__ import annotations

import asyncio
from typing import Any

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import GoalId, QuestionId, WorkId, new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, WorkRecord, WorkStatus
from all_tomorrow.execution_service import ExecutionService
from all_tomorrow.ingress_adapters import discord_ingress, web_api_ingress
from all_tomorrow.report.store import Report, ReportStore
from all_tomorrow.repair import RepairError, RepairItem, RepairService, RepairStatus
from all_tomorrow.requests import RequestStore
from all_tomorrow.storage.artifact_store import ArtifactAccessDeniedError, ArtifactStoreProtocol
from all_tomorrow.storage.semantic_store import GoalWorkRunStore, SemanticEvent

MAX_TEXT = 4000


class NotFound(DomainError):
    """Missing object, or one owned by another user (indistinguishable on purpose)."""


def _evt(actor: str, type_: str, **kw: Any) -> SemanticEvent:
    return SemanticEvent(event_id=new_event_id(), actor=actor, type=type_, **kw)


def _ts(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class WebControl:
    def __init__(
        self,
        store: GoalWorkRunStore,
        requests: RequestStore | None = None,
        *,
        artifact_store: ArtifactStoreProtocol | None = None,
        report_store: ReportStore | None = None,
        repair_service: RepairService | None = None,
    ) -> None:
        self.store = store
        self.requests = requests or RequestStore()
        self.artifact_store = artifact_store
        self.report_store = report_store or ReportStore()
        self.repair_service = repair_service or RepairService()
        self._goal_for_request: dict[str, GoalId] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self, user: str, text: str, idempotency_key: str, *, attachment_refs: tuple[str, ...] = (),
    ) -> dict[str, Any]:
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
                await self.store.create_work(
                    work, _evt(user, "work.created", goal_id=goal.goal_id, work_id=work.work_id,
                               artifact_refs=attachment_refs,
                               payload={"attachment_refs": list(attachment_refs)}),
                )
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
            created_events = await self.store.list_events(goal_id=goal.goal_id)
            transport = "web"
            for e in created_events:
                if e.type == "goal.created":
                    transport = e.payload.get("transport", "web")
                    break
            goals_out.append({
                "goal_id": str(goal.goal_id), "title": goal.title, "status": str(goal.status),
                "revision": goal.revision, "terminal": goal.is_terminal(),
                "created_at": _ts(goal.created_at), "works": works_out, "transport": transport,
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

    # -- Feature 4: Goal detail (Work list, Run history, event/state timeline) --
    async def goal_detail(self, user: str, goal_id: str) -> dict[str, Any]:
        goal = await self._owned_goal(user, goal_id)
        works_out: list[dict[str, Any]] = []
        for work in await self.store.list_work(goal.goal_id):
            runs = await self.store.list_runs(work.work_id)
            outcome = await self.store.get_outcome(work.work_id)
            events = await self.store.list_events(work_id=work.work_id)
            works_out.append({
                "work_id": str(work.work_id), "title": work.title, "status": str(work.status),
                "revision": work.revision, "created_at": _ts(work.created_at),
                "runs": [
                    {"run_id": str(r.run_id), "status": str(r.status),
                     "attempt": r.attempt_number, "created_at": _ts(r.created_at)}
                    for r in sorted(runs, key=lambda r: r.created_at)
                ],
                "artifact_refs": list(outcome.evidence.artifact_refs) if outcome and outcome.evidence else [],
                "events": [
                    {"type": e.type, "actor": e.actor, "occurred_at": _ts(e.occurred_at)}
                    for e in sorted(events, key=lambda e: e.occurred_at)
                ],
            })
        goal_events = await self.store.list_events(goal_id=goal.goal_id)
        return {
            "goal_id": str(goal.goal_id), "title": goal.title, "status": str(goal.status),
            "revision": goal.revision, "created_at": _ts(goal.created_at), "works": works_out,
            "events": [
                {"type": e.type, "actor": e.actor, "occurred_at": _ts(e.occurred_at)}
                for e in sorted(goal_events, key=lambda e: e.occurred_at)
            ],
        }

    # -- Feature 3: artifact listing/viewing (own Work's outputs only) ----------
    async def list_work_artifacts(self, user: str, work_id: str) -> list[dict[str, Any]]:
        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise NotFound(work_id)
        await self._owned_goal(user, str(work.goal_id))
        outcome = await self.store.get_outcome(work.work_id)
        if outcome is None or outcome.evidence is None:
            return []
        return [{"artifact_id": ref} for ref in outcome.evidence.artifact_refs]

    async def get_artifact_content(self, user: str, work_id: str, artifact_ref: str) -> str:
        """``artifact_ref`` here is the content_hash the executor recorded in
        CompletionEvidence.artifact_refs (see executor._succeed)."""
        if self.artifact_store is None:
            raise NotFound(artifact_ref)
        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise NotFound(work_id)
        await self._owned_goal(user, str(work.goal_id))
        outcome = await self.store.get_outcome(work.work_id)
        refs = outcome.evidence.artifact_refs if outcome and outcome.evidence else ()
        if artifact_ref not in refs:
            raise NotFound(artifact_ref)
        resolver = getattr(self.artifact_store, "retrieve_by_content_hash", None)
        if resolver is None:
            raise NotFound(artifact_ref)
        try:
            content = await resolver(artifact_ref)
        except FileNotFoundError as error:
            raise NotFound(artifact_ref) from error
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("utf-8", errors="replace")

    # -- Feature 5: reports -----------------------------------------------------
    def list_reports(self, user: str) -> list[dict[str, Any]]:
        reports = [r for r in self.report_store._by_id.values() if r.user_id == user]
        reports.sort(key=lambda r: r.period_start_utc, reverse=True)
        return [
            {"report_id": r.report_id, "logical_period_id": r.logical_period_id,
             "status": str(r.status), "summary": r.summary, "created_at": _ts(r.created_at)}
            for r in reports
        ]

    def get_report(self, user: str, report_id: str) -> dict[str, Any]:
        report = self.report_store.get(report_id)
        if report is None or report.user_id != user:
            raise NotFound(report_id)
        return {
            "report_id": report.report_id, "logical_period_id": report.logical_period_id,
            "status": str(report.status), "summary": report.summary,
            "created_at": _ts(report.created_at),
            "sections": [
                {"title": s.title, "source_refs": list(s.source_refs), "unknown": s.unknown}
                for s in report.sections
            ],
        }

    # -- Feature 6: broken/stuck Work -- list, retry, clean up (via RepairService) --
    async def list_broken_work(self, user: str) -> list[dict[str, Any]]:
        """FAILED Work owned by ``user``. A STUCK Work is one RUNNING/WAITING with
        no active Run left (its Run already terminalized without the Work
        following) -- surfaced the same way so an operator can act on either."""
        out: list[dict[str, Any]] = []
        for goal in await self.store.list_goals(user_id=user):
            for work in await self.store.list_work(goal.goal_id):
                is_stuck = False
                if work.status in (WorkStatus.RUNNING, WorkStatus.WAITING):
                    runs = await self.store.list_runs(work.work_id)
                    is_stuck = bool(runs) and not any(r.is_active() for r in runs)
                if work.status == WorkStatus.FAILED or is_stuck:
                    out.append({
                        "work_id": str(work.work_id), "goal_id": str(goal.goal_id),
                        "title": work.title, "status": str(work.status), "stuck": is_stuck,
                    })
        return out

    async def retry_broken_work(self, user: str, work_id: str, *, operator: str) -> dict[str, Any]:
        """Retry = a fresh Work under the same Goal (FAILED/terminal Work is never
        revived in place -- TerminalReviveError -- so a new attempt is a new Work),
        recorded through RepairService for the audit trail."""
        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise NotFound(work_id)
        await self._owned_goal(user, str(work.goal_id))
        repair_id = f"repair:{work_id}"
        item = self.repair_service._items.get(repair_id)
        if item is None:
            item = self.repair_service.record_repair_required(RepairItem(
                repair_id=repair_id, subject_ref=f"work:{work_id}", reason="failed or stuck",
                safe_to_retry=True, provenance_refs=(f"work:{work_id}",),
            ))
        self.repair_service.authorize(operator)
        self.repair_service.retry(repair_id, operator)
        new_work = WorkRecord(work_id=new_work_id(), goal_id=work.goal_id, title=work.title)
        await self.store.create_work(
            new_work, _evt(operator, "work.retried", goal_id=work.goal_id, work_id=new_work.work_id,
                            payload={"retried_from": work_id}),
        )
        return {"original_work_id": work_id, "new_work_id": str(new_work.work_id)}

    # -- Feature 8: Discord CENTRAL_TASK requests -> same Goal/Work store, ---------
    #    visible in the web list as transport=discord. Dedup key = discord message id.
    async def submit_from_discord(self, user: str, text: str, message_id: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("요청 내용이 비어 있습니다")
        text = text[:MAX_TEXT]
        async with self._lock:
            result = await discord_ingress(
                self.requests, user_id=user, text=text, message_id=message_id,
            )
            request_id = result.request.request_id
            goal_id = self._goal_for_request.get(request_id)
            if goal_id is None:
                goal = GoalRecord(goal_id=new_goal_id(), user_id=user, title=text)
                await self.store.create_goal(
                    goal, _evt(user, "goal.created", goal_id=goal.goal_id, external_ref=request_id,
                               payload={"transport": "discord", "discord_message_id": message_id}),
                )
                work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title=text)
                await self.store.create_work(
                    work, _evt(user, "work.created", goal_id=goal.goal_id, work_id=work.work_id,
                               payload={"transport": "discord"}),
                )
                goal_id = goal.goal_id
                self._goal_for_request[request_id] = goal_id
        return {"goal_id": str(goal_id), "is_new": result.is_new, "transport": "discord"}

    async def clean_up_broken_work(self, user: str, work_id: str, *, operator: str) -> dict[str, Any]:
        """Abandon a broken Work -- recorded through RepairService, never a blind
        automatic retry for a non-retryable item."""
        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise NotFound(work_id)
        await self._owned_goal(user, str(work.goal_id))
        repair_id = f"repair:{work_id}"
        if repair_id not in self.repair_service._items:
            self.repair_service.record_repair_required(RepairItem(
                repair_id=repair_id, subject_ref=f"work:{work_id}", reason="failed or stuck",
                safe_to_retry=False, provenance_refs=(f"work:{work_id}",),
            ))
        self.repair_service.authorize(operator)
        self.repair_service.abandon(repair_id, operator)
        if work.status in (WorkStatus.RUNNING, WorkStatus.WAITING, WorkStatus.PENDING):
            try:
                await self.store.transition_work_status(
                    work.work_id, WorkStatus.CANCELLED, work.revision,
                    _evt(operator, "work.cleaned_up", work_id=work.work_id),
                )
            except DomainError:
                pass  # already terminal (e.g. FAILED); nothing left to transition
        return {"work_id": work_id, "status": "ABANDONED"}
