"""Eve 해금 사용자 DM: 소유자가 유료 DM을 해금한 사용자와 이브가 나눈 대화를 사람별로 본다.

  POST /internal/edge/eve/unlocked-dm   Eve 봇이 보낸다(엣지 토큰, Authorization: Bearer). 형식은 UnlockedDmBatch.
  GET  /api/eve-dm                      사람 목록(해금·회수 상태, 대화 수, 마지막 대화)
  GET  /api/eve-dm/{user_id}            그 사람의 대화, 오래된 것부터

기존 디스코드 입구(/internal/edge/discord/messages)는 받은 것을 관제의 디스코드 요약으로 넘긴다. 해금 DM은
거기 섞이지 않게 따로 받아 data_dir/eve-dm/dm.sqlite에만 둔다. 저장 전에 토큰·키·비밀번호로 보이는 값은
overseer.redact의 가림 규칙으로 가린다. 기록은 지우지 않는다. 회수된 사용자는 '회수됨'으로 표시만 한다.
같은 message_id는 한 번만 저장한다(재전송해도 안전).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from all_tomorrow.console import ConsoleContext

Snowflake = Annotated[str, Field(pattern=r"^[0-9]{1,32}$")]


class DmTurn(BaseModel):
    message_id: Snowflake
    user_id: Snowflake                  # 해금 사용자(대화 상대). 이브의 답도 그 사용자의 대화로 묶는다.
    user_name: str = Field(default="", max_length=200)
    role: Literal["user", "eve"]
    created_at: AwareDatetime
    content: str = Field(max_length=20_000)


class DmAccess(BaseModel):
    user_id: Snowflake
    user_name: str = Field(default="", max_length=200)
    state: Literal["unlocked", "revoked"]
    at: AwareDatetime


class UnlockedDmBatch(BaseModel):
    source: Literal["eve"]
    batch_id: str = Field(min_length=1, max_length=256)
    turns: list[DmTurn] = Field(default_factory=list, max_length=500)
    access: list[DmAccess] = Field(default_factory=list, max_length=500)


class DmStore:
    def __init__(self, base: Path) -> None:
        self.path = base / "dm.sqlite"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS turns (message_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL, received_at TEXT NOT NULL, batch_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_user ON turns (user_id, created_at);
                CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, user_name TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'unlocked', state_at TEXT NOT NULL DEFAULT '');
            """)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def receive(self, batch: UnlockedDmBatch, redact) -> dict[str, int]:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        added = 0
        with self.db() as db:
            for t in batch.turns:
                db.execute("INSERT OR IGNORE INTO users (user_id, user_name, state, state_at) VALUES (?,?,?,?)",
                           (t.user_id, t.user_name, "unlocked", ""))
                if t.user_name:
                    db.execute("UPDATE users SET user_name = ? WHERE user_id = ?", (t.user_name, t.user_id))
                added += db.execute(
                    "INSERT OR IGNORE INTO turns (message_id, user_id, role, content, created_at, received_at, batch_id)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (t.message_id, t.user_id, t.role, redact(t.content), t.created_at.astimezone(UTC).isoformat(),
                     stamp, batch.batch_id)).rowcount
            for a in sorted(batch.access, key=lambda a: a.at):
                at = a.at.astimezone(UTC).isoformat()
                db.execute("INSERT OR IGNORE INTO users (user_id, user_name, state, state_at) VALUES (?,?,?,?)",
                           (a.user_id, a.user_name, a.state, at))
                # 늦게 도착한 옛 상태가 새 상태를 덮지 않게 시각을 비교한다.
                db.execute("UPDATE users SET state = ?, state_at = ?, user_name = CASE WHEN ? != '' THEN ? ELSE user_name END"
                           " WHERE user_id = ? AND state_at <= ?", (a.state, at, a.user_name, a.user_name, a.user_id, at))
        return {"added": added, "duplicates": len(batch.turns) - added, "access": len(batch.access)}

    def people(self) -> list[dict[str, Any]]:
        with self.db() as db:
            rows = db.execute("""
                SELECT u.user_id, u.user_name, u.state, u.state_at, COUNT(t.message_id) AS turns,
                       MAX(t.created_at) AS last_at,
                       (SELECT content FROM turns x WHERE x.user_id = u.user_id ORDER BY created_at DESC, message_id DESC LIMIT 1) AS last_text
                FROM users u LEFT JOIN turns t ON t.user_id = u.user_id GROUP BY u.user_id
                ORDER BY COALESCE(MAX(t.created_at), u.state_at) DESC""").fetchall()
        return [dict(r) for r in rows]

    def conversation(self, user_id: str) -> dict[str, Any] | None:
        with self.db() as db:
            user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user is None:
                return None
            turns = db.execute("SELECT message_id, role, content, created_at FROM turns WHERE user_id = ?"
                               " ORDER BY created_at, CAST(message_id AS INTEGER)", (user_id,)).fetchall()
        return {**dict(user), "turns": [dict(t) for t in turns]}


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = DmStore(ctx.feature_dir("eve-dm"))
    router = APIRouter()

    @router.post("/internal/edge/eve/unlocked-dm")
    async def receive(request: Request) -> dict[str, int]:
        if ctx.verify_edge is None:
            raise HTTPException(503, "edge authentication not configured")
        ctx.verify_edge(request.headers.get("authorization"))
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2 * 1024 * 1024:
                raise HTTPException(413, "본문 최대 2MB")
            body.extend(chunk)
        try:
            batch = UnlockedDmBatch.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "해금 DM 배치 형식 오류") from None
        from all_tomorrow.overseer.redact import Redactor, default_secret_files
        return store.receive(batch, Redactor.from_files(default_secret_files(Path.home())))

    @router.get("/api/eve-dm")
    async def people(_: str = Depends(ctx.current_user)) -> list[dict[str, Any]]:
        return store.people()

    @router.get("/api/eve-dm/{user_id}")
    async def conversation(user_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        found = store.conversation(user_id)
        if found is None:
            raise HTTPException(404, "no such user")
        return found

    return router
