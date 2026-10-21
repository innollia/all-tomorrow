"""Turn collected sessions into problem→solution cards with free models.

Calls go through the idea factory's LiteLLM gateway (key rotation, cooldown).
Text is redacted again right before it leaves the PC, and a call is refused if
any known secret value would still be in the request.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from all_tomorrow.idea_factory.llm import LLMError, chat_json
from all_tomorrow.overseer import oracle
from all_tomorrow.overseer.redact import Redactor

log = logging.getLogger("all_tomorrow.overseer")

CHUNK_CHARS = 20000
MODEL_GROUPS = ("g-nemotron-super", "g-gpt-oss-120b", "g-gemma")
PROMPT_VERSION = "1"

SYSTEM = """너는 개발 세션 기록에서 다시 쓸 수 있는 문제 해결 노하우를 뽑는 정리자다.
기록 형식: [U] 사용자 말, [A] 에이전트 말, [T] 도구 호출, [E] 실패한 도구 출력.

다른 프로젝트에서 같은 문제를 만난 에이전트가 바로 가져다 쓸 수 있는 것만 카드로 만든다.
- 카드가 되는 것: 오류·막힘·삽질과 그것을 푼 방법, 도구·환경·라이브러리의 함정, 효과가 확인된 우회법.
- 카드가 아닌 것: 평범한 작업 진행(파일 읽기, 단순 수정, 기능 구현 자체), 프로젝트 고유 기획 내용.
- 풀지 못한 문제도 outcome "미해결"로 남긴다. 다음에 같은 함정을 피하는 데 쓰인다.
- 기록에 없는 내용은 지어내지 않는다.

카드 형식:
{"problem": "증상 1~2문장. 오류 메시지의 핵심 문구 포함",
 "situation": ["OS·셸·언어·도구·라이브러리 태그"],
 "attempts": "실패한 시도 요약. 없으면 빈 문자열",
 "solution": "효과가 있던 해결. 명령·설정·코드 위치처럼 구체적으로",
 "outcome": "해결" | "미해결" | "포기",
 "evidence": "근거가 된 기록 속 짧은 문구"}

카드가 없으면 []를 낸다. JSON 배열만 출력한다."""

_SCHEMA = """
create table if not exists cards (
    card_id     text primary key,
    source      text not null,
    session_id  text not null,
    project     text,
    agent       text,
    models      text,
    problem     text not null,
    situation   text,
    attempts    text,
    solution    text,
    outcome     text,
    evidence    text,
    chunk       integer,
    distilled_by text,
    prompt_version text,
    status      text not null default 'candidate',
    created_at  text not null
);
create index if not exists cards_session on cards(source, session_id);
create table if not exists distilled (
    source      text not null,
    session_id  text not null,
    fingerprint text not null,
    chunks      integer,
    cards       integer,
    failed_chunks integer,
    at          text not null,
    primary key (source, session_id)
);
"""

Chat = Callable[[str, str, str], tuple[object, str]]


class SecretLeak(RuntimeError):
    pass


def ensure_schema(con) -> None:
    con.executescript(_SCHEMA)


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on line boundaries so a [U]/[A]/[E] line is never cut in half (unless it alone is huge)."""
    out, current, length = [], [], 0
    for line in text.splitlines():
        if length + len(line) > size and current:
            out.append("\n".join(current))
            current, length = [], 0
        current.append(line[:size])
        length += min(len(line), size) + 1
    if current:
        out.append("\n".join(current))
    return out


def _guarded(redact: Redactor, secrets: set[str], text: str) -> str:
    text = redact(text)
    if any(s in text for s in secrets):
        raise SecretLeak("a known secret value survived redaction")
    return text


def _call(chat: Chat, user: str) -> tuple[list, str]:
    last: Exception | None = None
    for group in MODEL_GROUPS:
        try:
            data, served = chat(group, SYSTEM, user)
            if isinstance(data, dict):
                data = data.get("cards", [data])
            if not isinstance(data, list):
                raise LLMError(f"expected a list, got {type(data).__name__}")
            return data, f"{group}:{served}"
        except LLMError as error:
            last = error
            log.warning("distill via %s failed: %s", group, str(error)[:200])
    raise LLMError(str(last))


def pilot_sessions(con, per_source: int = 2, max_chars: int = 60000) -> list[tuple[str, str]]:
    """A mixed sample for the user to judge: top-level sessions that hit errors and had a real exchange."""
    picked: list[tuple[str, str]] = []
    for (source,) in con.execute("select distinct source from sessions order by source").fetchall():
        picked += con.execute(
            "select source, session_id from sessions where source=? "
            "and (parent_id is null or source = 'kiro') and coalesce(title, '') not like 'You are a memory%' "
            # Kiro/Antigravity logs carry no tool-failure marks, so errors can't be required there.
            "and n_user >= 2 and (n_errors >= 1 or source in ('kiro', 'antigravity')) "
            "and length(text) between 3000 and ? "
            "order by n_errors * 1.0 / (length(text) / 1000.0 + 1) desc, updated_at desc limit ?",
            (source, max_chars, per_source)).fetchall()
    return picked


def pending_sessions(con, limit: int, quiet_minutes: int = 30) -> list[tuple[str, str]]:
    """Newest sessions not yet distilled (or changed since), skipping ones still being worked in."""
    return con.execute(
        "select s.source, s.session_id from sessions s left join distilled d "
        "on d.source = s.source and d.session_id = s.session_id "
        "where (d.fingerprint is null or d.fingerprint != s.fingerprint) "
        "and s.n_user >= 1 and length(s.text) >= 1500 "
        "and coalesce(s.title, '') not like 'You are a memory%' "
        "and coalesce(s.updated_at, '') < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) "
        "order by s.updated_at desc limit ?",
        (f"-{quiet_minutes} minutes", limit)).fetchall()


def distill_session(con, source: str, session_id: str, *, redact: Redactor, secrets: frozenset[str],
                    chat: Chat | None = None) -> int:
    chat = chat or (lambda g, s, u: chat_json(g, s, u, max_tokens=4000, temperature=0.2))
    row = con.execute("select fingerprint, project, agent, models, title, text from sessions "
                      "where source=? and session_id=?", (source, session_id)).fetchone()
    if row is None:
        raise KeyError(f"{source}/{session_id} not collected")
    fingerprint, project, agent, models, title, text = row
    header = f"도구: {agent}\n모델: {', '.join(json.loads(models or '[]'))}\n프로젝트: {project}\n제목: {title}\n\n"
    # Ask the models first and write afterwards in one short transaction: holding the
    # write lock through minutes of model calls blocked every other writer (2026-10-20).
    made = failed = 0
    parts = chunks(text or "")
    rows = []
    for i, part in enumerate(parts):
        user = _guarded(redact, secrets, header + f"[기록 {i + 1}/{len(parts)}]\n" + part)
        try:
            cards, served = _call(chat, user)
        except LLMError:
            failed += 1
            continue
        now = datetime.now(timezone.utc).isoformat()
        for card in cards:
            if not isinstance(card, dict) or not str(card.get("problem", "")).strip():
                continue
            situation = card.get("situation") or []
            rows.append((uuid.uuid4().hex, source, session_id, project, agent, models,
                         redact(str(card.get("problem", ""))),
                         json.dumps(situation if isinstance(situation, list) else [str(situation)], ensure_ascii=False),
                         redact(str(card.get("attempts", ""))), redact(str(card.get("solution", ""))),
                         str(card.get("outcome", "")), redact(str(card.get("evidence", "")))[:500],
                         i, served, PROMPT_VERSION, now))
            made += 1
    oracle.ensure_schema(con)
    con.execute("delete from cards_fts where card_id in (select card_id from cards where source=? "
                "and session_id=?)", (source, session_id))
    con.execute("delete from cards where source=? and session_id=?", (source, session_id))
    con.executemany(
        "insert into cards (card_id, source, session_id, project, agent, models, problem, situation, "
        "attempts, solution, outcome, evidence, chunk, distilled_by, prompt_version, created_at) "
        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    oracle.index_session_cards(con, source, session_id)
    # A session with a failed chunk keeps a non-matching fingerprint so the next run retries it.
    con.execute("insert or replace into distilled values (?,?,?,?,?,?,?)",
                (source, session_id, fingerprint if failed == 0 else "retry", len(parts), made, failed,
                 datetime.now(timezone.utc).isoformat()))
    con.commit()
    return made
