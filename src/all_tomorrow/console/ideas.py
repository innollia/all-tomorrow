"""Idea desk: idea text → research prompt for 자료봉 → pasted results → brief for the overseer.

  GET  /api/ideas                     ideas, newest first, with result counts
  POST /api/ideas                     {title?, text} → new idea with its full prompt
  GET  /api/ideas/{id}                idea, full prompt, results, brief (markdown)
  POST /api/ideas/{id}/results        {text}: one or more pasted result blocks

Flow (user side): paste an idea → copy the full prompt (universal meta-prompt + idea) to
자료봉, the user's separate research agent → 자료봉 answers with N self-contained sub-prompts →
the user runs each one in its own 자료봉 session → pastes every result back here.

자료봉 cannot see this PC and its sessions cannot talk to each other, so every sub-prompt carries
the whole idea and ends with a fixed result block (idea ID + subtask ID) that `parse_results`
reads. No model is called here: the brief is a deterministic grouping of the pasted results.

State for the overseer: ctx.feature_dir("ideas") holds ideas.sqlite (original pastes and
parsed results) and briefs/<idea id>.md (idea + latest result per subtask + every raw paste),
rewritten on every change. A prompt.md in that directory replaces the built-in meta-prompt.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext

META_PROMPT = """너는 자료조사 에이전트다. 아래 [아이디어]를 사업·프로젝트로 할 만한지 판단할 자료를 모으려 한다.
지금 할 일은 조사 자체가 아니라, 조사를 나눠 맡길 **하위 프롬프트**를 만드는 것이다.

## 조건
- 하위 프롬프트는 서로 다른 새 세션에서 동시에 따로 실행된다. 세션끼리 대화할 수 없고, 이 대화도 보지 못한다.
  그러니 각 하위 프롬프트는 자기완결이어야 한다: 아이디어 요약(필요한 원문 포함)·조사 질문·범위·판단 기준을 그 안에 다 적는다.
  "앞의 결과를 참고해" 같은 다른 하위과제에 기대는 지시는 넣지 않는다.
- 실행하는 쪽은 웹사이트와 GitHub에 접근할 수 있고, 의뢰인의 PC나 파일에는 접근할 수 없다. 의뢰인에게 되묻지 않고 끝낼 수 있게 쓴다.
- 하위과제는 3~6개. 서로 겹치지 않게 나눈다. 예: 이미 있는 서비스·오픈소스(GitHub)·특허, 수요·고객·지불 의사, 수익 모델·가격, 만드는 데 드는 기술·비용·기간, 법·플랫폼 정책 리스크, 유통·첫 고객 확보. 아이디어에 맞게 고르고 바꾼다.
- 하위과제 ID는 S1, S2, … 순서로 붙인다. 아이디어 ID는 `{idea_id}` 그대로 쓴다.
- 모든 하위 프롬프트는 사실마다 출처 URL을 달고, 확인한 사실과 추정을 구분하고, 한국어로 답하게 한다.
- 모든 하위 프롬프트의 맨 끝에 아래 [결과 형식]을 글자 그대로(ID만 채워서) 넣고, "답은 이 형식 블록 하나로만 낸다"고 적는다.

## 결과 형식 (하위 프롬프트에 그대로 넣을 것)
```
=== 자료봉 결과 ===
아이디어 ID: {idea_id}
하위과제 ID: S?
하위과제: (하위과제 제목)
---
## 결론 (3줄 이내)
## 근거 (사실마다 출처 URL)
## 추정·불확실한 점
## 다음에 확인할 것
=== 끝 ===
```

## 네 답의 형식
하위과제마다 아래처럼 낸다. 사용자가 코드블록 하나씩 복사해 새 세션에 붙여넣는다. 다른 설명은 붙이지 않는다.

### S1 · (하위과제 제목)
```
(자기완결 하위 프롬프트 전문)
```

[아이디어]
아이디어 ID: {idea_id}
제목: {title}

{text}
"""

BLOCK = re.compile(r"=== *자료봉 결과 *===(.*?)(?:=== *끝 *===|\Z)", re.S)
FIELD = re.compile(r"^\s*(아이디어 ID|하위과제 ID|하위과제)\s*[:：]\s*(.*?)\s*$", re.M)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_results(text: str) -> list[dict[str, str]]:
    """Split a paste into result blocks. Text without any block becomes one unlabelled result."""
    blocks = [m.group(1) for m in BLOCK.finditer(text)] or [text]
    parsed = []
    for block in blocks:
        head, sep, body = block.partition("\n---")
        if not sep:
            head, body = block, block
        fields = {k: v for k, v in FIELD.findall(head)}
        parsed.append({
            "idea_id": fields.get("아이디어 ID", "").strip("`* "),
            "subtask_id": fields.get("하위과제 ID", "").strip("`* ").upper(),
            "subtask_title": fields.get("하위과제", "").strip("`* "),
            "body": body.strip(),
        })
    return [p for p in parsed if p["body"]]


class IdeaStore:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.db_path = base / "ideas.sqlite"
        self.briefs = base / "briefs"
        self.briefs.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS ideas (id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL,
                prompt TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS pastes (id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL, raw TEXT NOT NULL,
                created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL, paste_id INTEGER NOT NULL,
                subtask_id TEXT NOT NULL, subtask_title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def meta_prompt(self) -> str:
        custom = self.base / "prompt.md"
        return custom.read_text(encoding="utf-8") if custom.exists() else META_PROMPT

    def create(self, title: str, text: str) -> str:
        idea_id = "I-" + datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(2)
        title = title.strip() or text.strip().splitlines()[0][:60]
        values = {"idea_id": idea_id, "title": title, "text": text.strip()}
        prompt = re.sub(r"\{(idea_id|title|text)\}", lambda m: values[m.group(1)], self.meta_prompt())
        stamp = now()
        with self.db() as db:
            db.execute("INSERT INTO ideas VALUES (?,?,?,?,?,?)", (idea_id, title, text.strip(), prompt, stamp, stamp))
        self.write_brief(idea_id)
        return idea_id

    def list(self) -> list[dict[str, Any]]:
        with self.db() as db:
            rows = db.execute("""SELECT i.id, i.title, i.created_at, i.updated_at,
                (SELECT COUNT(*) FROM results r WHERE r.idea_id = i.id) AS results,
                (SELECT COUNT(DISTINCT subtask_id) FROM results r WHERE r.idea_id = i.id) AS subtasks
                FROM ideas i ORDER BY i.updated_at DESC""").fetchall()
        return [dict(r) for r in rows]

    def get(self, idea_id: str) -> dict[str, Any] | None:
        with self.db() as db:
            idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
            if idea is None:
                return None
            results = db.execute("SELECT * FROM results WHERE idea_id = ? ORDER BY id DESC", (idea_id,)).fetchall()
            pastes = db.execute("SELECT * FROM pastes WHERE idea_id = ? ORDER BY id", (idea_id,)).fetchall()
        return {**dict(idea), "results": [dict(r) for r in results], "pastes": [dict(p) for p in pastes]}

    def add_results(self, idea_id: str, raw: str) -> list[dict[str, Any]]:
        parsed = parse_results(raw)
        if not parsed:
            raise ValueError("붙여넣은 내용이 비어 있다")
        wrong = sorted({p["idea_id"] for p in parsed if p["idea_id"] and p["idea_id"] != idea_id})
        if wrong:
            raise ValueError(f"다른 아이디어의 결과다: {', '.join(wrong)} (이 화면은 {idea_id})")
        stamp = now()
        with self.db() as db:
            paste_id = db.execute("INSERT INTO pastes (idea_id, raw, created_at) VALUES (?,?,?)",
                                  (idea_id, raw, stamp)).lastrowid
            for p in parsed:
                db.execute("""INSERT INTO results (idea_id, paste_id, subtask_id, subtask_title, body, created_at)
                              VALUES (?,?,?,?,?,?)""",
                           (idea_id, paste_id, p["subtask_id"] or "?", p["subtask_title"], p["body"], stamp))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (stamp, idea_id))
        self.write_brief(idea_id)
        return parsed

    def brief(self, idea_id: str) -> str:
        idea = self.get(idea_id)
        if idea is None:
            return ""
        latest: dict[str, dict[str, Any]] = {}
        for r in idea["results"]:  # newest first, so the first per subtask wins
            latest.setdefault(r["subtask_id"], r)
        order = sorted(latest, key=lambda s: (s == "?", int(s[1:]) if s[1:].isdigit() else 999, s))
        lines = [f"# {idea['title']} ({idea['id']})", "",
                 f"- 만든 때: {idea['created_at']} · 마지막 변경: {idea['updated_at']}",
                 f"- 결과: 하위과제 {len([s for s in latest if s != '?'])}개 · 붙여넣기 {len(idea['pastes'])}회",
                 "", "## 원문", "", idea["text"], "", "## 정리본 (하위과제별 최신 결과)", ""]
        if not order:
            lines += ["아직 결과 없음.", ""]
        for sid in order:
            r = latest[sid]
            title = r["subtask_title"] or ("형식 밖 결과" if sid == "?" else "")
            lines += [f"### {sid} · {title}".rstrip(" ·"), f"_{r['created_at']}_", "", r["body"], ""]
        lines += ["## 붙여넣은 원문 (전부, 오래된 순)", ""]
        for p in idea["pastes"]:
            lines += [f"<details><summary>{p['created_at']}</summary>", "", "```", p["raw"], "```", "", "</details>", ""]
        return "\n".join(lines)

    def write_brief(self, idea_id: str) -> None:
        text = self.brief(idea_id)
        target = self.briefs / f"{idea_id}.md"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)


class IdeaRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=50_000)


class PasteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = IdeaStore(ctx.feature_dir("ideas"))
    router = APIRouter(prefix="/api/ideas")

    def found(idea_id: str) -> dict[str, Any]:
        idea = store.get(idea_id)
        if idea is None:
            raise HTTPException(404, "no such idea")
        return idea

    @router.get("")
    async def ideas(_: str = Depends(ctx.current_user)) -> list[dict[str, Any]]:
        return store.list()

    @router.post("")
    async def create(body: IdeaRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        if not body.text.strip():
            raise HTTPException(422, "아이디어 텍스트가 비어 있다")
        return found(store.create(body.title, body.text))

    @router.get("/{idea_id}")
    async def idea(idea_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        return {**found(idea_id), "brief": store.brief(idea_id), "brief_path": str(store.briefs / f"{idea_id}.md")}

    @router.post("/{idea_id}/results")
    async def results(idea_id: str, body: PasteRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        found(idea_id)
        try:
            parsed = store.add_results(idea_id, body.text)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"added": [{k: p[k] for k in ("subtask_id", "subtask_title")} for p in parsed]}

    return router
