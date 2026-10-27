"""Idea desk: idea text → research prompt for 자료봉 → pasted results → brief for the overseer.

  GET  /api/ideas                     ideas, newest first, with result counts
  POST /api/ideas                     {title?, text} → new idea with its full prompt
  GET  /api/ideas/{id}                idea, full prompt, results, brief (markdown)
  POST /api/ideas/{id}/results        {text}: one or more pasted result blocks
  PUT  /api/ideas/{id}/plan           {text}: 자료봉's decomposition answer (replaces; "" clears)
  POST /api/ideas/intake              {text?, files?[{name,data}], idea_id?}: free material in any shape (see below)
  PUT  /api/ideas/{id}/materials/{n}/subtask  {subtask_id}: move a free material to a task ("" = free)
  DELETE /api/ideas/{id}/materials/{n}  one free material
  POST /api/ideas/{id}/adopt          a new-idea candidate becomes a normal idea
  DELETE /api/ideas/{id}              idea, its results, pastes and brief file
  DELETE /api/ideas/{id}/results/{n}  one result (its raw paste too once nothing else uses it)

Flow (user side): paste an idea → copy the full prompt (universal meta-prompt + idea) to
자료봉, the user's separate research agent → 자료봉 answers with N self-contained sub-prompts →
the user runs each one in its own 자료봉 session → pastes every result back here.

자료봉 cannot see this PC and its sessions cannot talk to each other, so every sub-prompt carries
the whole idea and ends with a fixed result block (idea ID + subtask ID) that `parse_results`
reads. No model is called here: the brief is a deterministic grouping of the pasted results.

Free material: the user may also research on their own, with no prompt and no subtasks, and throw the outcome
in as pasted text (chat logs, notes, article bodies), links (a bare URL is enough; the page text is fetched) or
files (md, txt, pdf). Without an idea chosen, Jev picks one of the existing ideas (one request, one Choice per
material); if none fits (or Jev is down) the material starts a new idea candidate. If a saved decomposition has
tasks, Jev may also put the material on one; otherwise it stays "free material". Nothing is refused because
sorting failed. Every material keeps its source (kind, link or file name, when it arrived) and reaches the brief
and the overseer summary next to the systematic results. Filled 자료봉 result blocks pasted this way go through
the old result path.

State for the overseer: ctx.feature_dir("ideas") holds ideas.sqlite (original pastes and
parsed results) and briefs/<idea id>.md, rewritten on every change. The brief holds every result
body exactly once (latest per subtask, then replaced ones); raw pastes appear there only as what the
parser did not keep (block headers, text outside blocks), since their bodies are already above. The
full raw pastes stay in the database. A prompt.md in that directory replaces the built-in meta-prompt.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext, ideas_intake, ideas_jev, jev

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
- 아래 세 관점은 어떤 아이디어든 빠짐없이 과제에 배정한다. 표에 어느 과제가 맡았는지 적는다.

## 반드시 넣을 관점 1: 유사 제품의 성장 궤적 사례
"이미 비슷한 기능이 있다"는 기능 단위 비교만으로 결론을 내지 않는다. 과제 하나는 반드시 유사·인접 제품이 **어떤 모습으로 시작해 어떻게 커졌는지(또는 멈췄는지)**를 사례로 조사한다(독립 과제로 병렬).
- 사례 고르기: 성공한 것만 고르지 않는다. 범주를 선점한 것, 정체한 것, 실패·중단한 것을 섞는다. 다음 유형을 각각 찾는다.
  - 처음 공개판은 조악했지만 관심이 붙어, 지금은 "그 분야 프로그램" 하면 반드시 거론되는 이름이 된 프로그램
  - 모듈·플러그인·확장으로 먼저 인기를 끈 뒤, 그 모듈을 탑재한 통합 도구(하네스·앱)로 넓힌 경우(확장 후 성패가 확인 안 되면 "미상"으로 적는다)
  - 개인·소규모 팀이 시작한 것을 우선하고, 대기업 제품은 비교 기준으로만 쓴다
- 사례마다 적을 것(표로):
  - 처음 내놓은 형태: 완성된 하나의 프로그램 / 모듈·플러그인·확장 / 기타
  - 초기 완성도: 첫 공개판이 얼마나 거칠었는지(첫 공개 시점, 기능 범위, 당시 불만·버그)
  - 관심이 붙은 경로: 어느 커뮤니티·입소문·채널(포럼, 디스코드, 유튜브, 스토어 순위, 추천 글 등)에서 무엇 때문에
  - 이후 확장 경로: 예) 모듈→통합 하네스, 무료→유료, 한 용도→여러 용도
  - 성과 판정: 성공 / 정체 / 실패 / 미상 과 그 근거(사용자 수·매출·업데이트 중단·커뮤니티 활동 등, 1차 출처 우선)
  - 범주 대표성: 그 분야 프로그램을 찾는 사람이 먼저 떠올리는 이름이 되었는지(추천·비교 글, 커뮤니티 질문 답변, 검색 상위에서 거론되는 근거)
  - 이 아이디어에 주는 교훈 한 줄

## 반드시 넣을 관점 2: 사업 형태를 나눠 평가
- "모듈(다른 도구에 붙는 기능 단위)을 파는 것"과 "완성된 하나의 프로그램을 파는 것"은 서로 다른 사업이다. 고객·유통 채널·가격·경쟁 상대·성장 경로가 다르다.
- 시장·수익·경쟁을 다루는 과제의 scope와 deliverables에 두 형태를 **각각** 평가하는 항목을 넣는다. 하나로 뭉뚱그려 "기능이 겹치니 좁은 모듈부터" 같은 결론을 내지 않게 한다.
- 두 형태를 잇는 단계 전략(모듈로 시작해 프로그램으로 확장 등)을 말하려면 관점 1의 실제 사례를 근거로 단다.

## 반드시 넣을 관점 3: 국가·언어권별 시장
- 글로벌 시장과 국가·언어권별 시장(특히 아이디어 원문 언어의 시장)을 따로 본다. 글로벌에 비슷한 제품이 있어도 그 언어권에서 범주를 대표하는 프로그램이 아직 없으면 따로 판단한다.
- 그 언어권의 현재 대표 프로그램, 사용자 커뮤니티, 유통 채널, 범주를 선점하는 경로(현지화·커뮤니티·플랫폼)를 글로벌 결론과 분리해 적게 한다.

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
1~3단계(분석·불확실성·과제 표: ID·제목·분류·결정에 쓰이는 곳·맡은 관점 1~3)를 짧게 적은 뒤, 과제마다 아래처럼 낸다.
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

BLOCK = re.compile(r"=+\s*자료봉\s*결과\s*=+(.*?)(?:=+\s*끝\s*=+?|(?==+\s*자료봉\s*결과)|\Z)", re.S)
IDEA_ID = re.compile(r"I-\d{6}-[0-9a-f]{4}", re.I)
TASK_ID = re.compile(r"(?:하위\s*과제|과제)\s*ID|task_id", re.I)
SUBTASK = re.compile(r"\bS\d{1,2}\b", re.I)
# Header labels; a value runs until the next label, a line break or the body separator, because
# 자료봉 output often arrives with several fields on one line (lost line breaks, markdown bold).
LABELS = r"(?:아이디어\s*ID|하위\s*과제\s*ID|과제\s*ID|task_id|하위\s*과제|과제|상태|기준\s*시점|분류)"
TITLE = re.compile(r"(?<![\w])(?:하위\s*과제|과제)(?!\s*ID)\s*[:：]\s*(.+?)(?=\s*" + LABELS + r"\s*[:：]|\n|$)")
STATUS = re.compile(r"상태\s*[:：]?\s*(완료|불완전|실패)")
SEPARATOR = re.compile(r"(?m)^\s*-{3,}\s*$|\s-{3,}\s|(?=#+\s*결론)")
CLAIM = re.compile(r"^\s*[-*]?\s*\[(C\d+)\]\s*(.+)$")
CLAIM_FIELD = re.compile(r"^\s*[-*]\s*(출처|인용|구분)\s*[:：]\s*(.*?)\s*$")
STATUSES = ("완료", "불완전", "실패")
# The result template inside a decomposition answer lists every status; a filled result names one.
TEMPLATE_STATUS = re.compile(r"완료\s*\|\s*불완전")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_claims(body: str) -> list[dict[str, str]]:
    """`- [C1] 주장` lines with 출처/인용/구분 sub-items (indented or not)."""
    claims: list[dict[str, str]] = []
    for line in body.splitlines():
        if m := CLAIM.match(line):
            claims.append({"id": m.group(1).upper(), "claim": m.group(2).strip(), "source": "", "quote": "", "kind": ""})
        elif claims and (m := CLAIM_FIELD.match(line)):
            key = {"출처": "source", "인용": "quote", "구분": "kind"}[m.group(1)]
            claims[-1][key] = m.group(2).strip().strip("<>")
    return claims


def parse_header(head: str) -> dict[str, str]:
    """Pick IDs by shape, not by line layout: I-yymmdd-xxxx and S<n>, wherever they sit."""
    idea = IDEA_ID.search(head)
    task = ""
    label = TASK_ID.search(head)
    if label and (m := SUBTASK.search(head, label.end())):
        task = m.group(0)
    elif m := SUBTASK.search(head):
        task = m.group(0)
    title = TITLE.search(head)
    status = STATUS.search(head)
    return {
        "idea_id": idea.group(0)[:9].upper() + idea.group(0)[9:].lower() if idea else "",
        "subtask_id": task.upper(),
        "subtask_title": title.group(1).strip(" -·|") if title else "",
        "status": status.group(1) if status else "",
    }


def parse_results(text: str) -> list[dict[str, Any]]:
    """Split a paste into result blocks. Text without any block becomes one unlabelled result."""
    text = normalize(text)
    blocks =[m.group(1) for m in BLOCK.finditer(text)] or [text]
    parsed = []
    for block in blocks:
        sep = SEPARATOR.search(block)
        head, body = (block[:sep.start()], block[sep.end():]) if sep else (block, block)
        head = head.replace("`", "")
        parsed.append({**parse_header(head), "claims": parse_claims(body), "body": body.strip()})
    return [p for p in parsed if p["body"]]


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("**", "").replace("__", "")


def looks_like_results(text: str) -> bool:
    """Filled 자료봉 result blocks, as opposed to a decomposition answer that quotes the empty template."""
    for m in BLOCK.finditer(normalize(text)):
        block = m.group(1)
        if not TEMPLATE_STATUS.search(block) and STATUS.search(block):
            return True
    return False


def paste_residue(raw: str) -> str:
    """What `parse_results` did not store as a body: block headers and text between blocks."""
    text = normalize(raw)
    matches = list(BLOCK.finditer(text))
    if not matches:  # the whole paste became one unlabelled result body
        return ""
    parts, pos = [], 0
    for m in matches:
        parts.append(text[pos:m.start()])
        if sep := SEPARATOR.search(m.group(1)):
            parts.append(m.group(1)[:sep.start()])
        pos = m.end()
    parts.append(text[pos:])
    return "\n".join(p.strip() for p in parts if re.search(r"\w", p))


def idea_head(item: dict[str, Any]) -> str:
    """Text of a new idea candidate: the title and the start of the material that opened it."""
    return (item["title"] + "\n" + item["body"][:600]).strip()


class IdeaStore:
    def __init__(self, base: Path, use_jev: bool = False) -> None:
        self.use_jev = use_jev  # the web app turns Jev on; direct callers (tests, scripts) call nothing
        self.base = base.resolve()
        self.db_path = self.base / "ideas.sqlite"
        self.briefs = self.base / "briefs"
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
            if "plan" not in {row["name"] for row in db.execute("PRAGMA table_info(ideas)")}:
                # 자료봉's decomposition answer (analysis, uncertainties, task table), pasted back as-is.
                db.execute("ALTER TABLE ideas ADD COLUMN plan TEXT NOT NULL DEFAULT ''")
                db.execute("ALTER TABLE ideas ADD COLUMN plan_at TEXT NOT NULL DEFAULT ''")
            if "assigned" not in {row["name"] for row in db.execute("PRAGMA table_info(results)")}:
                # how the subtask was decided: "ID" (read from the block), "jev:0.93", "user"; "" = unsorted/unlabelled
                db.execute("ALTER TABLE results ADD COLUMN assigned TEXT NOT NULL DEFAULT ''")
            if "candidate" not in {row["name"] for row in db.execute("PRAGMA table_info(ideas)")}:
                # 1 = made by free material that fit no existing idea; the user adopts or deletes it
                db.execute("ALTER TABLE ideas ADD COLUMN candidate INTEGER NOT NULL DEFAULT 0")
            # Free material: what the user researched on their own. task_id "" = not on any task.
            db.execute("""CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL,
                kind TEXT NOT NULL, label TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                note TEXT NOT NULL, task_id TEXT NOT NULL, assigned TEXT NOT NULL, file TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
            # Every saved decomposition stays readable after it is replaced.
            db.execute("""CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL)""")
            if "paras" not in {row["name"] for row in db.execute("PRAGMA table_info(plans)")}:
                # Jev's paragraph filter: [{text, p, keep}]; "[]" = not filtered (the raw text is still in `text`)
                db.execute("ALTER TABLE plans ADD COLUMN paras TEXT NOT NULL DEFAULT '[]'")

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

    def render_prompt(self, idea_id: str, title: str, text: str) -> str:
        values = {"idea_id": idea_id, "title": title, "text": text.strip()}
        return re.sub(r"\{(idea_id|title|text)\}", lambda m: values[m.group(1)], self.meta_prompt())

    def create(self, title: str, text: str, candidate: bool = False) -> str:
        idea_id = "I-" + datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(2)
        title = title.strip() or text.strip().splitlines()[0][:60]
        prompt = self.render_prompt(idea_id, title, text)
        stamp = now()
        with self.db() as db:
            db.execute("INSERT INTO ideas (id, title, text, prompt, created_at, updated_at, candidate) VALUES (?,?,?,?,?,?,?)",
                       (idea_id, title, text.strip(), prompt, stamp, stamp, int(candidate)))
        self.write_brief(idea_id)
        return idea_id

    def list(self) -> list[dict[str, Any]]:
        """Ideas newest-updated first; statuses count the latest result of each subtask."""
        with self.db() as db:
            ideas = [dict(r) for r in db.execute(
                "SELECT id, title, created_at, updated_at, plan_at, candidate FROM ideas ORDER BY updated_at DESC")]
            rows = db.execute("SELECT idea_id, subtask_id, status FROM results ORDER BY id DESC").fetchall()
            free = {r["idea_id"]: r["n"] for r in db.execute("SELECT idea_id, COUNT(*) AS n FROM materials GROUP BY idea_id")}
        latest: dict[str, dict[str, str]] = {}
        totals: dict[str, int] = {}
        for r in rows:
            latest.setdefault(r["idea_id"], {}).setdefault(r["subtask_id"], r["status"])
            totals[r["idea_id"]] = totals.get(r["idea_id"], 0) + 1
        for idea in ideas:
            per = latest.get(idea["id"], {})
            idea["results"] = totals.get(idea["id"], 0)
            idea["materials"] = free.get(idea["id"], 0)
            idea["candidate"] = bool(idea["candidate"])
            idea["subtasks"] = len(per)
            idea["status_counts"] = {s: sum(v == s for v in per.values()) for s in (*STATUSES, "")}
        return ideas

    def recent_summary(self, days: int = 7, now_: datetime | None = None) -> str:
        """Lines for the overseer brief: ideas touched in the last `days` days."""
        cutoff = ((now_ or datetime.now(UTC)) - timedelta(days=days)).isoformat(timespec="seconds")
        lines = []
        for i in self.list():
            if i["updated_at"] < cutoff:
                continue
            c = i["status_counts"]
            lines.append(f"- {i['id']} {i['title']}{' [새 아이디어 후보]' if i['candidate'] else ''} · 과제 {i['subtasks']} (완료 {c['완료']}/불완전 {c['불완전']}/실패 {c['실패']}"
                         f"{'/상태없음 ' + str(c['']) if c[''] else ''}) · 자유 자료 {i['materials']}건 · 쪼개기 {'있음' if i['plan_at'] else '없음'}"
                         f" · 갱신 {i['updated_at'][:16]} · 정리본 {self.briefs / (i['id'] + '.md')}")
        return "\n".join(lines) or f"최근 {days}일 아이디어 조사 없음"

    def get(self, idea_id: str) -> dict[str, Any] | None:
        with self.db() as db:
            idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
            if idea is None:
                return None
            results = db.execute("SELECT * FROM results WHERE idea_id = ? ORDER BY id DESC", (idea_id,)).fetchall()
            pastes = db.execute("SELECT * FROM pastes WHERE idea_id = ? ORDER BY id", (idea_id,)).fetchall()
            plans = db.execute("SELECT * FROM plans WHERE idea_id = ? ORDER BY id DESC", (idea_id,)).fetchall()
            materials = db.execute("SELECT * FROM materials WHERE idea_id = ? ORDER BY id DESC", (idea_id,)).fetchall()
        seen: set[str] = set()
        decoded = []
        for r in results:  # newest first: the first of each subtask is current, the rest were replaced
            decoded.append({**dict(r), "claims": json.loads(r["claims"]), "latest": r["subtask_id"] not in seen})
            seen.add(r["subtask_id"])
        plan_list = [{**dict(p), "paras": json.loads(p["paras"])} for p in plans]
        return {**dict(idea), "candidate": bool(idea["candidate"]), "materials": [dict(m) for m in materials],
                "results": decoded, "pastes": [dict(p) for p in pastes], "plans": plan_list,
                "plan_paras": plan_list[0]["paras"] if plan_list and plan_list[0]["text"] == idea["plan"] else [],
                "tasks": ideas_jev.plan_tasks(idea["plan"])}

    def add_results(self, idea_id: str, raw: str) -> list[dict[str, Any]]:
        return self.add_slots(idea_id, [raw])

    def add_slots(self, idea_id: str, raws: list[str]) -> list[dict[str, Any]]:
        """Save pasted slots (one paste each). Blocks whose task is certain from their own ID labels are
        taken as they are; the rest are put to Jev together with the task list of the saved decomposition."""
        entries: list[tuple[str, dict[str, Any], str]] = []  # (raw, parsed block, how the subtask was decided)
        for raw in raws:
            if not raw.strip():
                continue
            framed = bool(BLOCK.search(normalize(raw)))
            for p in parse_results(raw):
                if not framed and not TASK_ID.search(p["body"]):
                    p = {**p, "loose": p["subtask_id"], "subtask_id": ""}  # a stray "S3" in free text is no label
                entries.append((raw, p, "ID" if p["subtask_id"] else ""))
        if not entries:
            raise ValueError("붙여넣은 내용이 비어 있다")
        wrong = sorted({p["idea_id"] for _, p, _ in entries if p["idea_id"] and p["idea_id"] != idea_id})
        if wrong:
            raise ValueError(f"다른 아이디어의 결과다: {', '.join(wrong)} (이 화면은 {idea_id})")
        pending = [n for n, (_, _, how) in enumerate(entries) if not how]
        picked = None  # Jev's answers; None = Jev not used or failed, then the old loose reading stands
        if pending and self.use_jev:
            tasks = ideas_jev.plan_tasks((self.get(idea_id) or {}).get("plan", ""))
            try:
                if tasks:
                    picked = ideas_jev.classify_bodies(tasks, [entries[n][1]["body"] for n in pending])
            except jev.JevError:
                picked = None
        for k, n in enumerate(pending):
            raw, p, _ = entries[n]
            if picked is not None:
                hit = picked[k]
                title = p["subtask_title"] or (tasks[hit[0]]["title"] if hit else "")
                entries[n] = (raw, {**p, "subtask_id": hit[0] if hit else "", "subtask_title": title},
                              f"jev:{hit[1]:.2f}" if hit else "")
            elif p.get("loose"):
                entries[n] = (raw, {**p, "subtask_id": p["loose"]}, "")
        stamp = now()
        with self.db() as db:
            paste_ids: dict[str, int] = {}
            for raw, p, how in entries:
                if raw not in paste_ids:
                    paste_ids[raw] = db.execute("INSERT INTO pastes (idea_id, raw, created_at) VALUES (?,?,?)",
                                                (idea_id, raw, stamp)).lastrowid
                db.execute("""INSERT INTO results (idea_id, paste_id, subtask_id, subtask_title, body, created_at,
                              status, claims, assigned) VALUES (?,?,?,?,?,?,?,?,?)""",
                           (idea_id, paste_ids[raw], p["subtask_id"] or "?", p["subtask_title"], p["body"], stamp,
                            p["status"], json.dumps(p["claims"], ensure_ascii=False), how))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (stamp, idea_id))
        self.write_brief(idea_id)
        return [{**p, "assigned": how} for _, p, how in entries]

    # --- free material -------------------------------------------------------------------------------

    def intake(self, items: list[dict[str, Any]], idea_id: str = "") -> list[dict[str, Any]]:
        """File free-form items under ideas. `idea_id` given = that idea; else Jev picks among the existing
        ideas, and an item that fits none (or a Jev failure) opens a new idea candidate. Within an idea, Jev may
        put the item on a task of the saved decomposition; if not sure the item stays free. Never refuses
        because of sorting; the only error is nothing usable (ValueError)."""
        items = [i for i in items if i["body"].strip()]
        if not items:
            raise ValueError("넣을 내용이 비어 있다")
        if idea_id and self.get(idea_id) is None:
            raise LookupError(idea_id)
        placed: list[dict[str, Any]] = []   # outcome per item, in order
        rest: list[tuple[int, dict[str, Any]]] = []
        for n, item in enumerate(items):
            placed.append({})
            # Filled 자료봉 result blocks keep their old path (parsed claims, task from the block's own IDs).
            if item["kind"] != "url" and looks_like_results(item["body"]):
                block = next((p["idea_id"] for p in parse_results(item["body"]) if p["idea_id"]), "")
                target = idea_id or (block if block and self.get(block) else "")
                if target and (not block or block == target):
                    added = self.add_slots(target, [item["body"]])
                    placed[n] = {"idea_id": target, "kind": "result", "title": item["title"], "task_id": added[0]["subtask_id"],
                                 "assigned": added[0]["assigned"], "note": "", "candidate": False, "placed_by": "user" if idea_id else "id"}
                    continue
            rest.append((n, item))
        # 1) which idea
        ideas = [{"id": i["id"], "title": i["title"], "text": (self.get(i["id"]) or {}).get("text", "")} for i in self.list()]
        chosen: list[tuple[str, str]]  # (idea id, how)
        if idea_id:
            chosen = [(idea_id, "user")] * len(rest)
        else:
            picks: list[str | None] = [None] * len(rest)
            if rest and ideas and self.use_jev:
                try:
                    picks = ideas_jev.choose_ideas(ideas, [i["body"] for _, i in rest])
                except jev.JevError:
                    picks = [None] * len(rest)
            chosen = [(p, "jev") if p else ("", "") for p in picks]
        # 2) a candidate idea for each item that fit none
        for k, (n, item) in enumerate(rest):
            if not chosen[k][0]:
                chosen[k] = (self.create(item["title"], idea_head(item), candidate=True), "new")
        # 3) which task, one request per idea
        by_idea: dict[str, list[int]] = {}
        for k, (iid, how) in enumerate(chosen):
            if how != "new":
                by_idea.setdefault(iid, []).append(k)
        tasks_of: dict[int, tuple[str, str]] = {}
        for iid, ks in by_idea.items():
            tasks = ideas_jev.plan_tasks((self.get(iid) or {}).get("plan", ""))
            if not (tasks and self.use_jev):
                continue
            try:
                hits = ideas_jev.classify_bodies(tasks, [rest[k][1]["body"] for k in ks])
            except jev.JevError:
                continue
            for k, hit in zip(ks, hits):
                if hit:
                    tasks_of[k] = (hit[0], f"jev:{hit[1]:.2f}")
        for k, (n, item) in enumerate(rest):
            iid, how = chosen[k]
            task, assigned = tasks_of.get(k, ("", ""))
            mid = self.add_material(iid, item, task, assigned)
            placed[n] = {"idea_id": iid, "material_id": mid, "kind": item["kind"], "title": item["title"], "task_id": task,
                         "assigned": assigned, "note": item["note"], "candidate": how == "new",
                         "placed_by": how or "free"}
        for iid in {p["idea_id"] for p in placed if p}:
            self.write_brief(iid)
        for p in placed:
            p["idea_title"] = (self.get(p["idea_id"]) or {}).get("title", "")
        return placed

    def add_material(self, idea_id: str, item: dict[str, Any], task_id: str = "", assigned: str = "") -> int:
        stamp = now()
        with self.db() as db:
            mid = db.execute("""INSERT INTO materials (idea_id, kind, label, url, title, body, note, task_id, assigned, file,
                                created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (idea_id, item["kind"], item["label"], item["url"], item["title"], item["body"][:ideas_intake.MAX_BODY],
                              item["note"], task_id, assigned, "", stamp)).lastrowid
            if item.get("raw"):  # keep the original (a PDF) next to the data so the overseer can open it
                folder = self.base / "files"
                folder.mkdir(exist_ok=True)
                target = folder / (str(mid) + "-" + re.sub(r"[^\w.-]+", "_", item["label"])[:80])
                target.write_bytes(item["raw"])
                db.execute("UPDATE materials SET file = ? WHERE id = ?", (str(target), mid))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (stamp, idea_id))
        return mid

    def assign_material(self, idea_id: str, material_id: int, task_id: str) -> bool:
        sid = task_id.strip().upper()
        if sid and not re.fullmatch(r"S\d{1,2}", sid):
            raise ValueError("과제 ID는 S1, S2 … 형식이고, 비우면 자유 자료다")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM materials WHERE id = ? AND idea_id = ?", (material_id, idea_id)).fetchone():
                return False
            db.execute("UPDATE materials SET task_id = ?, assigned = ? WHERE id = ?", (sid, "user" if sid else "", material_id))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (now(), idea_id))
        self.write_brief(idea_id)
        return True

    def delete_material(self, idea_id: str, material_id: int) -> bool:
        with self.db() as db:
            row = db.execute("SELECT file FROM materials WHERE id = ? AND idea_id = ?", (material_id, idea_id)).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (now(), idea_id))
        if row["file"]:
            Path(row["file"]).unlink(missing_ok=True)
        self.write_brief(idea_id)
        return True

    def adopt(self, idea_id: str) -> bool:
        with self.db() as db:
            if not db.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone():
                return False
            db.execute("UPDATE ideas SET candidate = 0, updated_at = ? WHERE id = ?", (now(), idea_id))
        self.write_brief(idea_id)
        return True

    def assign_result(self, idea_id: str, result_id: int, subtask_id: str) -> bool:
        """The user picks the task of a result (typically one Jev left unsorted)."""
        sid = subtask_id.strip().upper()
        if not re.fullmatch(r"S\d{1,2}|\?", sid):
            raise ValueError("과제 ID는 S1, S2 … 형식이다")
        tasks = ideas_jev.plan_tasks((self.get(idea_id) or {}).get("plan", ""))
        with self.db() as db:
            row = db.execute("SELECT subtask_title FROM results WHERE id = ? AND idea_id = ?", (result_id, idea_id)).fetchone()
            if row is None:
                return False
            title = row["subtask_title"] or (tasks.get(sid, {}).get("title", "") if sid != "?" else "")
            db.execute("UPDATE results SET subtask_id = ?, subtask_title = ?, assigned = ? WHERE id = ?",
                       (sid, title, "user" if sid != "?" else "", result_id))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (now(), idea_id))
        self.write_brief(idea_id)
        return True

    def set_plan(self, idea_id: str, text: str) -> None:
        if looks_like_results(text):
            raise ValueError("자료봉 결과 블록이다. 과제 쪼개기 칸이 아니라 '결과 붙여넣기'에 넣는다")
        paras: list[dict[str, Any]] = []
        if self.use_jev and text.strip():
            idea = self.get(idea_id) or {}
            try:  # Jev failing leaves the plan unfiltered, as before
                paras = ideas_jev.judge_paragraphs(idea.get("title", ""), idea.get("text", ""), text.strip())
            except jev.JevError:
                paras = []
        stamp = now()
        with self.db() as db:
            db.execute("UPDATE ideas SET plan = ?, plan_at = ?, updated_at = ? WHERE id = ?",
                       (text.strip(), stamp, stamp, idea_id))
            db.execute("INSERT INTO plans (idea_id, text, created_at, paras) VALUES (?,?,?,?)",
                       (idea_id, text.strip(), stamp, json.dumps(paras, ensure_ascii=False)))
        self.write_brief(idea_id)

    def delete_idea(self, idea_id: str) -> None:
        with self.db() as db:
            for f in db.execute("SELECT file FROM materials WHERE idea_id = ? AND file != ''", (idea_id,)).fetchall():
                Path(f["file"]).unlink(missing_ok=True)
            for table, column in (("results", "idea_id"), ("pastes", "idea_id"), ("plans", "idea_id"), ("materials", "idea_id"), ("ideas", "id")):
                db.execute(f"DELETE FROM {table} WHERE {column} = ?", (idea_id,))
        (self.briefs / f"{idea_id}.md").unlink(missing_ok=True)

    def delete_result(self, idea_id: str, result_id: int) -> bool:
        """Drop one result; its raw paste goes too once no result from that paste is left."""
        with self.db() as db:
            row = db.execute("SELECT paste_id FROM results WHERE id = ? AND idea_id = ?", (result_id, idea_id)).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM results WHERE id = ?", (result_id,))
            if not db.execute("SELECT 1 FROM results WHERE paste_id = ?", (row["paste_id"],)).fetchone():
                db.execute("DELETE FROM pastes WHERE id = ?", (row["paste_id"],))
            db.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (now(), idea_id))
        self.write_brief(idea_id)
        return True

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
                 f"- 결과: 하위과제 {len([s for s in latest if s != '?'])}개 · 붙여넣기 {len(idea['pastes'])}회"
                 f" · 자유 자료 {len(idea['materials'])}건",
                 *(["- 상태: 새 아이디어 후보 (자유 자료에서 만들어짐, 아직 확정 안 함)"] if idea["candidate"] else []),
                 "", "## 원문", "", idea["text"], "",
                 "## 자료봉 과제 쪼개기 (분석·불확실성·과제 표)", "",
                 *([f"_{idea['plan_at']}_", "", ideas_jev.render_plan(idea["plan"], idea["plan_paras"])]
                   if idea["plan"] else ["아직 붙여넣지 않음."]), "",
                 "## 정리본 (하위과제별 최신 결과)", ""]
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
        def heading(r: dict[str, Any]) -> str:
            title = r["subtask_title"] or ("형식 밖 결과" if r["subtask_id"] == "?" else "")
            return f"{r['subtask_id']} · {title}".rstrip(" ·")

        for sid in order:
            r = latest[sid]
            lines += [f"### {heading(r)}", f"_{r['status'] or '상태 표시 없음'} · {r['created_at']}_", "", r["body"], ""]
        if idea["materials"]:
            tasks = idea["tasks"]
            kinds = {"paste": "붙여넣기", "url": "링크", "file": "파일"}
            lines += ["## 자유 자료 (사용자가 프롬프트 없이 직접 조사해 넣은 것 · 오래된 순)", "",
                      "| # | 출처 | 받은 때 | 과제 | 제목 |", "|---|---|---|---|---|"]
            for m in reversed(idea["materials"]):
                where = f"{m['task_id']} {tasks.get(m['task_id'], {}).get('title', '')}".strip() if m["task_id"] else "자유 자료"
                lines.append(f"| {m['id']} | {m['label'].replace('|', '/')[:80]} ({kinds.get(m['kind'], m['kind'])}) "
                             f"| {m['created_at']} | {where} | {m['title'].replace('|', '/')[:60]} |")
            lines.append("")
            for m in reversed(idea["materials"]):
                where = f"{m['task_id']} ({m['assigned']})" if m["task_id"] else "과제 배정 없음 (자유 자료)"
                src = {"paste": "붙여넣은 글", "url": "링크 " + m["url"], "file": "파일 " + m["label"]}.get(m["kind"], m["kind"])
                extra = (" · " + m["note"] if m["note"] else "") + (" · 원본 " + m["file"] if m["file"] else "")
                lines += [f"### 자료 {m['id']} · {m['title']}", f"_{src} · 받은 때 {m['created_at']} · {where}{extra}_", "", m["body"], ""]
        replaced = [r for r in idea["results"] if not r["latest"]]
        if replaced:
            lines += ["## 덮어쓴 이전 결과 (최신 순)", ""]
            for r in replaced:
                lines += [f"<details><summary>{heading(r)} · {r['status'] or '상태 표시 없음'} · {r['created_at']}</summary>",
                          "", r["body"], "", "</details>", ""]
        bodies = {r["body"] for r in idea["results"]}
        if len(idea["plans"]) > 1:
            lines += ["## 이전 과제 쪼개기 (바뀌기 전, 최신 순)", ""]
            for old in idea["plans"][1:]:
                # Result blocks saved in the plan box by mistake: the same bodies are already in the results above.
                misplaced = looks_like_results(old["text"]) and all(
                    p["body"] in bodies for p in parse_results(old["text"]))
                text = "(결과 블록을 이 칸에 잘못 넣은 기록. 같은 내용이 위 결과에 있어 생략)" if misplaced else old["text"]
                lines += [f"<details><summary>{old['created_at']}</summary>", "", text, "", "</details>", ""]
        lines += ["## 붙여넣은 원문 (오래된 순 · 결과 본문은 위에 있어 블록 머리와 블록 밖 글만)", ""]
        for p in idea["pastes"]:
            sids = [r["subtask_id"] for r in reversed(idea["results"]) if r["paste_id"] == p["id"]]
            residue = paste_residue(p["raw"])
            lines += [f"<details><summary>{p['created_at']} · {len(p['raw'])}자 · 결과 {', '.join(sids) or '없음'}</summary>",
                      "", *(["```", residue, "```"] if residue else ["(블록 밖 글 없음)"]), "", "</details>", ""]
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


class PlanRequest(BaseModel):
    text: str = Field(default="", max_length=200_000)


class PasteRequest(BaseModel):
    text: str = Field(default="", max_length=500_000)
    slots: list[str] = Field(default_factory=list, max_length=20)  # one pasted result per slot, any order


class IntakeFile(BaseModel):
    name: str = Field(max_length=300)
    data: str = Field(max_length=12_000_000)  # base64


class IntakeRequest(BaseModel):
    text: str = Field(default="", max_length=ideas_intake.MAX_BODY)
    files: list[IntakeFile] = Field(default_factory=list, max_length=10)
    idea_id: str = Field(default="", max_length=40)


class AssignRequest(BaseModel):
    subtask_id: str = Field(max_length=8)


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = IdeaStore(ctx.feature_dir("ideas"), use_jev=True)
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

    @router.post("/intake")
    async def intake(body: IntakeRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        if body.idea_id:
            found(body.idea_id)
        items = await asyncio.to_thread(ideas_intake.text_items, body.text) if body.text.strip() else []
        skipped: list[str] = []
        for f in body.files:
            try:
                items.append(ideas_intake.file_item(f.name, f.data))
            except ValueError as error:
                skipped.append(str(error))
        try:
            placed = await asyncio.to_thread(store.intake, items, body.idea_id)
        except ValueError as error:
            raise HTTPException(422, "; ".join([str(error), *skipped])) from error
        return {"added": placed, "skipped": skipped}

    @router.get("/{idea_id}")
    async def idea(idea_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        return {**found(idea_id), "brief": store.brief(idea_id), "brief_path": str(store.briefs / f"{idea_id}.md")}

    @router.put("/{idea_id}/plan")
    async def plan(idea_id: str, body: PlanRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        found(idea_id)
        try:
            await asyncio.to_thread(store.set_plan, idea_id, body.text)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"ok": True}

    @router.delete("/{idea_id}", status_code=204)
    async def delete_idea(idea_id: str, _: str = Depends(ctx.current_user)) -> None:
        found(idea_id)
        store.delete_idea(idea_id)

    @router.delete("/{idea_id}/results/{result_id}", status_code=204)
    async def delete_result(idea_id: str, result_id: int, _: str = Depends(ctx.current_user)) -> None:
        if not store.delete_result(idea_id, result_id):
            raise HTTPException(404, "no such result")

    @router.post("/{idea_id}/results")
    async def results(idea_id: str, body: PasteRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        found(idea_id)
        try:
            parsed = await asyncio.to_thread(store.add_slots, idea_id, [*body.slots, *([body.text] if body.text.strip() else [])])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"added": [{"subtask_id": p["subtask_id"], "subtask_title": p["subtask_title"], "status": p["status"],
                           "claims": len(p["claims"]),
                           "assigned": p["assigned"]} for p in parsed]}

    @router.put("/{idea_id}/materials/{material_id}/subtask")
    async def assign_material(idea_id: str, material_id: int, body: AssignRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        try:
            if not store.assign_material(idea_id, material_id, body.subtask_id):
                raise HTTPException(404, "no such material")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"ok": True}

    @router.delete("/{idea_id}/materials/{material_id}", status_code=204)
    async def delete_material(idea_id: str, material_id: int, _: str = Depends(ctx.current_user)) -> None:
        if not store.delete_material(idea_id, material_id):
            raise HTTPException(404, "no such material")

    @router.post("/{idea_id}/adopt")
    async def adopt(idea_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        if not store.adopt(idea_id):
            raise HTTPException(404, "no such idea")
        return {"ok": True}

    @router.put("/{idea_id}/results/{result_id}/subtask")
    async def assign(idea_id: str, result_id: int, body: AssignRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        try:
            if not store.assign_result(idea_id, result_id, body.subtask_id):
                raise HTTPException(404, "no such result")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"ok": True}

    return router
