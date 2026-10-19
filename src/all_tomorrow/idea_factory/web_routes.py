"""Console API for the idea factory (mounted by all_tomorrow.web)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.idea_factory import evaluation
from all_tomorrow.idea_factory.config import Roster
from all_tomorrow.idea_factory.store import Store


@dataclass(slots=True)
class FactoryRuntime:
    """start_topic/kill_all need a launched DBOS; None means read/control-only."""
    store: Store
    roster: Roster
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


def build_router(runtime: FactoryRuntime, current_user: Callable[..., str]) -> APIRouter:
    router = APIRouter(prefix="/api/factory")
    store = runtime.store

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
        return {"actions": evaluation.apply_policy(store, runtime.roster, actor="policy")}

    @router.get("/killed")
    async def killed(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.ideas(status="KILLED", limit=100)

    @router.post("/ideas/{idea_id}/review")
    async def review(idea_id: str, payload: ReviewRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            store.review_kill(idea_id, payload.verdict, user)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"actions": evaluation.apply_policy(store, runtime.roster, actor="policy")}

    @router.get("/staff")
    async def staff(_: str = Depends(current_user)) -> dict[str, Any]:
        active = {row["id"]: row for row in evaluation.evaluate(store, runtime.roster)}
        return {"staff": [active.get(m["id"], {**m, "samples": None, "score": None, "verdict": "RETIRED"})
                          for m in store.staff()],
                "policy": {"min_samples": runtime.roster.evaluation_min_samples,
                           "promote_above": runtime.roster.promote_above, "retire_below": runtime.roster.retire_below}}

    @router.get("/audit")
    async def audit(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return store.audit_log(200)

    return router
