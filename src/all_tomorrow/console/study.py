"""게임기획 공부 달력·커리큘럼: gamedesign-study의 계획과 진도를 읽어 보여 준다. 고치지 않는다.

  GET /api/study    plan.json의 날마다에 progress.json의 두 사람 진도를 붙여서 준다
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from all_tomorrow.console import ConsoleContext

LEARNERS = ("innollia", "pai")


def study_repo() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_STUDY_REPO", r"C:\projects\gamedesign-study"))


def merged(repo: Path) -> dict[str, Any]:
    try:
        plan = json.loads((repo / "data/plan.json").read_text(encoding="utf-8"))
        progress = json.loads((repo / "data/progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HTTPException(503, f"공부 계획을 읽지 못했다: {type(error).__name__}") from error
    entries = progress.get("days", {})

    def learner(day: dict[str, Any], name: str) -> dict[str, Any]:
        entry = entries.get(day["id"], {}).get(name) or {}
        return {"status": entry.get("status") or "todo", "date": entry.get("date"),
                "actual_min": entry.get("actual_min"), "note": entry.get("note") or ""}
    return {"days": [{**day, "progress": {name: learner(day, name) for name in LEARNERS}} for day in plan.get("days", [])]}


def build_router(ctx: ConsoleContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/study")
    def study(_user: str = Depends(ctx.current_user)) -> dict[str, Any]:
        return merged(study_repo())

    return router
