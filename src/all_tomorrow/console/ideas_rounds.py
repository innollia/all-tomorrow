"""아이디어 조사 '바퀴': 종합본 → 빈 곳으로 다음 자료봉 프롬프트 → 사용자가 돌려 붙여 넣음 → 압축·재종합 → 다시.

다음 바퀴 후보는 종합본의 '빈 곳'(모르는 것), '어긋나는 주장'(충돌), '(추정)' 주장(근거 약함)에서 그대로 뽑고,
각 후보가 어떻게 답을 얻는지 가른다(route): 웹 조사 / 사용자에게 묻기(본인 신상·본인이 정할 것) / 직접 확인(이 PC에서
만들고 돌려 봐야 나오는 것). 웹 조사만 자료봉 프롬프트가 되고, 나머지는 화면에서 사용자에게 묻는다. 그 답은
IdeaStore.grounds로 종합의 '정해진 것' 근거가 된다. 붙여 넣은 결과는 '바퀴 n 결과' 자유 자료가 되어 평소처럼 Codex가 압축하고, 이전 종합본 + 새 압축본으로
다시 종합한다(IdeaStore.synth_job). 바퀴 기록(물은 것·새로 나온 것·바뀐 결론)은 열 때마다 저장된 것에서 다시 계산한다.
바퀴 수 상한은 없다.

사용자가 직접 더 알고 싶은 것은 바퀴가 아니라 '추가 조사'(extras)다: 추가 조사 칸(ideas.asks) → 쪼개기 프롬프트 → 자료봉이 과제 S{n}…로
나눈다 → 사용자가 병렬로 돌린다 → 처음 쪼개기와 같은 과제·결과로 저장되어 압축·종합된다. 사용자가 물은 말은 asked로 종합까지 가서
'질문별 답'에 물음마다 답이 남는다.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from all_tomorrow.console import ideas_followup, jev

LABEL = "바퀴 {n} 결과"
LOW_NEW = 3   # 한 바퀴에서 새로 더해진 항목이 이보다 적으면 '더 돌릴 필요 낮음'
KINDS = (("빈 곳", "모름"), ("어긋나는 주장", "충돌"))
MINE = "내 질문"
WEB, USER, LOCAL = "web", "user", "local"
ROUTE_NAMES = {WEB: "웹 조사", USER: "사용자에게 묻기", LOCAL: "직접 확인"}
SURE = 0.5   # Jev's top route at or above this is taken; below it the rules below decide
# Only the user knows these: who they are, what they meant, what they will pick. Checked before Jev: a web prompt about
# the founder's age or nationality is what this module must never make.
USER_RE = re.compile(r"나이|국적|사업자\s*형태|개발자\s*본인|본인의|사용자\s*구상|재사용하려던|원래\s*쓰려던|사용자가\s*정")
# Only running it here answers these: builds, runs, measurements, playtests of our own thing.
LOCAL_RE = re.compile(r"실제\s*(?:Studio\s*)?실행|실행·빌드|실행\s*검증|검증\s*결과가\s*없|실측|측정하지|플레이\s*테스트|실행하지\s*않았")
ROUTE_CRITERIA = {
    ROUTE_NAMES[WEB]: "공개된 사실(시장·경쟁작·가격·약관·법·기술 문서·사례·통계)을 웹 검색으로 찾아 답할 수 있다.",
    ROUTE_NAMES[USER]: "아이디어를 낸 사용자 본인만 알거나 정할 수 있다: 본인의 나이·국적·사업자 형태, 사용자가 무엇을 뜻했는지, "
                       "원래 쓰려던 저장소·자료, 대상 국가·연령·가격·규칙 같은 사용자가 정할 선택, 원문 구상과 조사 결과가 부딪칠 때 어느 쪽으로 갈지.",
    ROUTE_NAMES[LOCAL]: "웹에는 답이 없고 사용자가 이 PC에서 직접 만들고 실행·빌드·측정·플레이테스트해야 나오는 결과, "
                        "또는 우리 조사 기록끼리의 숫자·표기 불일치를 맞추는 일.",
}
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


def rule_route(topic: str) -> str:
    return USER if USER_RE.search(topic) else LOCAL if LOCAL_RE.search(topic) else WEB


def route(store: Any, idea: dict[str, Any], found: list[dict[str, str]]) -> list[str]:
    """How each candidate gets its answer: WEB, USER or LOCAL. The user rule first, then Jev (one Choice per candidate,
    all in one request) when the store has Jev on and is sure, else the rules."""
    picks: dict[int, str] = {}
    if store.use_jev and found:
        names = {v: k for k, v in ROUTE_NAMES.items()}
        questions = {f"g{n}": {"type": "choice", "criteria": ROUTE_CRITERIA,
                               "instructions": f"사업 아이디어 조사의 다음 바퀴 후보 항목이다. 이 항목은 어떻게 답을 얻는가?\n\n항목 ({g['kind']}):\n{g['topic'][:1200]}"}
                     for n, g in enumerate(found)}
        try:
            answers = jev.ask({"아이디어": {"제목": idea["title"], "원문": idea["text"][:1500]}}, questions)
        except jev.JevError:
            answers = {}
        for n in range(len(found)):
            probs = (answers.get(f"g{n}") or {}).get("probabilities") or {}
            top = max(probs, key=probs.get, default=None)
            if top in names and probs[top] >= SURE:
                picks[n] = names[top]
    return [USER if USER_RE.search(g["topic"]) else picks.get(n) or rule_route(g["topic"]) for n, g in enumerate(found)]


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
        answers = {(a["n"], a["qid"]): a["answer"] for a in db.execute("SELECT * FROM round_answers WHERE idea_id = ?", (idea["id"],))}
    out = []
    for k, r in enumerate(rows):
        label = LABEL.format(n=r["n"])
        mats = [m for m in idea["materials"] if m["label"] == label]
        done = bool(mats) and all(m["summary"] for m in mats)
        folded = done and all(any(s.startswith(f"M{m['id']}:") for s in idea["synth_keys"]) for m in mats)
        after = rows[k + 1]["synth_before"] if k + 1 < len(rows) else (idea["synth"] if folded else "")
        count = sum(new_items(m["summary"]) for m in mats if m["summary"])
        asked = [{"to": WEB, **q} for q in json.loads(r["topics"])]   # rounds from before routing asked the web only
        # A round with nothing for the web does not wait for a paste.
        state = ("붙여넣기 대기" if any(q["to"] == WEB for q in asked) else "물음만") if not mats else \
            "압축 중" if not done else "통합 중" if not folded and k + 1 == len(rows) else "통합됨"
        for q in asked:
            if q["to"] != WEB:
                q["answer"] = answers.get((r["n"], q["qid"]), "")
        out.append({"n": r["n"], "created_at": r["created_at"], "asked": asked, "state": state,
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
    with store.db() as db:   # what the user already answered is not asked again
        answered = {a["topic"] for a in db.execute("SELECT topic FROM round_answers WHERE idea_id = ? AND answer != ''", (idea_id,))}
    found = [{**g, "to": to} for g, to in zip(found, route(store, idea, found)) if not (to != WEB and g["topic"] in answered)]
    n = (rounds[-1]["n"] if rounds else 0) + 1
    if not found:
        raise ValueError("종합본에 빈 곳·충돌·추정 주장이 없다. 더 물을 것이 없다")
    topics = []
    for k, g in enumerate(found, 1):
        g = {**g, "qid": f"Q{k}"}
        topics.append({**g, "prompt": prompt(idea, n, g)} if g["to"] == WEB else g)
    with store.db() as db:
        db.execute("INSERT INTO rounds (idea_id, n, topics, synth_before, created_at) VALUES (?,?,?,?,?)",
                   (idea_id, n, json.dumps(topics, ensure_ascii=False), idea["synth"], datetime.now(UTC).isoformat(timespec="seconds")))
    return {"n": n, "asked": topics}


def set_asks(store: Any, idea_id: str, text: str) -> None:
    """What the user wants researched next, as typed (one per line). Saved as they type."""
    with store.db() as db:
        if not db.execute("UPDATE ideas SET asks = ? WHERE id = ?", (text, idea_id)).rowcount:
            raise LookupError(idea_id)


def set_answer(store: Any, idea_id: str, n: int, qid: str, answer: str) -> None:
    """The user's answer to a question put to them; IdeaStore.grounds reads it as something the user decided."""
    with store.db() as db:
        row = db.execute("SELECT topics FROM rounds WHERE idea_id = ? AND n = ?", (idea_id, n)).fetchone()
        q = next((q for q in json.loads(row["topics"]) if q["qid"] == qid and q.get("to", WEB) != WEB), None) if row else None
        if q is None:
            raise LookupError(qid)
        db.execute("""INSERT INTO round_answers (idea_id, n, qid, topic, answer, updated_at) VALUES (?,?,?,?,?,?)
                      ON CONFLICT(idea_id, n, qid) DO UPDATE SET answer = excluded.answer, updated_at = excluded.updated_at""",
                   (idea_id, n, qid, q["topic"], answer.strip(), datetime.now(UTC).isoformat(timespec="seconds")))


def add_results(store: Any, idea_id: str, n: int, slots: list[str]) -> list[int]:
    with store.db() as db:
        row = db.execute("SELECT topics FROM rounds WHERE idea_id = ? AND n = ?", (idea_id, n)).fetchone()
    if row is None:
        raise LookupError(n)
    slots = [s.strip() for s in slots if s.strip()]
    if not slots:
        raise ValueError("붙여넣은 내용이 비어 있다")
    topics = {q["qid"]: q["topic"] for q in json.loads(row["topics"])}
    ids = []
    for k, body in enumerate(slots, 1):
        q = re.search(r"바퀴\s*\d+\s*·\s*(Q\d+)", body)
        title = f"바퀴 {n} · {q.group(1) if q else '결과 ' + str(k)}"
        topic = topics.get(q.group(1), "") if q else ""   # the compression answers this question, the answer rarely repeats it
        ids.append(store.add_material(idea_id, {"kind": "paste", "label": LABEL.format(n=n), "url": "", "title": title,
                                                "body": body, "note": f"조사 바퀴 {n}" + (f" · 물음: {topic[:500]}" if topic else "")}))
    store.write_brief(idea_id)
    return ids


def asked(db: Any, idea_id: str) -> list[str]:
    """Everything the user asked to have researched, with where the answer is, for the synthesis to answer one by one."""
    out = []
    for e in db.execute("SELECT * FROM extras WHERE idea_id = ? ORDER BY n", (idea_id,)):
        out += [f"- {q} [과제 S{e['start']}부터]" for q in json.loads(e["questions"])]
    for r in db.execute("SELECT n, topics FROM rounds WHERE idea_id = ? ORDER BY n", (idea_id,)).fetchall():
        for q in json.loads(r["topics"]):
            mats = db.execute("SELECT id FROM materials WHERE idea_id = ? AND title = ?", (idea_id, f"바퀴 {r['n']} · {q['qid']}")).fetchall()
            if q["kind"] == MINE and mats:
                out.append(f"- {q['topic']} [{', '.join('M' + str(m['id']) for m in mats)}]")
    for m in db.execute("SELECT id, note FROM materials WHERE idea_id = ? AND label = ? ORDER BY id", (idea_id, ideas_followup.LABEL)):
        out.append(f"- {re.sub(r'^요청 원문: | · 실행 .*$', '', m['note'])} [M{m['id']}]")
    return out


def task_ids(idea: dict[str, Any]) -> dict[str, str]:
    """Every task of an idea, from the plan and from results: {S6: title}."""
    tasks = {sid: t["title"] for sid, t in idea["tasks"].items()}
    for r in idea["results"]:
        if r["subtask_id"][1:].isdigit():
            tasks[r["subtask_id"]] = tasks.get(r["subtask_id"]) or r["subtask_title"]
    return tasks


def _job(job: dict[str, Any]) -> dict[str, Any]:
    return {"worker": job["worker"], "model": job["model"], "status": job["status"], "error": job["error"],
            "active": job["status"] in ("WAIT", "RUNNING")}


def extras(store: Any, idea: dict[str, Any]) -> list[dict[str, Any]]:
    """Every 추가 조사 of an idea, oldest first: its questions, its tasks and how far they got."""
    with store.db() as db:
        rows = [dict(e) for e in db.execute("SELECT * FROM extras WHERE idea_id = ? ORDER BY n", (idea["id"],))]
        jobs = [dict(j) for j in db.execute("SELECT * FROM extra_jobs WHERE idea_id = ? ORDER BY id", (idea["id"],))]
    known, latest = task_ids(idea), {r["subtask_id"]: r for r in idea["results"] if r["latest"]}
    out = []
    for k, e in enumerate(rows):
        stop = rows[k + 1]["start"] if k + 1 < len(rows) else 100
        ids = sorted((s for s in known if e["start"] <= int(s[1:]) < stop), key=lambda s: int(s[1:]))
        got = [latest[s] for s in ids if s in latest]
        folded = bool(got) and len(got) == len(ids) and all(any(s.startswith(f"R{r['id']}:") for s in idea["synth_keys"]) for r in got)
        ran = {j["task"]: _job(j) for j in jobs if j["n"] == e["n"]}   # the last run of each task
        split = ran.get("")
        state = ("쪼개는 중" if split and split["active"] else "쪼개기 실패" if split and split["status"] == "FAILED" else "쪼개기 답 대기") if not ids \
            else "조사 중" if any(ran.get(s, {}).get("active") for s in ids) else "결과 대기" if len(got) < len(ids) \
            else "압축 중" if not all(r["summary"] for r in got) else "통합됨" if folded else "통합 중"
        after = rows[k + 1]["synth_before"] if k + 1 < len(rows) else (idea["synth"] if folded else "")
        out.append({"n": e["n"], "start": e["start"], "created_at": e["created_at"], "questions": json.loads(e["questions"]), "prompt": e["prompt"],
                    "state": state, "split": split, "tasks": [{"id": s, "title": known[s], "done": s in latest, "job": ran.get(s)} for s in ids],
                    "changed": changes(e["synth_before"], after) if e["synth_before"] and after else []})
    return out


def open_extra(store: Any, idea_id: str, text: str) -> dict[str, Any]:
    """Turn the questions in the 추가 조사 box into a decomposition prompt. A split still waiting for its answer takes them in."""
    idea = store.get(idea_id)
    if idea is None:
        raise LookupError(idea_id)
    lines = [q for q in (x.strip(" -*\t") for x in text.splitlines()) if q]
    done = extras(store, idea)
    open_one = done[-1] if done and not done[-1]["tasks"] else None
    if not lines and not open_one:
        raise ValueError("조사할 질문을 한 줄 적는다")
    questions = [*(open_one["questions"] if open_one else []), *lines]
    start = open_one["start"] if open_one else max((int(s[1:]) for s in task_ids(idea)), default=0) + 1
    n = open_one["n"] if open_one else (done[-1]["n"] if done else 0) + 1
    prompt = ideas_followup.split_prompt(idea, questions, start)
    with store.db() as db:
        db.execute("""INSERT INTO extras (idea_id, n, questions, start, prompt, synth_before, created_at) VALUES (?,?,?,?,?,?,?)
                      ON CONFLICT(idea_id, n) DO UPDATE SET questions = excluded.questions, prompt = excluded.prompt""",
                   (idea_id, n, json.dumps(questions, ensure_ascii=False), start, prompt, idea["synth"], datetime.now(UTC).isoformat(timespec="seconds")))
        db.execute("UPDATE ideas SET asks = '' WHERE id = ?", (idea_id,))
    return {"n": n, "start": start, "questions": questions, "prompt": prompt}

def run_extra(store: Any, idea_id: str, n: int, worker: str, model: str) -> dict[str, Any]:
    """Queue what an 추가 조사 still needs for overseer.direct_research: its decomposition, or every task without a result."""
    from all_tomorrow.overseer.direct_research import WORKERS, task_worker
    if worker not in WORKERS:
        raise ValueError("CLI는 " + ", ".join(WORKERS))
    idea = store.get(idea_id)
    extra = next((x for x in extras(store, idea) if x["n"] == n), None)
    if extra is None:
        raise ValueError("그런 추가 조사가 없다")
    if extra["split"] and extra["split"]["active"]:
        raise ValueError("쪼개는 중이다. 끝나면 과제가 알아서 돈다")
    tasks = [t["id"] for t in extra["tasks"] if not t["done"] and not (t["job"] and t["job"]["active"])] if extra["tasks"] else [""]
    if not tasks:
        raise ValueError("돌릴 과제가 없다")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with store.db() as db:
        for task in tasks:
            db.execute("INSERT INTO extra_jobs (idea_id, n, task, worker, model, status, created_at) VALUES (?,?,?,?,?,'WAIT',?)",
                       (idea_id, n, task, task_worker(worker, task), model, now))
    return {"n": n, "tasks": tasks}


def run_new(store: Any, idea_id: str, text: str, worker: str, model: str) -> dict[str, Any]:
    """The 바로 조사 button: the questions in the box become an 추가 조사 and the chosen model starts on it."""
    last = extras(store, store.get(idea_id))[-1:]
    if last and last[0]["split"] and last[0]["split"]["active"]:
        raise ValueError("쪼개는 중이다. 끝난 뒤에 다시 누른다")
    return run_extra(store, idea_id, open_extra(store, idea_id, text)["n"], worker, model)
