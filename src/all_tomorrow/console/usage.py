"""Subscription usage panel: the PC collector (all_tomorrow.usage) pushes, the console shows it.

  GET  /api/usage       latest snapshot for the logged-in user (null until the first push)
  POST /internal/usage  collector push, bearer collector token, validated and size-bounded
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext

log = logging.getLogger(__name__)


class UsageWindow(BaseModel):
    label: str = Field(max_length=64)
    percent: float = Field(ge=0, le=1000)
    resets_at: str | None = Field(default=None, max_length=64)


class UsageProvider(BaseModel):
    id: str = Field(max_length=32)
    name: str = Field(max_length=64)
    plan: str | None = Field(default=None, max_length=64)
    status: str = Field(max_length=32)
    observed_at: str | None = Field(default=None, max_length=64)
    windows: list[UsageWindow] = Field(default_factory=list, max_length=10)


class UsageSnapshot(BaseModel):
    collected_at: str = Field(max_length=64)
    providers: list[UsageProvider] = Field(max_length=10)


class UsageStore:
    """Latest snapshot in memory, mirrored to one JSON file so a restart keeps it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.snapshot: dict[str, Any] | None = None
        if path.exists():
            try:
                self.snapshot = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("ignoring unreadable usage snapshot at %s", path)

    def store(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = UsageStore(ctx.feature_dir("usage") / "usage.json")
    router = APIRouter()

    def collector(authorization: str | None = Header(default=None)) -> None:
        # A dependency, so a bad token is refused before the body is even validated.
        ctx.verify_collector(authorization)

    @router.get("/api/usage")
    async def usage(_: str = Depends(ctx.current_user)) -> dict[str, Any] | None:
        return store.snapshot

    @router.post("/internal/usage", status_code=204)
    async def ingest_usage(payload: UsageSnapshot, _: None = Depends(collector)) -> None:
        store.store(payload.model_dump())

    return router
