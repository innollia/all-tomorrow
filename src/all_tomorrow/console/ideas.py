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

import json
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

META_PROMPT = """너는 자료조사 총괄이다. 아래 [아이디어]를 사업·프로젝트로 할 만한지 판단할 자료를 모으려 한다.
지금 할 일은 조사 자체가 아니라, 조사를 나눠 맡길 **자기완결 하위 프롬프트**와 그 작업 경계를 만드는 것이다.

## 실행 환경 (하위 프롬프트가 지켜야 할 전제)
- 하위 프롬프트는 사용자가 서로 다른 새 세션에 하나씩 붙여 동시에 돌린다. 세션끼리 대화할 수 없고, 이 대화도 보지 못한다. 공유 기억이 없다.
- 실행하는 쪽은 웹사이트와 GitHub에 접근할 수 있고, 의뢰인의 PC·파일에는 접근할 수 없다. 의뢰인에게 되묻지 않고 끝낼 수 있어야 한다.
- 결과는 사용자가 웹사이트에 붙여넣고 나중에 합친다. 합치는 단계에서 믿을 수 있게, 출처 목록이 아니라 **주장마다** 근거(URL·인용)를 붙인다.

## 분해 순서 (이 순서대로 생각하고 1~3을 답에 적는다)
1. 아이디어 분석: 제품, 고객, 해결하는 문제, 수익 방식, 지금 있는 근거, 중요한 가정. 원문에 없는 것은 "가정"으로 표시한다.
2. 핵심 불확실성: 맞고 틀림에 따라 성패가 크게 바뀌는데 아직 검증 안 된 가정을 중요한 순으로. 시장·기술·법률·유통 같은 분야는 빠뜨림 점검용일 뿐 고정 목차가 아니다.
3. 조사 과제: 불확실성마다 과제를 만들고 각각 검사한다 — 단독 실행 가능한가, 다른 결과를 기다려야 하는가, 결과가 실제 결정(할지/말지/어떻게)에 쓰이는가. 결정에 안 쓰이는 과제는 버린다. 과제마다 분류를 붙인다.
   - 독립: 그대로 병렬.
   - 의존: 다른 과제 결과가 필요하면, 필요한 값을 명시한 가정으로 박아 넣어 병렬로 돌리거나 "2차"로 표시한다.
   - 교차검증: 결론이 특히 중요하거나 출처가 약할 것 같은 주장은 같은 질문을 다른 접근으로 따로 조사하는 과제를 하나 더 둔다.
   - 현장검증: 조사로는 답이 안 나는 것(실제 구매 의향 등)은 조사로 가설과 직접 검증 방법을 쓰는 과제로 만든다.
- 과제 수는 기본 3~5개(사용자가 손으로 돌리므로 많을수록 좋지 않다). 과제끼리 범위가 겹치지 않게 exclusions로 경계를 나눈다.
- 과제 ID는 S1, S2, … 로 붙인다. 아이디어 ID는 `{idea_id}` 그대로 쓴다.

## 하위 프롬프트 계약 (모든 하위 프롬프트에 아래 필드를 이 이름 그대로 다 넣는다)
- idea_brief: 아이디어 공통 맥락. 1단계 분석 요약 + 이 과제에 필요한 원문. 다른 세션이 이것만 보고 이해할 수 있게.
- task_id: {idea_id} / S?
- objective: 답해야 할 핵심 질문 하나(와 그 답이 바꿀 결정).
- scope: 반드시 다룰 범위.
- exclusions: 다루지 않을 것(다른 과제가 맡는 범위 포함).
- source_policy: 쓸 출처 종류(공식 문서·통계·특허·GitHub·뉴스·커뮤니티 등)와 우선순위, 기준 시점, 검증 조건(예: 숫자는 1차 출처 또는 독립 출처 2곳).
- deliverables: 꼭 내야 할 산출물(표·목록·수치 등).
- completion_rule: 상태 판정 기준. 완료 = objective에 근거 있는 답, 불완전 = 일부만 답함(빠진 것을 적음), 실패 = 답할 근거를 못 찾음(시도한 검색과 이유를 적음).
- 마지막에 아래 [결과 형식]을 글자 그대로(ID만 채워서) 넣고, "답은 이 형식 블록 하나로만 낸다. 출처 없는 주장은 '구분: 추정'으로 적는다"고 적는다.

## 결과 형식 (하위 프롬프트에 그대로 넣을 것)
```
=== 자료봉 결과 ===
아이디어 ID: {idea_id}
하위과제 ID: S?
하위과제: (과제 제목)
상태: 완료 | 불완전 | 실패
---
## 결론 (3줄 이내)
## 주장과 근거
- [C1] (주장 한 문장)
  - 출처: (URL)
  - 인용: "(출처 원문에서 그대로 옮긴 한두 문장)"
  - 구분: 확인 | 추정
- [C2] …
## 빠진 것·실패 이유 (상태가 완료가 아니면 반드시)
## 다음에 확인할 것
=== 끝 ===
```

## 네 답의 형식
1~3단계(분석·불확실성·과제 표: ID·제목·분류·결정에 쓰이는 곳)를 짧게 적은 뒤, 과제마다 아래처럼 낸다.
사용자가 코드블록 하나씩 복사해 새 세션에 붙여넣는다. 2차 과제는 제목에 "(2차)"를 붙인다.

### S1 · (과제 제목) · (분류)
```
(자기완결 하위 프롬프트 전문)
```

[아이디어]
아이디어 ID: {idea_id}
제목: {title}

{text}
"""

BLOCK = re.compile(r"=== *자료봉 결과 *===(.*?)(?:=== *끝 *===|\Z)", re.S)
FIELD = re.compile(r"^\s*(아이디어 ID|하위과제 ID|과제 ID|task_id|하위과제|과제|상태)\s*[:：]\s*(.*?)\s*$", re.M)
CLAIM = re.compile(r"^\s*[-*]\s*\[(C\d+)\]\s*(.+)$")
CLAIM_FIELD = re.compile(r"^\s+[-*]\s*(출처|인용|구분)\s*[:：]\s*(.*?)\s*$")
STATUSES = ("완료", "불완전", "실패")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_claims(body: str) -> list[dict[str, str]]:
    """`- [C1] 주장` lines with indented 출처/인용/구분 sub-items."""
    claims: list[dict[str, str]] = []
    for line in body.splitlines():
        if m := CLAIM.match(line):
            claims.append({"id": m.group(1), "claim": m.group(2).strip(), "source": "", "quote": "", "kind": ""})
        elif claims and (m := CLAIM_FIELD.match(line)):
            key = {"출처": "source", "인용": "quote", "구분": "kind"}[m.group(1)]
            claims[-1][key] = m.group(2).strip().strip("<>")
    return claims


def parse_results(text: str) -> list[dict[str, Any]]:
    """Split a paste into result blocks. Text without any block becomes one unlabelled result."""
    blocks = [m.group(1) for m in BLOCK.finditer(text)] or [text]
    parsed = []
    for block in blocks:
        head, sep, body = block.partition("\n---")
        if not sep:
            head, body = block, block
        fields = {k: v.strip("`* ") for k, v in FIELD.findall(head)}
        status = next((s for s in STATUSES if s == fields.get("상태", "").split("|")[0].strip()), "")
        task = fields.get("하위과제 ID") or fields.get("과제 ID") or fields.get("task_id", "")
        task = task.split("/")[-1].strip().upper()
        parsed.append({
            "idea_id": fields.get("아이디어 ID", ""),
            "subtask_id": task,
            "subtask_title": fields.get("하위과제") or fields.get("과제", ""),
            "status": status,
            "claims": parse_claims(body),
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
            columns = {row["name"] for row in db.execute("PRAGMA table_info(results)")}
            if "status" not in columns:  # added with the claim/evidence result format
                db.execute("ALTER TABLE results ADD COLUMN status TEXT NOT NULL DEFAULT ''")
                db.execute("ALTER TABLE results ADD COLUMN claims TEXT NOT NULL DEFAULT '[]'")

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
        return {**dict(idea), "results": [{**dict(r), "claims": json.loads(r["claims"])} for r in results], "pastes": [dict(p) for p in pastes]}

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
                db.execute("""INSERT INTO results (idea_id, paste_id, subtask_id, subtask_title, body, created_at,
                              status, claims) VALUES (?,?,?,?,?,?,?,?)""",
                           (idea_id, paste_id, p["subtask_id"] or "?", p["subtask_title"], p["body"], stamp,
                            p["status"], json.dumps(p["claims"], ensure_ascii=False)))
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
        else:
            lines += ["| 과제 | 상태 | 주장 | 출처 없음 | 추정 |", "|---|---|---|---|---|"]
            for sid in order:
                r = latest[sid]
                claims = r["claims"]
                lines.append(f"| {sid} {r['subtask_title']} | {r['status'] or '표시 없음'} | {len(claims)} | "
                             f"{sum(not c['source'] for c in claims)} | {sum(c['kind'] == '추정' for c in claims)} |")
            lines.append("")
        for sid in order:
            r = latest[sid]
            title = r["subtask_title"] or ("형식 밖 결과" if sid == "?" else "")
            lines += [f"### {sid} · {title}".rstrip(" ·"), f"_{r['status'] or '상태 표시 없음'} · {r['created_at']}_", "",
                      r["body"], ""]
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
        return {"added": [{"subtask_id": p["subtask_id"], "subtask_title": p["subtask_title"], "status": p["status"],
                           "claims": len(p["claims"])} for p in parsed]}

    return router
