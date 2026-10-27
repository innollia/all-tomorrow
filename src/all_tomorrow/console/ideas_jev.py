"""Jev questions for the idea desk: sort pasted results onto tasks, fold the researcher's own opinions.

Both helpers raise jev.JevError when the call fails; the idea desk then keeps its old behaviour.
Questions are typed judgments only: which task is this result for (a Choice per pasted slot),
and is this paragraph needed to define tasks or instruct research (a Noul per paragraph). What to do
with the answers (thresholds, folding, "unsorted") is decided here in code.
"""
from __future__ import annotations

import re
from typing import Any

from all_tomorrow.console import jev

SURE = 0.7       # a Choice top option at or above this is taken as the task; below it the slot stays unsorted
DROP = 0.3       # a paragraph whose "needed" Noul is below this is folded (between DROP and 0.7 stays open)
MAX_ASKED = 150  # paragraphs asked per request; later ones stay open

HEADING_TASK = re.compile(r"^[ \t]*#{1,6}[ \t]*\**[ \t]*(S\d{1,2})[ \t]*\**[ \t]*[·:：.|\-–—][ \t]*(.+?)[ \t]*$", re.M | re.I)
TABLE_TASK = re.compile(r"^[ \t]*\|[ \t]*\**(S\d{1,2})\**[ \t]*\|[ \t]*([^|\n]+?)[ \t]*\|", re.M | re.I)
BREAKS = re.compile(r"\s+")


def plan_tasks(plan: str) -> dict[str, dict[str, str]]:
    """Tasks S1..Sn named in a decomposition answer: {id: {title, context}} in id order.
    Headings (`### S1 · title · class`) carry the section text; table rows only the title."""
    tasks: dict[str, dict[str, str]] = {}
    heads = list(HEADING_TASK.finditer(plan))
    for n, m in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else len(plan)
        section = re.sub(r"```\w*", "", plan[m.end():end]).strip()
        tasks.setdefault(m.group(1).upper(), {"title": m.group(2).split("·")[0].strip(" *`()"), "context": section[:600]})
    for m in TABLE_TASK.finditer(plan):
        tasks.setdefault(m.group(1).upper(), {"title": m.group(2).strip(" *`"), "context": ""})
    return dict(sorted(tasks.items(), key=lambda kv: int(kv[0][1:])))


def excerpt(body: str, head: int = 1500, tail: int = 500) -> str:
    body = body.strip()
    return body if len(body) <= head + tail else body[:head] + "\n…\n" + body[-tail:]


def classify_bodies(tasks: dict[str, dict[str, str]], bodies: list[str]) -> list[tuple[str, float] | None]:
    """One Choice per body ("which task is this result for?"), all in one request.
    (task id, probability) when sure, else None."""
    if not tasks or not bodies:
        return [None] * len(bodies)
    names = {sid: f"{sid} {BREAKS.sub(' ', t['title'])[:80]}".strip() for sid, t in tasks.items()}
    criteria = {names[sid]: BREAKS.sub(" ", t["context"])[:300] or t["title"] for sid, t in tasks.items()}
    questions = {f"slot{n}": {
        "type": "choice",
        "instructions": "자료조사 에이전트가 낸 아래 결과는 어느 조사 과제에 대한 결과인가?\n\n결과:\n" + excerpt(body, 1200, 300),
        "criteria": criteria} for n, body in enumerate(bodies)}
    answers = jev.ask({"조사 과제 목록": {sid: t["title"] for sid, t in tasks.items()}}, questions)
    by_name = {name: sid for sid, name in names.items()}
    out: list[tuple[str, float] | None] = []
    for n in range(len(bodies)):
        probs = (answers.get(f"slot{n}") or {}).get("probabilities") or {}
        top = max(probs, key=probs.get, default=None)
        out.append((by_name[top], float(probs[top])) if top in by_name and probs[top] >= SURE else None)
    return out


NONE = "맞는 아이디어 없음"


def choose_ideas(ideas: list[dict[str, str]], bodies: list[str]) -> list[str | None]:
    """Which existing idea does each free material belong to? One Choice per material, all in one request,
    with a "no idea fits" option. The idea id when sure (>= SURE), else None (the caller makes a new idea candidate).
    `ideas` = [{id, title, text}]."""
    if not ideas or not bodies:
        return [None] * len(bodies)
    names = {i["id"]: f"{i['id']} {BREAKS.sub(' ', i['title'])[:60]}".strip() for i in ideas}
    criteria = {names[i["id"]]: BREAKS.sub(" ", i["text"])[:300] or i["title"] for i in ideas}
    criteria[NONE] = "아래 자료는 위 아이디어들 중 어느 것의 조사에도 쓰이지 않는다. 다른 주제다."
    questions = {f"item{n}": {
        "type": "choice",
        "instructions": "사용자가 직접 조사해 모은 아래 자료는 어느 아이디어를 위한 것인가?\n\n자료:\n" + excerpt(body, 1200, 300),
        "criteria": criteria} for n, body in enumerate(bodies)}
    answers = jev.ask({"아이디어 목록": {i["id"]: i["title"] for i in ideas}}, questions)
    by_name = {name: iid for iid, name in names.items()}
    out: list[str | None] = []
    for n in range(len(bodies)):
        probs = (answers.get(f"item{n}") or {}).get("probabilities") or {}
        top = max(probs, key=probs.get, default=None)
        out.append(by_name[top] if top in by_name and probs[top] >= SURE else None)
    return out


def split_paragraphs(text: str) -> list[dict[str, Any]]:
    """Blank-line paragraphs; a fenced block (a sub-prompt) is one paragraph and is never asked about.
    `ask` marks prose worth a question: not a heading, table row or a few words."""
    paras: list[dict[str, Any]] = []
    cur: list[str] = []
    fenced = False
    block_is_fence = False

    def flush() -> None:
        chunk = "\n".join(cur).strip("\n")
        if chunk.strip():
            paras.append({"text": chunk, "ask": not block_is_fence and chunk.lstrip()[0] not in "#|" and len(chunk.strip()) >= 30})
        cur.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            if not fenced:
                flush()
                block_is_fence = True
            cur.append(line)
            fenced = not fenced
            if not fenced:
                flush()
                block_is_fence = False
        elif not fenced and not line.strip():
            flush()
        else:
            cur.append(line)
    flush()
    return paras


def judge_paragraphs(idea_title: str, idea_text: str, plan: str) -> list[dict[str, Any]]:
    """Paragraphs of a decomposition answer as {text, p, keep}: p = Jev's probability that the paragraph is
    needed to define tasks or instruct the research (not the researcher's own opinion or chatter), None
    when it was not asked. [] when there is nothing to ask."""
    paras = split_paragraphs(plan)
    asked = [n for n, p in enumerate(paras) if p["ask"]][:MAX_ASKED]
    if not asked:
        return []
    questions = {f"p{n}": {
        "type": "noul",
        "instructions": "아래 문단은 조사 과제의 정의나 조사 지시에 필요한 내용인가?\n\n문단:\n" + paras[n]["text"][:1500],
        "criteria": {
            "true": "아이디어 분석, 핵심 불확실성, 과제 목록·목적·범위·제외·출처 기준·산출물·분류, 하위 프롬프트 작성 방법처럼 과제를 정의하거나 조사를 지시하는 글.",
            "false": "자료조사 에이전트가 자기 생각·감상·칭찬·인사·마무리 제안·일반론·잡담을 늘어놓은 글로, 과제 정의나 조사 지시에는 쓰이지 않는다."}}
        for n in asked}
    answers = jev.ask({"아이디어": {"제목": idea_title, "원문": idea_text[:2000]}}, questions)
    out = []
    for n, para in enumerate(paras):
        prob = (answers.get(f"p{n}") or {}).get("noul") if n in asked else None
        out.append({"text": para["text"], "p": prob, "keep": prob is None or float(prob) >= DROP})
    return out


def render_plan(plan: str, paras: list[dict[str, Any]]) -> str:
    """The plan for the brief: filtered paragraphs folded in <details>, never dropped."""
    if not paras or all(p["keep"] for p in paras):
        return plan
    parts = []
    for p in paras:
        if p["keep"]:
            parts.append(p["text"])
        else:
            first = BREAKS.sub(" ", p["text"]).strip()[:40].replace("<", "&lt;")
            parts.append(f"<details><summary>접음: 과제 정의·조사 지시가 아닌 글로 걸러짐 (p={p['p']:.2f}) · {first}…</summary>"
                         f"\n\n{p['text']}\n\n</details>")
    return "\n\n".join(parts)
