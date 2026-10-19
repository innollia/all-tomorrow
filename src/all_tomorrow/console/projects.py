"""Projects snapshot: the PC collector (all_tomorrow.projects_snapshot) pushes, the console shows it.

  GET  /api/project-snapshot  latest snapshot for the logged-in user, ETag + 304 (null until a push)
  POST /internal/projects     collector push, bearer collector token, capped at 1 MB

The body is encoded once per push, so repeated reads cost no JSON work on the small server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from all_tomorrow.console import ConsoleContext

log = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = 1_000_000


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.body: bytes | None = None
        self.etag: str | None = None
        if path.exists():
            try:
                self._encode(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                log.warning("ignoring unreadable projects snapshot at %s", path)

    def _encode(self, snapshot: dict[str, Any]) -> None:
        self.body = json.dumps(snapshot, ensure_ascii=False).encode()
        self.etag = '"' + hashlib.sha256(self.body).hexdigest()[:16] + '"'

    def store(self, snapshot: dict[str, Any]) -> None:
        # Collected on the user's PC; the server only keeps the latest copy.
        self._encode(snapshot)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self.body or b"")
        os.replace(tmp, self.path)


async def _read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="snapshot too large")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="snapshot too large")
        chunks.append(chunk)
    return b"".join(chunks)


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = SnapshotStore(ctx.feature_dir("projects") / "projects-snapshot.json")
    router = APIRouter()

    @router.get("/api/project-snapshot")
    async def project_snapshot(request: Request, _: str = Depends(ctx.current_user)) -> Response:
        if store.body is None:
            return Response("null", media_type="application/json")
        headers = {"ETag": store.etag or "", "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == store.etag:
            return Response(status_code=304, headers=headers)
        return Response(store.body, media_type="application/json", headers=headers)

    @router.post("/internal/projects", status_code=204)
    async def ingest_projects(request: Request, authorization: str | None = Header(default=None)) -> None:
        # Same collector credential as usage, checked before the body is read.
        ctx.verify_collector(authorization)
        body = await _read_capped(request, MAX_SNAPSHOT_BYTES)
        try:
            snapshot = json.loads(body)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="snapshot is not valid JSON") from error
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("projects"), list):
            raise HTTPException(status_code=422, detail="snapshot must have a projects list")
        store.store(snapshot)

    return router
