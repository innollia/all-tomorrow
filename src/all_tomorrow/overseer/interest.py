"""사용자 관심의 흐름: 메타인지가 읽을 사실과, 관심이 바뀔 때 메타인지 세션을 깨우는 계기.

규칙("N일이면 주제를 넣는다")은 두지 않는다. 사실만 모아 보여 주고(control-brief 2절), 관심이 바뀐 때 깨운다.
무엇을 할지는 세션이 목적(사용자가 없을 때 사용자가 원할 일을 미리 해 둔다)에서 판단한다.

- 사실: 최근 7일 사용자가 손댄 아이디어와 날짜별 활동(아이디어 만들기, 붙여 넣기, 쪼개기, 자료 넣기, 추가 조사 요청 —
  조사 실행이 넣은 자료는 사용자 활동이 아니다), 최근 만든 프로젝트 폴더와 커밋한 날, 각각에 걸린 조사 주제 수와
  마지막 조사일, 사용자가 끄거나 지운 메타인지 주제.
- 깨우는 계기: 새 프로젝트 폴더(만든 지 7일 안), 한 아이디어에 사용자 활동이 이틀 이상(최근 7일).
  지문은 metacog_session과 같이 한 번만 깨운다. 아이디어는 사흘 조용하면 지문을 지워 다음 흐름에 다시 깨운다.
  하루 상한은 metacog_session.wake가 다른 이상과 같이 센다.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DAYS = 7
QUIET_DAYS = 3
PROJECTS_ROOT = Path(os.environ.get("ALL_TOMORROW_PROJECTS_ROOT", r"C:\projects"))


def console_dir() -> Path:
    from all_tomorrow.overseer.environment import REPO
    base = Path(os.environ.get("ALL_TOMORROW_CONSOLE_DATA") or REPO / ".artifacts" / "console")
    return base if base.is_absolute() else REPO / base


def _day(stamp: str | float) -> date:
    if isinstance(stamp, (int, float)):
        return datetime.fromtimestamp(stamp).date()
    return datetime.fromisoformat(stamp).astimezone().date()


def idea_activity(console: Path, topics: list[dict], since: date) -> dict[str, dict[str, Any]]:
    """아이디어별 사용자 활동 {id: {title, days: {날짜: [무엇]}, brief}}. 조사 실행이 넣은 자료(메모에 실행 id)는 뺀다."""
    path = console / "ideas" / "ideas.sqlite"
    ideas: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return ideas
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        titles = {i: (t, s) for i, t, s in con.execute("SELECT id, title, synth_at FROM ideas")}
        events = [(i, c, "아이디어 만듦") for i, c in con.execute("SELECT id, created_at FROM ideas")]
        events += [(i, c, "결과 붙여 넣기") for i, c in con.execute("SELECT idea_id, created_at FROM pastes")]
        events += [(i, c, "쪼개기") for i, c in con.execute("SELECT idea_id, created_at FROM plans")]
        events += [(i, c, "자료 넣기") for i, c in con.execute(
            "SELECT idea_id, created_at FROM materials WHERE note NOT LIKE '%실행 RR-%'")]
    finally:
        con.close()
    events += [(t["idea_id"], t["created"], "추가 조사 요청") for t in topics
               if t.get("idea_id") and t.get("source") != "metacog" and t.get("created")]
    for idea_id, stamp, what in events:
        day = _day(stamp)
        if day < since or idea_id not in titles:
            continue
        entry = ideas.setdefault(idea_id, {"title": titles[idea_id][0], "synth_at": titles[idea_id][1],
                                           "days": defaultdict(list),
                                           "brief": str(console / "ideas" / "briefs" / f"{idea_id}.md")})
        if what not in entry["days"][day.isoformat()]:
            entry["days"][day.isoformat()].append(what)
    return ideas


def _commit_days(path: Path, since: date) -> list[str]:
    if not (path / ".git").exists():
        return []
    try:
        out = subprocess.run(["git", "-C", str(path), "log", f"--since={since.isoformat()}", "--format=%cd",
                              "--date=short"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted(set(out.split()))


def new_projects(root: Path, since: date) -> dict[str, dict[str, Any]]:
    """최근 만든 프로젝트 폴더(이름이 _나 .으로 시작하는 것은 뺀다)와 그 뒤 커밋한 날."""
    found = {}
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))]
    except OSError:
        return found
    for folder in folders:
        try:
            made = _day(folder.stat().st_ctime)
        except OSError:
            continue
        if made >= since:
            found[folder.name] = {"made": made.isoformat(), "path": str(folder), "commit_days": _commit_days(folder, since)}
    return found


def observe(now: float | None = None, *, console: Path | None = None, root: Path = PROJECTS_ROOT) -> dict[str, Any]:
    from all_tomorrow.console.research import ResearchStore, load_runs
    now = time.time() if now is None else now
    console = console or console_dir()
    since = _day(now) - timedelta(days=DAYS - 1)
    store = ResearchStore(console / "research")
    topics, runs = store.topics(), load_runs(store.folder)

    def research(match: Callable[[dict], bool]) -> dict[str, Any]:
        mine = [t for t in topics if match(t)]
        ids = {t["id"] for t in mine}
        done = [r["started"] for r in runs if r.get("topic_id") in ids and r.get("status") == "SUCCESS"]
        return {"topics": len(mine), "on": sum(t.get("enabled", True) for t in mine),
                "metacog": sum(t.get("source") == "metacog" for t in mine),
                "last": _day(max(done)).isoformat() if done else ""}

    ideas = idea_activity(console, topics, since)
    for idea_id, entry in ideas.items():
        entry["days"] = dict(sorted(entry["days"].items()))
        entry["research"] = research(lambda t, i=idea_id: t.get("idea_id") == i)
    projects = new_projects(root, since)
    for name, entry in projects.items():
        entry["research"] = research(lambda t, n=name: t.get("project_id") == n and not t.get("idea_id"))
    return {"today": _day(now).isoformat(), "ideas": ideas, "projects": projects, "declined": store.declined()}


def render(facts: dict[str, Any]) -> str:
    def research(r: dict) -> str:
        return (f"조사 주제 {r['topics']}개(켜짐 {r['on']}, 메타인지 제안 {r['metacog']}) · 마지막 조사 {r['last'] or '없음'}")
    lines = [f"최근 {DAYS}일 사용자가 손댄 아이디어:"]
    for idea_id, entry in sorted(facts["ideas"].items(), key=lambda kv: max(kv[1]["days"]), reverse=True):
        days = " / ".join(f"{d[5:]} {', '.join(w)}" for d, w in entry["days"].items())
        lines.append(f"- {idea_id} {entry['title']} · 활동한 날 {len(entry['days'])}일: {days}")
        lines.append(f"  {research(entry['research'])} · 종합 {entry['synth_at'][:10] or '아직'} · 정리본 {entry['brief']}")
    if not facts["ideas"]:
        lines.append("- 없음")
    lines.append(f"최근 {DAYS}일 새로 만든 프로젝트 폴더:")
    for name, entry in sorted(facts["projects"].items(), key=lambda kv: kv[1]["made"], reverse=True):
        commits = ", ".join(d[5:] for d in entry["commit_days"]) or "없음"
        lines.append(f"- {name} · 만든 날 {entry['made']} · 커밋한 날 {commits} · {research(entry['research'])} · {entry['path']}")
    if not facts["projects"]:
        lines.append("- 없음")
    lines.append("사용자가 끄거나 지운 메타인지 주제:")
    for d in facts["declined"][-10:]:
        target = d.get("idea_id") or d.get("project_id")
        lines.append(f"- {_day(d['at']).isoformat()} {d['how']} · {d['title']} ({target})")
    if not facts["declined"]:
        lines.append("- 없음")
    return "\n".join(lines)


def summary(now: float | None = None) -> str:
    try:
        return render(observe(now))
    except Exception as error:  # the brief must still render
        return f"관심 흐름 읽기 실패: {type(error).__name__}"


def signals(facts: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(지문, 제목, 상태) 목록. 관심이 바뀐 곳."""
    out = []
    for name, entry in facts["projects"].items():
        out.append((f"interest:project:{name}", f"새 프로젝트 {name}",
                    f"{entry['made']}에 만든 폴더 {entry['path']}, 커밋한 날 {', '.join(entry['commit_days']) or '없음'}"))
    recent = (date.fromisoformat(facts["today"]) - timedelta(days=QUIET_DAYS)).isoformat()
    for idea_id, entry in facts["ideas"].items():
        if len(entry["days"]) >= 2 and max(entry["days"]) >= recent:
            out.append((f"interest:idea:{idea_id}", f"아이디어 {idea_id} {entry['title']}에 며칠째 손댐",
                        "활동한 날 " + ", ".join(entry["days"])))
    return out


def check(base: Path, now: float | None = None, *, facts: dict | None = None, wake: Callable | None = None) -> str:
    """매시간 수집 뒤에 부른다. 관심이 바뀐 곳마다 메타인지 세션을 (지문당 한 번) 깨운다."""
    from all_tomorrow.overseer import metacog_session
    now = time.time() if now is None else now
    facts = facts or observe(now)
    wake = wake or metacog_session.wake
    found = signals(facts)
    live = {f[0] for f in found}
    # 조용해진 아이디어·오래된 프로젝트의 지문을 지운다. 아이디어는 다음 흐름에 다시 깨운다.
    metacog_session.close(base, [fp for fp in metacog_session.load_state(base).get("incidents", {})
                                 if fp.startswith("interest:") and fp not in live])
    state = metacog_session.load_state(base).get("incidents", {})
    fresh = [f for f in found if not (state.get(f[0]) or {}).get("woke")]
    if not fresh:
        return "quiet"
    # 바뀐 곳이 여럿이어도 세션은 하나만 깨운다(세션은 사실 전체를 읽는다). 나머지 지문은 같은 세션이 맡은 것으로 둔다.
    fp, title, detail = fresh[0]
    detail = "\n".join(f"- {t}: {d}" for _, t, d in fresh)
    result = wake(base, metacog_session.Incident(fingerprint=fp, source="interest", title=title, detail=detail), now=now)
    if result == "woken":
        metacog_session.mark(base, [f[0] for f in fresh[1:]], now, source="interest", title="같은 세션이 함께 봄")
    return result
