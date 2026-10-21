"""The oracle button: a stuck session asks whether the problem was solved elsewhere.

Answers come from the distilled cards by full-text search only — no model call —
so asking is free and instant. The asking agent judges whether a card applies.
Every question is logged with the cards it got, so later distillation can tell
whether the answer was used.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

MAX_TERMS = 24
_TERM = re.compile(r"[0-9A-Za-z_\-]{3,}|[가-힣]{3,}")
_PARTICLE = re.compile(r"(으로|에서|에게|까지|부터|이랑|하고|[이가을를은는의에로와과도만])$")

_SCHEMA = """
create virtual table if not exists cards_fts using fts5(card_id UNINDEXED, body, tokenize='trigram');
create table if not exists oracle_log (
    ask_id     text primary key,
    asked_at   text not null,
    caller     text,
    project    text,
    problem    text not null,
    card_ids   text not null
);
"""


def ensure_schema(con) -> None:
    con.executescript(_SCHEMA)


def index_session_cards(con, source: str, session_id: str) -> None:
    ensure_schema(con)
    con.execute("delete from cards_fts where card_id in "
                "(select card_id from cards where source=? and session_id=?)", (source, session_id))
    con.execute("insert into cards_fts (card_id, body) select card_id, "
                "problem || ' ' || coalesce(situation,'') || ' ' || coalesce(attempts,'') || ' ' || "
                "coalesce(solution,'') from cards where source=? and session_id=?", (source, session_id))


def _query(problem: str) -> str:
    terms, seen = [], set()
    for term in _TERM.findall(problem):
        # Korean words carry particles ("오류로"); match the stem too. Trigram needs 3+ characters.
        if "가" <= term[0] <= "힣":
            term = _PARTICLE.sub("", term)
        if len(term) < 3 or term.lower() in seen:
            continue
        seen.add(term.lower())
        terms.append('"' + term.replace('"', '""') + '"')
        if len(terms) >= MAX_TERMS:
            break
    return " OR ".join(terms)


def search(con, problem: str, *, project: str | None = None, limit: int = 5, write: bool = True) -> list[dict]:
    if write:
        ensure_schema(con)
    query = _query(problem)
    if not query:
        return []
    rows = con.execute(
        "select c.card_id, c.agent, c.models, c.project, c.problem, c.attempts, c.solution, c.outcome, "
        "c.source, c.session_id, s.title, s.updated_at, bm25(cards_fts) as score "
        "from cards_fts join cards c using (card_id) left join sessions s "
        "on s.source = c.source and s.session_id = c.session_id "
        "where cards_fts match ? and c.status != 'retired' order by score limit ?",
        (query, limit * 3)).fetchall()
    cards = []
    for (card_id, agent, models, card_project, prob, attempts, solution, outcome,
         source, session_id, title, updated, score) in rows:
        cards.append({
            "card_id": card_id, "problem": prob, "solution": solution, "attempts": attempts,
            "outcome": outcome, "agent": agent, "models": json.loads(models or "[]"),
            "project": card_project, "session": f"{source}:{session_id}", "session_title": title,
            "date": (updated or "")[:10], "score": round(-score, 2)})
    # Solved cards first, then ones from other projects (the point is cross-project reuse).
    cards.sort(key=lambda c: (c["outcome"] != "해결", c["project"] == project, -c["score"]))
    return cards[:limit]


def ask(con, problem: str, *, caller: str = "", project: str | None = None, limit: int = 5,
        peers: list | None = None) -> dict:
    cards = search(con, problem, project=project, limit=limit)
    for peer in peers or []:   # another PC's published store, read-only
        try:
            cards += search(peer, problem, project=project, limit=limit, write=False)
        except Exception:
            continue
    cards.sort(key=lambda c: (c["outcome"] != "해결", c["project"] == project, -c["score"]))
    cards = cards[:limit]
    con.execute("insert into oracle_log values (?,?,?,?,?,?)",
                (uuid.uuid4().hex, datetime.now(timezone.utc).isoformat(), caller, project, problem,
                 json.dumps([c["card_id"] for c in cards])))
    con.commit()
    if not cards:
        return {"found": False, "message": "비슷한 문제를 해결한 기록이 없습니다. 직접 해결을 이어가세요.", "cards": []}
    return {"found": True,
            "message": "다른 세션의 기록입니다. 지금 상황에 맞는지 근거를 보고 판단해서 쓰세요.",
            "cards": cards}
