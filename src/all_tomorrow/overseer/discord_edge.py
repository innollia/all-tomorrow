"""Eve의 보고 수신과 답장 연결. 기존 edge 토큰만 사용한다."""
import asyncio
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from all_tomorrow.domain.ids import new_event_id
from all_tomorrow.storage.semantic_store import SemanticEvent
from all_tomorrow.overseer import reports
from all_tomorrow.overseer.store import default_dir


class Delivery(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    part: int = Field(ge=0)
    message_id: str = Field(pattern=r"^[0-9]{1,32}$")


class Reply(BaseModel):
    discord_user_id: str
    discord_message_id: str = Field(pattern=r"^[0-9]{1,32}$")
    reply_to_message_id: str = Field(pattern=r"^[0-9]{1,32}$")
    text: str = Field(min_length=1, max_length=4000)


Snowflake = Annotated[str, Field(pattern=r"^[0-9]{1,32}$")]


class DiscordMessage(BaseModel):
    message_id: Snowflake
    guild_id: Snowflake
    guild_name: str
    channel_id: Snowflake
    channel_name: str
    thread_id: Snowflake | None = None
    author_id: Snowflake
    author_name: str
    author_is_bot: bool = Field(strict=True)
    created_at: AwareDatetime
    content: str
    reply_to: Snowflake | None = None


class MessageBatch(BaseModel):
    source: Literal["eve"]
    batch_id: str = Field(min_length=1, max_length=256)
    messages: list[DiscordMessage] = Field(max_length=500)


def include_discord_edge(app, auth, store):
    lock = asyncio.Lock()

    @app.post("/internal/edge/discord/messages")
    async def messages(request: Request):
        auth.verify_edge_token(request.headers.get("authorization"))
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2 * 1024 * 1024:
                raise HTTPException(413, "본문 최대 2MB")
            body.extend(chunk)
        try:
            batch = MessageBatch.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "디스코드 메시지 배치 형식 오류") from None
        from all_tomorrow.overseer.discord_digest import receive
        from all_tomorrow.overseer.redact import Redactor, default_secret_files
        redact = Redactor.from_files(default_secret_files(Path.home()))
        return await asyncio.to_thread(receive, default_dir(), batch, redact)

    def check(request):
        auth.verify_edge_token(request.headers.get("authorization"))
        owner = os.environ.get("DISCORD_OWNER_USER_ID")
        if not owner:
            raise HTTPException(503, "DISCORD_OWNER_USER_ID 설정 필요")
        return owner

    @app.get("/internal/edge/discord/reports")
    async def pending(request: Request):
        owner = check(request)
        async with lock:
            await reports.sync_events(store, default_dir())
            return {"owner_user_id": owner, "reports": reports.pending(default_dir())}

    @app.post("/internal/edge/discord/reports/ack")
    async def ack(payload: Delivery, request: Request):
        check(request)
        async with lock:
            if not reports.acknowledge(default_dir(), payload.event_id, payload.part, payload.message_id):
                raise HTTPException(409, "보고 또는 전송 순서 불일치")
        return {"ok": True}

    @app.post("/internal/edge/discord/reply")
    async def reply(payload: Reply, request: Request):
        owner = check(request)
        if payload.discord_user_id != owner:
            raise HTTPException(403, "owner only")
        async with lock:
            parent = reports.event_for_message(default_dir(), payload.reply_to_message_id)
            if not parent:
                return {"linked": False}
            async with store.autonomous_batch() as tx:
                events = await tx.list_events()
                original = next((e for e in events if str(e.event_id) == parent), None)
                if original is None:
                    if not reports.record_reply(default_dir(), payload.reply_to_message_id, payload.model_dump()):
                        return {"linked": False}
                    return {"linked": True, "event_id": parent, "approval_granted": False,
                            "message": "답변을 보고에 기록했습니다. 다음 메타인지에 전달합니다."}
                duplicate = any(e.type == "discord.question_reply" and
                                e.payload.get("discord_message_id") == payload.discord_message_id for e in events)
                if not duplicate:
                    await tx.append_event(SemanticEvent(
                        event_id=new_event_id(), actor=owner, type="discord.question_reply",
                        goal_id=original.goal_id, work_id=original.work_id,
                        payload={**payload.model_dump(), "question_event_id": parent,
                                 "approval_granted": False},
                    ))
            return {"linked": True, "event_id": parent, "approval_granted": False,
                    "message": "답변을 원래 Event에 기록했습니다. 보호 변경은 실행하지 않습니다. 권한·비용 확대는 웹 콘솔에서 승인하세요."}
