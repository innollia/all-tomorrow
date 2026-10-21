from all_tomorrow.overseer import brief
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore


def test_brief_lists_projects_activity_and_notion(tmp_path) -> None:
    store = SessionStore(tmp_path / "o.sqlite")
    s = Session("codex", "c1", cwd="C:\\projects\\web", title="빌드", updated_at="2099-01-01T00:00:00")
    s.lines = ["[U] 빌드 실패"]
    store.put(s, "fp", lambda t: t)
    store.commit()
    projects = {"projects": [{"name": "web", "git": {"branch": "main", "last_commit": "2099-01-01",
                                                     "last_subject": "fix", "commits_30d": 3, "dirty_files": 0}}]}
    text = brief.render(store.con, projects, {"진행 중인 목표": {"text": "게임 데모 완성"}})
    assert "### web" in text and "codex 1" in text and "빌드" in text and "게임 데모 완성" in text
    assert "신탁" not in text
