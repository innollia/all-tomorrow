"""A one-page starting digest for the overseer Claude session (optional convenience).

`python -m all_tomorrow.overseer brief` writes brief.md next to the store: each
registered project's git state, 30 days of session activity by agent, recent
unresolved problems, and the user's Notion profile digest.

It only gathers inputs. Judging anything (direction, whether the oracle helps,
which cards to keep) is the overseer's own reasoning over the raw records, not a
procedure coded here (README: no hard-coded self-improvement procedures).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())


def project_activity(con, days: int = 30) -> dict[str, dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    for project, agent, n, last in con.execute(
            "select project, source, count(*), max(updated_at) from sessions "
            "where parent_id is null and updated_at >= ? group by project, source", (since,)):
        p = out.setdefault(_norm(project), {"name": project, "agents": {}, "last": ""})
        p["agents"][agent] = n
        p["last"] = max(p["last"], last or "")
    for key, p in out.items():
        p["recent_titles"] = [t for (t,) in con.execute(
            "select title from sessions where parent_id is null and title != '' and updated_at >= ? "
            "and project = ? order by updated_at desc limit 5", (since, p["name"]))]
    return out


def open_problems(con, project: str, limit: int = 3) -> list[str]:
    try:
        rows = con.execute("select problem from cards where outcome = '미해결' and project = ? "
                           "order by created_at desc limit ?", (project, limit)).fetchall()
    except Exception:  # cards table not created yet
        return []
    return [r[0] for r in rows]


def render(con, projects: dict | None, notion: dict | None) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    out = [f"# 관제 브리핑 ({now})", ""]
    activity = project_activity(con)
    out += ["## 프로젝트", ""]
    seen = set()
    for p in (projects or {}).get("projects", []):
        key = _norm(p.get("name") or p.get("id"))
        seen.add(key)
        act = activity.get(key, {})
        git = p.get("git") or {}
        agents = ", ".join(f"{a} {n}" for a, n in sorted(act.get("agents", {}).items())) or "없음"
        out.append(f"### {p.get('name')}")
        out.append(f"- git: {git.get('branch', '-')} · 마지막 커밋 {git.get('last_commit', '-')} "
                   f"\"{git.get('last_subject', '')}\" · 30일 커밋 {git.get('commits_30d', '-')} · "
                   f"미커밋 파일 {git.get('dirty_files', '-')}")
        out.append(f"- 30일 세션: {agents} · 마지막 세션 {act.get('last', '')[:10] or '-'}")
        if act.get("recent_titles"):
            out.append("- 최근 세션: " + " / ".join(act["recent_titles"]))
        problems = open_problems(con, act.get("name") or p.get("name"))
        if problems:
            out.append("- 풀리지 않은 문제: " + " / ".join(x[:120] for x in problems))
        out.append("")
    others = [(k, v) for k, v in activity.items() if k not in seen and k]
    if others:
        out += ["### 등록 안 된 작업 폴더 (30일 세션)", ""]
        for _, v in sorted(others, key=lambda kv: kv[1]["last"], reverse=True)[:12]:
            agents = ", ".join(f"{a} {n}" for a, n in sorted(v["agents"].items()))
            out.append(f"- {v['name']}: {agents} · 마지막 {v['last'][:10]}")
        out.append("")

    out += ["## 노션 (사용자 프로필)", ""]
    if not notion:
        out.append("- 읽지 못함")
    for name, item in (notion or {}).items():
        out.append(f"### {name}")
        out.append(item.get("text") or f"(비어 있음{', 오류 ' + item['error'] if item.get('error') else ''})")
        out.append("")
    return "\n".join(out)


def load_projects() -> dict | None:
    try:
        from all_tomorrow import projects_snapshot
        return projects_snapshot.collect()
    except Exception:
        return None


def load_notion() -> dict | None:
    try:
        from all_tomorrow.idea_factory import profile
        from all_tomorrow.idea_factory.config import export_secrets_to_env, load_roster
        export_secrets_to_env()
        return profile.fetch_profile(load_roster().profile_sources)
    except Exception:
        return None
