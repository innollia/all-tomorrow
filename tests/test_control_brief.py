import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from all_tomorrow.overseer import control_brief as cb, discord_digest as dd
from all_tomorrow.overseer.discord_edge import MessageBatch
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.store import SessionStore
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl


def message(id="123", **kwargs):
    return dict(message_id=id, guild_id="1", guild_name="서버", channel_id="2", channel_name="개발",
                thread_id=None, author_id="870314156350402591", author_name="형님", author_is_bot=False,
                created_at="2026-10-22T03:00:00Z", content="금요일까지 게임 완성. 마음이 놓인다", reply_to=None) | kwargs


def batch(*messages):
    return MessageBatch.model_validate(dict(source="eve", batch_id="batch", messages=list(messages)))


def test_messages_auth_dedup_persistence_and_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path))
    monkeypatch.delenv("DISCORD_OWNER_USER_ID", raising=False)  # collection isn't owner-only
    app = create_app(auth=Auth("owner", "password", "s" * 32, edge_token="edge-secret"),
                     control=WebControl(InMemoryGoalWorkRunStore()))
    headers = {"Authorization": "Bearer edge-secret"}
    body = dict(source="eve", batch_id="b", messages=[message()])
    with TestClient(app) as client:
        url = "/internal/edge/discord/messages"
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, headers={"Authorization": "Bearer bad"}, json=body).status_code == 401
        assert client.post(url, headers=headers, json=body).json() == {"accepted": 1, "duplicates": 0}
        assert client.post(url, headers=headers, json=body).json() == {"accepted": 0, "duplicates": 1}
        body["batch_id"] = "new-batch"
        body["messages"].append(message("124"))
        assert client.post(url, headers=headers, json=body).json() == {"accepted": 1, "duplicates": 1}
        body["messages"] = [message(str(i)) for i in range(500)]
        assert client.post(url, headers=headers, json=body).status_code == 200
        body["messages"].append(message("501"))
        assert client.post(url, headers=headers, json=body).status_code == 422
        raw = json.dumps(dict(source="eve", batch_id="b", messages=[message()])).encode()
        raw += b" " * (2 * 1024 * 1024 - len(raw))
        assert client.post(url, headers=headers, content=raw).status_code == 200
        response = client.post(url, headers=headers, content=b"x" * (2 * 1024 * 1024 + 1))
        assert response.status_code == 413
        assert client.post(url, headers=headers, content=b"not json").status_code == 422
        body["messages"] = [message(created_at="no-date", content="private")]
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 422 and "private" not in response.text
    with dd.connect(tmp_path) as con:
        assert con.execute("select count(*) from messages").fetchone()[0] == 500


@pytest.mark.parametrize("change", [dict(created_at="2026-10-22T03:00:00"), dict(author_is_bot="false"),
                                     dict(message_id="../bad"), dict(thread_id="bad")])
def test_message_contract_rejects_invalid_fields(change):
    with pytest.raises(ValueError):
        batch(message(**change))


def test_incremental_summaries_late_arrival_day_thread_and_retry(tmp_path):
    redact = Redactor({"private-secret"})
    dd.receive(tmp_path, batch(message(content="決定 private-secret"), message("124", thread_id="8"),
                               message("125", created_at="2026-10-21T03:00:00Z")), redact)
    calls = []

    def chat(group, system, user):
        assert "private-secret" not in user
        calls.append(user)
        return {"summary": "사용자가 완성을 약속 [123]"}, "fake"

    assert dd.summarize(tmp_path, redact, chat=chat) == {"summarized": 3, "failed": 0}
    assert dd.summarize(tmp_path, redact, chat=chat)["summarized"] == 0
    assert len(calls) == 3
    assert any('"is_owner": true' in user for user in calls)
    # Backfilled older event in an already summarized day must still be processed.
    dd.receive(tmp_path, batch(message("126", created_at="2026-10-22T01:00:00Z")), redact)

    def fail(*args):
        raise RuntimeError("gateway down")

    assert dd.summarize(tmp_path, redact, chat=fail)["failed"] == 1
    assert dd.summarize(tmp_path, redact, chat=chat)["summarized"] == 1
    assert len(calls) == 4 and '"message_id": "126"' in calls[-1]
    assert '"message_id": "123"' not in calls[-1]
    text = dd.recent(tmp_path, now=datetime(2026, 10, 22, 10, tzinfo=timezone.utc))
    assert "스레드 8" in text and "사용자" in text and "요약" in text


def test_long_message_successful_parts_are_not_repeated(tmp_path):
    dd.receive(tmp_path, batch(message(content="a" * 25000)), Redactor())
    assert dd.summarize(tmp_path, Redactor(), chat=lambda *a: ({"summary": "part"}, "test"),
                        max_batches=1)["summarized"] == 1
    calls = []
    dd.summarize(tmp_path, Redactor(), chat=lambda g, s, u: (calls.append(u) or {"summary": "rest"}, "test"))
    assert calls and all('"part": 0' not in call for call in calls)
    with dd.connect(tmp_path) as con:
        assert con.execute("select count(*) from parts where summary_id is null").fetchone()[0] == 0


def test_summary_time_budget_and_transport_timeout(tmp_path, monkeypatch):
    dd.receive(tmp_path, batch(message()), Redactor())
    calls = []

    def chat(*args, **kwargs):
        calls.append(kwargs)
        return {"summary": "요약"}, "fake"

    monkeypatch.setattr(dd, "chat_json", chat)
    assert dd.summarize(tmp_path, Redactor(), budget_seconds=0)["summarized"] == 0
    assert calls == []
    assert dd.summarize(tmp_path, Redactor())["summarized"] == 1
    assert calls[0]["timeout"] == 45


def test_notion_read_only_fixed_addresses_and_filtering(monkeypatch):
    from all_tomorrow.idea_factory import profile

    def block(text):
        return {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": text}]}}

    pages = {cb.ROOT: [block("목표·프로젝트 원장 data_source: collection://c527805b-cf11-4412-aade-5e3352053707"),
                       block("일기 원장 data_source: collection://8f2e8dbc-b611-4e35-a1b8-d36750f0900c"),
                       block("일일 기록 인덱스 page_id: 3d14b985-2216-81de-91f3-cb7aedfca219")],
             cb.ACTIVE: [{"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "열린 후보"}]}}, block("게임 | page_id: task")],
             "3d14b985-2216-81de-91f3-cb7aedfca219": [
                 {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "오늘 일기"}]}},
                 block("2026-10-22 오늘 일기")],
             "a": [block("본문 실제 흐름") ]}

    def row(id, **values):
        return {"id": id, "last_edited_time": id, "properties": {
            k: {"type": "rich_text", "rich_text": [{"plain_text": v}]} for k, v in values.items()}}

    tasks = [row("a", 할일="해야할일", 상태="진행중"), row("b", 할일="끝난일", 상태="완료")]
    goals = [row("a", **{"목표/프로젝트": "살아있는목표", "상태": "진행중"}),
             row("b", **{"목표/프로젝트": "과거목표", "상태": "완료"})]
    diaries = [row("a", 날짜="2026-10-22", 하루요약="만들었다"),
               row("b", 날짜="2026-10-01", 하루요약="오래된기록")]
    monkeypatch.setattr(profile, "_blocks", lambda id: pages[id])
    monkeypatch.setattr(profile, "_query", lambda id: tasks if id == cb.TASKS else goals if id.startswith("c527") else diaries)
    monkeypatch.setattr(cb.brief, "load_notion", lambda: {"사용자": {"text": "프로필"}})
    result = cb.load_notion(today=date(2026, 10, 22))
    text = json.dumps(result, ensure_ascii=False)
    assert all(word in text for word in ("해야할일", "살아있는목표", "만들었다", "프로필", "오늘 일기", "본문 실제 흐름"))
    assert all(word not in text for word in ("끝난일", "과거목표", "오래된기록"))


def test_render_all_sections_limits_deadlines_and_fallback(tmp_path):
    store = SessionStore(tmp_path / "overseer.sqlite")
    (tmp_path / "direction.md").write_text("# 큰 방향\n게임을 만들고 싶다\n## 프로젝트\n"
        "- 플레시핏 10/31까지\n- sfstory 11월 8일까지\n- 북부의 휴지들 11월 15일까지\n"
        "- weinovel 10월 19일~12월 13일\n", encoding="utf-8")
    dd.receive(tmp_path, batch(message()), Redactor())
    (tmp_path / "metacog-journal.md").write_text("## 2026-10-21\n지난 일지\n## 2026-10-22\n최신 일지", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "latest.json").write_text(json.dumps({"id": "recent", "content": "최근 보고 내용"}), encoding="utf-8")
    text = cb.render(store.con, tmp_path, projects={"projects": []},
                     notion={"할 일": {"text": "최신 할 일\n" * 2000}, "일기": {"text": "최근 일기 흐름"}},
                     discord=dd.recent(tmp_path, now=datetime(2026, 10, 22, 10, tzinfo=timezone.utc)),
                     counts="열린 Work 2 / 실패 Work 1", now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert len(text) <= 12000
    assert text.count("\n## ") == 5
    assert all(word in text for word in ("D-9", "D-17", "D-24", "D-52", "최근 일기 흐름", "원문 발췌", "실패 Work 1", "최근 보고 내용", "최신 일지"))
    store.close()


def test_refresh_atomic_offline_and_secret_redaction(tmp_path, monkeypatch):
    from all_tomorrow.overseer import __main__ as cli
    store = SessionStore(tmp_path / "overseer.sqlite")
    (tmp_path / "direction.md").write_text("# 목표\nprivate-secret", encoding="utf-8")
    monkeypatch.setattr(cb, "load_key_pool", lambda: None)
    monkeypatch.setattr(cb.Redactor, "from_files", lambda files: Redactor({"private-secret"}))
    monkeypatch.setattr(cb, "load_notion", lambda: {"할일": {"text": "노션 실제 내용 대역"}})
    monkeypatch.setattr(cb.brief, "load_projects", lambda: {})
    monkeypatch.setattr(cb, "load_work_counts", lambda: "열린 Work 0 / 실패 Work 0")
    monkeypatch.setattr(cli, "_gateway_alive", lambda: False)
    monkeypatch.setattr(dd, "summarize", lambda *a: pytest.fail("offline model called"))
    target = cb.refresh(store.con, tmp_path)
    text = target.read_text(encoding="utf-8")
    assert "노션 실제 내용 대역" in text and "무료 모델 꺼짐" in text and "private-secret" not in text
    monkeypatch.setattr(cb, "render", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        cb.refresh(store.con, tmp_path)
    assert target.read_text(encoding="utf-8") == text
    assert not list(tmp_path.glob("control-brief-*.tmp"))
    store.close()


def test_work_counts_include_all_terminal_and_open_states():
    from all_tomorrow.domain.state import WorkStatus
    states = [WorkStatus.PENDING] * 105 + [WorkStatus.FAILED, WorkStatus.SUCCEEDED, WorkStatus.CANCELLED]

    class Store:
        async def list_goals(self):
            import os
            return [SimpleNamespace(goal_id="g", user_id=os.environ.get("ALL_TOMORROW_ADMIN_USER") or "owner")]

        async def list_work(self, goal_id):
            return [SimpleNamespace(status=s) for s in states]

    assert asyncio.run(cb.work_counts(Store())) == "열린 Work 105 / 실패 Work 1 (전체 108)"


def test_hourly_no_metacog_refreshes_brief(tmp_path, monkeypatch):
    from all_tomorrow.overseer import __main__ as cli
    from all_tomorrow.overseer import distill
    monkeypatch.setattr(cli, "collect", lambda *a: {})
    monkeypatch.setattr(cli, "_load_gateway_key", lambda: None)
    monkeypatch.setattr(cli, "_ensure_gateway", lambda: False)
    monkeypatch.setattr(cli.SessionStore, "publish", lambda *a: "fake-peer")
    called = []
    monkeypatch.setattr(cb, "refresh", lambda con, base: called.append(base))
    monkeypatch.setattr(cli, "_metacog_due", lambda *a: pytest.fail("metacog called"))
    assert cli.main(["--dir", str(tmp_path), "run", "--no-metacog"]) == 0
    assert called == [tmp_path]
