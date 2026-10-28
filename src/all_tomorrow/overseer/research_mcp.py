"""메타인지 세션의 조사 목록 도구(stdio MCP). 콘솔 '조사 목록'(console/research.py)과 같은 agenda.json을 쓴다.

메타인지가 넣은 주제는 출처 '메타인지'와 근거(reason), 연결 대상(idea_id·project_id)을 달고 들어가 콘솔에
'메타인지 제안'으로 보인다. 사용자가 끄거나 지운 메타인지 주제는 다시 넣거나 켜지 못한다(ResearchStore가 막는다).
"""
from __future__ import annotations

from typing import Any

from all_tomorrow.console.research import ResearchStore, load_runs, research_dir


def _store() -> ResearchStore:
    return ResearchStore(research_dir())


def list_topics() -> dict[str, Any]:
    store = _store()
    runs = load_runs(store.folder)
    topics = []
    for topic in store.topics():
        mine = [r for r in runs if r.get("topic_id") == topic["id"]]
        last = mine[-1] if mine else {}
        topics.append({k: topic.get(k) for k in ("id", "title", "ask", "project_id", "idea_id", "repeat_days",
                                                 "enabled", "source", "reason")}
                      | {"runs": len(mine), "last_status": last.get("status"), "last_started": last.get("started")})
    return {"topics": topics, "declined_by_user": store.declined()}


def add_topic(title: str, ask: str, reason: str, idea_id: str = "", project_id: str = "all-tomorrow",
              repeat_days: float = 0) -> dict[str, Any]:
    return _store().suggest(title, ask, reason, idea_id=idea_id, project_id=project_id, repeat_days=repeat_days)


def update_topic(topic_id: str, title: str | None = None, ask: str | None = None, reason: str | None = None,
                 repeat_days: float | None = None, project_id: str | None = None) -> dict[str, Any]:
    return _store().revise(topic_id, title=title, ask=ask, reason=reason, repeat_days=repeat_days, project_id=project_id)


def main() -> None:
    from fastmcp import FastMCP
    mcp = FastMCP("research")

    @mcp.tool
    def list_research_topics() -> dict[str, Any]:
        """조사 목록 전체(출처 source="metacog"이면 메타인지 제안, 실행 횟수·마지막 상태)와 사용자가 끄거나 지운 메타인지 주제."""
        return list_topics()

    @mcp.tool
    def add_research_topic(title: str, ask: str, reason: str, idea_id: str = "", project_id: str = "all-tomorrow",
                           repeat_days: float = 0) -> dict[str, Any]:
        """놀 때 Codex가 조사할 주제를 조사 목록 맨 아래에 넣는다. reason: 사용자가 보게 될 근거(어떤 관심·빈 곳 때문인지).
        idea_id를 주면 그 아이디어의 맥락을 붙여 조사하고 결과가 그 아이디어의 자료로 들어간다."""
        return add_topic(title, ask, reason, idea_id, project_id, repeat_days)

    @mcp.tool
    def update_research_topic(topic_id: str, title: str | None = None, ask: str | None = None,
                              reason: str | None = None, repeat_days: float | None = None,
                              project_id: str | None = None) -> dict[str, Any]:
        """메타인지가 넣은 주제를 고친다(project_id를 바꾸면 Codex가 그 프로젝트 폴더에서 조사한다).
        사용자가 넣은 주제와 사용자가 끈 주제는 고칠 수 없다."""
        return update_topic(topic_id, title, ask, reason, repeat_days, project_id)

    mcp.run()


if __name__ == "__main__":
    main()
