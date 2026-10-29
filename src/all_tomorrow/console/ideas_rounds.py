"""아이디어 조사 '바퀴': 종합본 → 빈 곳으로 다음 자료봉 프롬프트 → 사용자가 돌려 붙여 넣음 → 압축·재종합 → 다시.

모델을 따로 부르지 않는다. 다음 바퀴 질문은 종합본의 '빈 곳'(모르는 것), '어긋나는 주장'(충돌), '(추정)' 주장(근거 약함)에서
그대로 뽑는다. 붙여 넣은 결과는 '바퀴 n 결과' 자유 자료가 되어 평소처럼 Codex가 압축하고, 이전 종합본 + 새 압축본으로
다시 종합한다(IdeaStore.synth_job). 바퀴 기록(물은 것·새로 나온 것·바뀐 결론)은 열 때마다 저장된 것에서 다시 계산한다.
바퀴 수 상한은 없다.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

LABEL = "바퀴 {n} 결과"
LOW_NEW = 3   # 한 바퀴에서 새로 더해진 항목이 이보다 적으면 '더 돌릴 필요 낮음'
KINDS = (("빈 곳", "모름"), ("어긋나는 주장", "충돌"))
CHANGE_SECTIONS = ("한 줄 결론", "정해진 것", "질문별 답", "어긋나는 주장", "빈 곳")

PROMPT = """너는 사업 아이디어 조사 담당이다. 아래 [아이디어]는 이미 여러 번 조사됐다. 이번에는 [이번 질문] 하나만 웹 검색으로 조사해 한국어로 답한다.

## 규칙
- 되묻지 말고 가장 그럴듯한 해석으로 끝까지 조사한다. 이 대화에서 PC나 파일은 볼 수 없고 웹은 볼 수 있다.
- [정해진 것]은 사용자가 이미 정했다. 그것을 바꾸라고 권하지 않는다. 찾은 사실이 그것과 부딪치면 그 사실만 '정해진 것과 부딪침'에 적는다.
- 주장마다 출처 URL과 기준 시점을 붙이고, 확인과 추정을 나눈다. 못 찾으면 못 찾았다고 적는다(시도한 검색어).
- 찾은 사실만 쓴다. 평가·권고·우선순위는 쓰지 않는다. 인사·맺음말 없이 아래 형식으로만 답한다.

## 답의 형식
바퀴 {n} · {qid} · {kind}
## 한 줄 결론
## 찾은 것
## 정해진 것과 부딪침
(없으면 "없음")
## 여전히 모르는 것

[이번 질문] ({kind})
{topic}

[정해진 것]
{decided}

[아이디어]
제목: {title} ({idea_id})
{text}
"""


def section(synth: str, name: str) -> str:
    m = re.search(rf"^#{{1,6}}\s*{re.escape(name)}[^\n]*\n(.*?)(?=^#{{1,6}}\s|\Z)", synth, re.S | re.M)
    return m.group(1).strip() if m else ""


def bullets(text: str) -> list[str]:
    """Top-level '- ' items, with their indented continuation lines folded in."""
    items: list[str] = []
    for line in text.splitlines():
        if re.match(r"^[-*]\s+", line):
            items.append(re.sub(r"^[-*]\s+", "", line).strip())
        elif items and line.strip() and line[:1].isspace():
            items[-1] += " " + line.strip()
    return [i for i in items if i and i not in ("없음", "없음.")]


def gaps(synth: str) -> list[dict[str, str]]:
    """What the next round asks: unknowns, conflicts and claims the synthesis marks as estimates."""
    out = [{"kind": kind, "topic": b} for name, kind in KINDS for b in bullets(section(synth, name))]
    out += [{"kind": "근거 약함", "topic": b} for b in bullets(section(synth, "주장")) if re.search(r"\(추정\)\s*$", b)]
    for n, g in enumerate(out, 1):
        g["qid"] = f"Q{n}"
    return out


def prompt(idea: dict[str, Any], n: int, gap: dict[str, str]) -> str:
    decided = section(idea["synth"], "정해진 것") or "없음"
    text = idea["text"].strip()
    return PROMPT.format(n=n, qid=gap["qid"], kind=gap["kind"], topic=gap["topic"], decided=decided, title=idea["title"],
                         idea_id=idea["id"], text=text if len(text) <= 3000 else text[:3000].rstrip() + " …")


def new_items(summary: str) -> int:
    return len(bullets(section(summary, "새로 더해진 것")))


def changes(before: str, after: str) -> list[dict[str, Any]]:
    """Per synthesis section: lines that left and lines that came, ignoring the [R…, M…] source tags."""
    plain = lambda s: re.sub(r"\s*\[[^\]]*\]\s*", " ", s).strip()
    out = []
    for name in CHANGE_SECTIONS:
        old, new = bullets(section(before, name)) or [section(before, name)], bullets(section(after, name)) or [section(after, name)]
        po, pn = {plain(x) for x in old if x}, {plain(x) for x in new if x}
        gone, came = [x for x in old if x and plain(x) not in pn], [x for x in new if x and plain(x) not in po]
        if gone or came:
            out.append({"section": name, "gone": gone, "came": came})
    return out


def keep_decided(previous: str, text: str) -> str:
    """A new synthesis may not drop what was already decided: lines of the previous '정해진 것' that are gone are put back."""
    old = bullets(section(previous, "정해진 것"))
    plain = lambda s: re.sub(r"\s+", " ", s).strip()
    have = {plain(b) for b in bullets(section(text, "정해진 것"))}
    lost = [b for b in old if plain(b) not in have]
    if not lost:
        return text
    add = "\n".join("- " + b for b in lost)
    m = re.search(r"^#{1,6}\s*정해진 것[^\n]*\n", text, re.M)
    if not m:
        return f"## 정해진 것\n{add}\n\n" + text
    end = re.search(r"^#{1,6}\s", text[m.end():], re.M)
    at = m.end() + (end.start() if end else len(text) - m.end())
    body = text[m.end():at].rstrip()
    body = "" if body.strip() in ("없음", "없음.") else body + "\n"
    return text[:m.end()] + body + add + "\n\n" + text[at:].lstrip("\n")


def view(store: Any, idea: dict[str, Any]) -> list[dict[str, Any]]:
    """Every round of an idea, oldest first, with what it asked, what came back and what changed."""
    with store.db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM rounds WHERE idea_id = ? ORDER BY n", (idea["id"],))]
    out = []
    for k, r in enumerate(rows):
        label = LABEL.format(n=r["n"])
        mats = [m for m in idea["materials"] if m["label"] == label]
        done = bool(mats) and all(m["summary"] for m in mats)
        folded = done and all(any(s.startswith(f"M{m['id']}:") for s in idea["synth_keys"]) for m in mats)
        after = rows[k + 1]["synth_before"] if k + 1 < len(rows) else (idea["synth"] if folded else "")
        count = sum(new_items(m["summary"]) for m in mats if m["summary"])
        state = "붙여넣기 대기" if not mats else "압축 중" if not done else "통합 중" if not folded and k + 1 == len(rows) else "통합됨"
        out.append({"n": r["n"], "created_at": r["created_at"], "asked": json.loads(r["topics"]), "state": state,
                    "materials": [m["id"] for m in mats], "new": count,
                    "changed": changes(r["synth_before"], after) if after else [],
                    "low": state == "통합됨" and count < LOW_NEW})
    return out


def open_round(store: Any, idea_id: str) -> dict[str, Any]:
    idea = store.get(idea_id)
    if idea is None:
        raise LookupError(idea_id)
    if not idea["synth"]:
        raise ValueError("아직 종합본이 없다. 첫 조사 결과가 종합된 뒤에 다음 바퀴를 연다")
    rounds = view(store, idea)
    if rounds and rounds[-1]["state"] == "붙여넣기 대기":
        raise ValueError(f"바퀴 {rounds[-1]['n']}에 아직 결과를 붙여 넣지 않았다")
    found = gaps(idea["synth"])
    if not found:
        raise ValueError("종합본에 빈 곳·충돌·추정 주장이 없다. 더 물을 것이 없다")
    n = (rounds[-1]["n"] if rounds else 0) + 1
    topics = [{**g, "prompt": prompt(idea, n, g)} for g in found]
    with store.db() as db:
        db.execute("INSERT INTO rounds (idea_id, n, topics, synth_before, created_at) VALUES (?,?,?,?,?)",
                   (idea_id, n, json.dumps(topics, ensure_ascii=False), idea["synth"], datetime.now(UTC).isoformat(timespec="seconds")))
    return {"n": n, "asked": topics}


def add_results(store: Any, idea_id: str, n: int, slots: list[str]) -> list[int]:
    with store.db() as db:
        if not db.execute("SELECT 1 FROM rounds WHERE idea_id = ? AND n = ?", (idea_id, n)).fetchone():
            raise LookupError(n)
    slots = [s.strip() for s in slots if s.strip()]
    if not slots:
        raise ValueError("붙여넣은 내용이 비어 있다")
    ids = []
    for k, body in enumerate(slots, 1):
        q = re.search(r"바퀴\s*\d+\s*·\s*(Q\d+)", body)
        title = f"바퀴 {n} · {q.group(1) if q else '결과 ' + str(k)}"
        ids.append(store.add_material(idea_id, {"kind": "paste", "label": LABEL.format(n=n), "url": "", "title": title,
                                                "body": body, "note": f"조사 바퀴 {n}"}))
    store.write_brief(idea_id)
    return ids

