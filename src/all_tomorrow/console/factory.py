"""Idea factory console feature (all_tomorrow.idea_factory): topic → ideas → patent gate → council → proposal.

  GET  /api/factory/state | events | topics/{id} | proposals | killed | staff | audit
  POST /api/factory/control {pause|resume|kill|reset} | topics | proposals/{id}/decision | ideas/{id}/review

Every route needs the console login. The SQLite store lives in ctx.feature_dir("factory")
unless IDEA_FACTORY_STORE is set.

Only with IDEA_FACTORY_ENABLED=1 does this process run workflows. The router then carries a
lifespan that FastAPI's include_router merges *inside* the app's own lifespan (web.py's Postgres
open/migrate in durable mode): DBOS launches after the app's startup, which also recovers this
version's unfinished topics, and is destroyed before the app's shutdown. Without the flag the
routes work against the store only: POST /topics answers 503, and kill marks the store KILLED,
which workflows running in another process (the CLI) honour at their next checkpoint.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext
from all_tomorrow.idea_factory import evaluation
from all_tomorrow.idea_factory.config import Roster, dbos_url, load_roster, store_path
from all_tomorrow.idea_factory.store import Store

log = logging.getLogger(__name__)


@dataclass(slots=True)
class FactoryRuntime:
    """start_topic/kill_all need a launched DBOS; None means read/control-only.
    roster is None only in read-only mode without config/idea-factory.yaml (e.g. the container image)."""
    store: Store
    roster: Roster | None
    start_topic: Callable[[str, str], str] | None = None
    kill_all: Callable[[str], int] | None = None


class ControlRequest(BaseModel):
    action: str = Field(pattern="^(pause|resume|kill|reset)$")


class TopicRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    reason: str = Field(default="", max_length=500)


class ReviewRequest(BaseModel):
    verdict: str = Field(pattern="^(correct|overkill)$")


def routes(runtime: FactoryRuntime, current_user: Callable[..., str], lifespan: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/factory", lifespan=lifespan)
    store = runtime.store

    def apply_policy() -> list[dict[str, Any]]:
        # User judgments drive promotion/retirement; without a roster they are only recorded.
        return evaluation.apply_policy(store, runtime.roster, actor="policy") if runtime.roster else []

    @router.get("/state")
    async def state(_: str = Depends(current_user)) -> dict[str, Any]:
        staff = store.staff(include_retired=False)
        last_by_staff: dict[str, str] = {}
        for event in store.events(limit=300):
            if event["staff_id"] and event["staff_id"] not in last_by_staff:
                last_by_staff[event["staff_id"]] = event["text"]
        proposals = store.proposals()
        return {
            "loop": store.loop_state(),
            "runtime": runtime.start_topic is not None,
            "staff": [{**m, "last": last_by_staff.get(m["id"], "")} for m in staff],
            "topics": store.topics(10),
            "counts": {s: sum(1 for p in proposals if p["status"] == s) for s in ("PENDING", "APPROVED", "REJECTED")},
            "proposed_total": len(proposals),
        }

    @router.get("/events")
    async def events(limit: int = 60, _: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.events(limit=min(limit, 300))

    @router.post("/control")
    async def control(payload: ControlRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        current = store.loop_state()
        if payload.action == "kill":
            if runtime.kill_all:
                # DBOS's sync API refuses to run inside the event loop.
                cancelled = await asyncio.to_thread(runtime.kill_all, user)
            else:
                store.set_loop_state("KILLED", user)
                cancelled = 0
            return {"loop": "KILLED", "cancelled": cancelled}
        if payload.action == "pause":
            if current == "KILLED":
                raise HTTPException(409, "loop is KILLED")
            store.set_loop_state("PAUSED", user)
        elif payload.action == "resume":
            if current == "KILLED":
                raise HTTPException(409, "loop is KILLED; use reset")
            store.set_loop_state("RUN", user)
        elif payload.action == "reset":
            store.set_loop_state("RUN", user)
        return {"loop": store.loop_state()}

    @router.post("/topics")
    async def start(payload: TopicRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        if runtime.start_topic is None:
            raise HTTPException(503, "idea factory runtime is not running in this process")
        try:
            return {"topic_id": await asyncio.to_thread(runtime.start_topic, payload.text, user)}
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/topics/{topic_id}")
    async def topic(topic_id: str, _: str = Depends(current_user)) -> dict[str, Any]:
        found = store.topic(topic_id)
        if not found:
            raise HTTPException(404, "unknown topic")
        ideas = store.ideas(topic_id=topic_id)
        for idea in ideas:
            idea["votes"] = store.votes(idea["id"])
        return {**found, "ideas": ideas}

    @router.get("/proposals")
    async def proposals(status: str | None = None, _: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.proposals(status)

    @router.post("/proposals/{proposal_id}/decision")
    async def decide(proposal_id: str, payload: DecisionRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            store.decide_proposal(proposal_id, payload.decision, payload.reason, user)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        return {"actions": apply_policy()}

    @router.get("/killed")
    async def killed(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.ideas(status="KILLED", limit=100)

    @router.post("/ideas/{idea_id}/review")
    async def review(idea_id: str, payload: ReviewRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            store.review_kill(idea_id, payload.verdict, user)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"actions": apply_policy()}

    @router.get("/staff")
    async def staff(_: str = Depends(current_user)) -> dict[str, Any]:
        roster = runtime.roster
        if roster is None:
            return {"staff": [{**m, "samples": None, "score": None, "verdict": "RETIRED" if m["status"] == "RETIRED" else None}
                              for m in store.staff()], "policy": None}
        active = {row["id"]: row for row in evaluation.evaluate(store, roster)}
        return {"staff": [active.get(m["id"], {**m, "samples": None, "score": None, "verdict": "RETIRED"})
                          for m in store.staff()],
                "policy": {"min_samples": roster.evaluation_min_samples,
                           "promote_above": roster.promote_above, "retire_below": roster.retire_below}}

    @router.get("/audit")
    async def audit(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.audit_log(200)

    return router


def build_router(ctx: ConsoleContext) -> APIRouter:
    base = ctx.feature_dir("factory")
    store = Store(store_path(base))
    if os.environ.get("IDEA_FACTORY_ENABLED") != "1":
        try:
            roster: Roster | None = load_roster()
        except FileNotFoundError as error:
            # The console must not go down over an optional feature's config.
            log.warning("idea factory roster unavailable (%s); staff evaluation is off", error)
            roster = None
        return routes(FactoryRuntime(store=store, roster=roster), ctx.current_user)

    from all_tomorrow.idea_factory import pipeline  # imports DBOS only when this process runs the factory

    roster = load_roster()  # running workflows without the roster is not an option: fail at startup
    system_database_url = dbos_url(base)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Off the event loop: launch runs migrations and recovery, destroy joins DBOS threads.
        await asyncio.to_thread(pipeline.launch, store, system_database_url, roster_obj=roster)
        try:
            yield
        finally:
            await asyncio.to_thread(pipeline.shutdown)

    runtime = FactoryRuntime(store=store, roster=roster, start_topic=pipeline.start_topic, kill_all=pipeline.kill_all)
    return routes(runtime, ctx.current_user, lifespan=lifespan)
