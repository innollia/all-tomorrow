"""메타인지 자기 고리 방지(2026-10-26 정지 원인) 회귀시험. 실제 모델은 부르지 않는다.

- A 변화가 없으면 모델을 부르지 않고, 최소 간격·하루 상한을 지킨다.
- B 메모 재작성이 방향 파일을 건드리지 않고, 방향 변경은 새 근거다.
- C 반복 판단에도 Goal/Work가 늘지 않고, All Tomorrow 자체 Work는 하나만 열린다.
- D 스냅샷·프롬프트에 관제 브리핑과 방향이 들어간다.
- E 비밀값 가리기가 JSON을 깨지 않는다.
- F 쿼터 소진 작업자는 초기화 시각까지 건너뛴다.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from all_tomorrow.contracts import WorkerResult, WorkerStatus
from all_tomorrow.overseer import cooldown, loop, metacog
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore

FAST = {"min_interval": 0, "daily_limit": 1000, "idle_seconds": 300, "check_interval": 600}
EMPTY = '{"observations": [], "actions": [], "notes": ""}'


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    monkeypatch.setattr("all_tomorrow.overseer.reports.flush", lambda *a: 0)
    monkeypatch.delenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ALL_TOMORROW_METACOG_REASONER", raising=False)
    monkeypatch.setenv("ALL_TOMORROW_METACOG_MIN_INTERVAL_MINUTES", "0")
    monkeypatch.delenv("ALL_TOMORROW_METACOG_DAILY_LIMIT", raising=False)


@pytest.fixture
def sessions(tmp_path):
    store = SessionStore(tmp_path / "overseer.sqlite")
    yield store
    store.close()


def add_session(store, sid, line="[U] 플레시핏 충돌 판정 고치기"):
    s = Session("codex", sid, cwd="C:\\projects\\flashfit", title="플레시핏", updated_at="2026-10-26T00:00:00")
    s.lines = [line]
    store.put(s, "fp-" + sid, lambda t: t)
    store.commit()


def counter():
    calls = []

    def reasoner(prompt, workdir):
        calls.append(prompt)
        return EMPTY
    return calls, reasoner


# A ---------------------------------------------------------------------------

def test_unchanged_snapshot_never_calls_the_model_and_notion_is_not_read(tmp_path, sessions):
    add_session(sessions, "s1")
    calls, reasoner = counter()
    notion_reads = []

    def notion():
        notion_reads.append(1)
        return {"목표": {"text": "플레시핏 10/31"}}

    first = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=notion,
                         reasoner=reasoner, config=FAST)
    assert first["status"] == "done" and len(calls) == 1 and notion_reads == [1]
    for _ in range(5):   # 열린 Work·자기 로그 경고가 있어도 새 근거가 아니다
        (tmp_path / "overseer.log").write_text("2099-01-01 00:00:00,000 WARNING 사용량 push 실패\n", encoding="utf-8")
        result = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=notion,
                              reasoner=reasoner, config=FAST,
                              central={"work": [{"id": "w", "title": "t", "status": "PENDING"}], "events": []})
        assert result["status"] == "skipped" and result["reason"].startswith("변화 없음")
    assert len(calls) == 1 and notion_reads == [1]
    add_session(sessions, "s2")
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=notion,
                        reasoner=reasoner, config=FAST)["status"] == "done"
    assert len(calls) == 2


async def test_repeated_observe_without_change_never_reaches_the_reasoner(tmp_path, sessions):
    store = InMemoryGoalWorkRunStore()
    calls, reasoner = counter()
    await loop.observe(store, sessions, tmp_path, registry={}, redact=lambda t: t, reasoner=reasoner, force=True)
    for _ in range(10):
        result = await loop.observe(store, sessions, tmp_path, registry={}, redact=lambda t: t, reasoner=reasoner)
        assert result["status"] == "skipped"
    assert len(calls) == 1


def test_minimum_interval_and_daily_limit_block_model_calls(tmp_path, sessions):
    calls, reasoner = counter()
    config = dict(FAST, min_interval=1800, daily_limit=2)
    add_session(sessions, "a")
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                        reasoner=reasoner, config=config)["status"] == "done"
    add_session(sessions, "b")
    blocked = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                           reasoner=reasoner, config=config)
    assert blocked["status"] == "skipped" and "최소 간격" in blocked["reason"] and len(calls) == 1
    # 하루 상한: 직전 호출을 31분 전으로 옮겨도 24시간 안 호출 수가 상한이면 막는다.
    sessions.con.execute("update metacog_wakes set at = ? where status = 'done'",
                         ((datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),))
    sessions.con.commit()
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                        reasoner=reasoner, config=config)["status"] == "done"
    sessions.con.execute("update metacog_wakes set at = ? where status = 'done'",
                         ((datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(),))
    sessions.con.commit()
    add_session(sessions, "c")
    capped = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                          reasoner=reasoner, config=config)
    assert capped["status"] == "skipped" and "상한 2회" in capped["reason"] and len(calls) == 2
    # 관제의 수동 실행(--force)은 막지 않는다.
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                        reasoner=reasoner, config=config, force=True)["status"] == "done"


# B ---------------------------------------------------------------------------

def test_notes_rewrite_keeps_direction_files_and_direction_change_wakes(tmp_path, sessions):
    direction = "# 관제가 사용자와 정한 방향\n\n- AI 게임개발 프로그램, 착수 11/15 이후\n"
    (tmp_path / "direction-notes.md").write_text(direction, encoding="utf-8")
    (tmp_path / "direction.md").write_text("게임을 만들고 싶다\n", encoding="utf-8")
    seen = []

    def reasoner(prompt, workdir):
        path = Path(prompt.split("스냅샷 파일: ")[1].splitlines()[0])
        seen.append((prompt, json.loads(path.read_text(encoding="utf-8"))))
        return json.dumps({"observations": [], "actions": [], "notes": "메모를 통째로 새로 쓴다"}, ensure_ascii=False)

    for _ in range(3):
        metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                     reasoner=reasoner, config=FAST, force=True)
    assert (tmp_path / "direction-notes.md").read_text(encoding="utf-8") == direction
    assert (tmp_path / "metacog-notes.md").read_text(encoding="utf-8").strip() == "메모를 통째로 새로 쓴다"
    prompt, snapshot = seen[-1]
    assert snapshot["user_direction"]["direction-notes.md"] == direction
    assert str(tmp_path / "direction-notes.md") in prompt and "읽기 전용" in prompt
    calls_before = len(seen)
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                        reasoner=reasoner, config=FAST)["status"] == "skipped"
    (tmp_path / "direction-notes.md").write_text(direction + "- 마감: 11/8 sfstory\n", encoding="utf-8")
    assert metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                        reasoner=reasoner, config=FAST)["status"] == "done"
    assert len(seen) == calls_before + 1


# C ---------------------------------------------------------------------------

def registry_for(tmp_path):
    user = tmp_path / "flashfit"
    user.mkdir(exist_ok=True)
    verify = {"verify_argv": ["{python}", "-c", "pass"]}
    return {"all-tomorrow": {"path": str(Path(__file__).resolve().parents[1]), "autonomy": verify},
            "flashfit": {"path": str(user), "autonomy": verify}}


def self_fix(i):
    # 표현과 문제 키가 매번 다른 "중복 방지" 수정 — 실제로 쌓였던 모양.
    titles = ["Python 복구 작업 중복 등록 방지", "Python 복구 작업의 중복 생성 차단", "메타인지 중복 Goal/Work 정리",
              "반복 fallback 보고 억제", "스냅샷 JSON 파싱 실패 수정"]
    return {"kind": "fix", "title": titles[i % len(titles)], "detail": "중복을 막는다", "project_id": "all-tomorrow",
            "authority": "ordinary", "problem_key": f"self-{i}", "evidence_refs": ["project:all-tomorrow"]}


async def test_repeated_self_actions_open_at_most_one_self_work(tmp_path):
    store = InMemoryGoalWorkRunStore()
    registry = registry_for(tmp_path)
    for i in range(8):
        await loop.materialize_actions(store, [self_fix(i)], wake_id=f"w{i}", known_refs={"project:all-tomorrow"},
                                       registry=registry, redact=lambda t: t)
    assert len(await store.list_goals()) == 1
    deferred = [e for e in await store.list_events() if e.type == "metacog.self_work_deferred"]
    # 8번 중 1번 생성, 1번(i=5)은 같은 제목이라 중복, 나머지 6번은 자기 Work가 열려 있어 보류.
    assert len(deferred) == 6 and all("report" not in e.payload for e in deferred)   # 디스코드로 가지 않는다


async def test_self_fix_without_new_failure_is_held_before_reaching_central(tmp_path, sessions):
    store = InMemoryGoalWorkRunStore()
    registry = registry_for(tmp_path)
    user_fix = {"kind": "fix", "title": "플레시핏 빌드 실패 수정", "detail": "고친다", "project_id": "flashfit",
                "authority": "ordinary", "problem_key": "build", "evidence_refs": ["project:flashfit"]}
    for i in range(5):
        add_session(sessions, f"s{i}")
        reply = json.dumps({"observations": [], "actions": [self_fix(i), user_fix], "notes": ""}, ensure_ascii=False)
        result = await loop.observe(store, sessions, tmp_path, registry=registry, redact=lambda t: t,
                                    reasoner=lambda p, w, reply=reply: reply)
        assert [a["project_id"] for a in result["actions"]] == ["flashfit"]
        assert "자체 수정 판단을 보류" in result["observations"][-1]["what"]
    titles = [g.title for g in await store.list_goals()]
    assert titles == ["플레시핏 빌드 실패 수정"]
    # 새 실패(작업 결과 rolled_back)가 있으면 자기 수정도 만들 수 있다.
    await store.append_event(loop.event("metacog.rolled_back", payload={"reason": "시험 실패"}))
    reply = json.dumps({"observations": [], "actions": [self_fix(0)], "notes": ""}, ensure_ascii=False)
    result = await loop.observe(store, sessions, tmp_path, registry=registry, redact=lambda t: t,
                                reasoner=lambda p, w: reply)
    assert result["status"] == "done" and len(result["actions"]) == 1
    assert len(await store.list_goals()) == 2


async def test_same_purpose_is_idempotent_but_other_user_work_is_allowed(tmp_path):
    store = InMemoryGoalWorkRunStore()
    registry = registry_for(tmp_path)
    fix = {"kind": "fix", "title": "플레시핏 빌드 실패 수정", "detail": "빌드 오류를 고친다", "project_id": "flashfit",
           "authority": "ordinary", "problem_key": "build-a", "evidence_refs": ["project:flashfit"]}
    refs = {"project:flashfit", "project:all-tomorrow"}
    for i, variant in enumerate(["플레시핏 빌드 실패 수정", "플레시핏  빌드 실패 수정.", "플레시핏 빌드-실패 수정"]):
        await loop.materialize_actions(store, [dict(fix, title=variant, problem_key=f"build-{i}")],
                                       wake_id=f"w{i}", known_refs=refs, registry=registry, redact=lambda t: t)
    assert len(await store.list_goals()) == 1
    await loop.materialize_actions(store, [self_fix(0), dict(fix, title="플레시핏 저장 오류", problem_key="save")],
                                   wake_id="w9", known_refs=refs, registry=registry, redact=lambda t: t)
    assert len(await store.list_goals()) == 3   # 사용자 프로젝트의 다른 일과 자기 Work 하나는 만든다
    report = {"kind": "report", "title": "플레시핏 마감 D-5, 최근 세션 없음", "detail": "확인 필요"}
    for i in range(3):
        await loop.materialize_actions(store, [report], wake_id=f"r{i}", known_refs=refs, registry=registry,
                                       redact=lambda t: t)
    assert len([e for e in await store.list_events() if e.type == "metacog.report"]) == 1


async def test_close_self_work_cancels_without_deleting(tmp_path):
    store = InMemoryGoalWorkRunStore()
    registry = registry_for(tmp_path)
    refs = {"project:flashfit", "project:all-tomorrow"}
    user_fix = {"kind": "fix", "title": "플레시핏 빌드 실패 수정", "detail": "고친다", "project_id": "flashfit",
                "authority": "ordinary", "problem_key": "build", "evidence_refs": ["project:flashfit"]}
    await loop.materialize_actions(store, [self_fix(0), user_fix], wake_id="w", known_refs=refs,
                                   registry=registry, redact=lambda t: t)
    listed = await loop.close_self_work(store, registry, reason="시험")
    assert [i["title"] for i in listed] == [self_fix(0)["title"]]
    assert all(not w["work"].is_terminal() for w in await loop.open_metacog_work(store))   # 목록만
    await loop.close_self_work(store, registry, reason="관제 정리", apply=True)
    remaining = await loop.open_metacog_work(store)
    assert [r["project_id"] for r in remaining] == ["flashfit"]
    goals = await store.list_goals()
    assert len(goals) == 2 and sorted(g.status.value for g in goals) == ["ACTIVE", "CANCELLED"]
    cancelled = [e for e in await store.list_events() if e.type == "metacog.cancelled"]
    assert len(cancelled) == 1 and cancelled[0].payload["reason"] == "관제 정리"
    assert "report" not in cancelled[0].payload


# D ---------------------------------------------------------------------------

def test_snapshot_and_prompt_put_user_goals_first(tmp_path, sessions):
    (tmp_path / "control-brief.md").write_text("# 관제 브리핑\n- 2026-10-31 · D-5 · 플레시핏\n", encoding="utf-8")
    seen = {}

    def reasoner(prompt, workdir):
        path = Path(prompt.split("스냅샷 파일: ")[1].splitlines()[0])
        seen.update(prompt=prompt, snapshot=json.loads(path.read_text(encoding="utf-8")))
        return EMPTY

    metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None, reasoner=reasoner,
                 config=FAST, force=True)
    assert "D-5 · 플레시핏" in seen["snapshot"]["control_brief"]
    prompt = seen["prompt"]
    assert prompt.index("사용자 목표와 마감") < prompt.index("All Tomorrow·메타인지 자체의 문제")
    assert "새 실패" in prompt and "Encoding UTF8" in prompt
    assert len(seen["snapshot"]["own_previous_wakes"]) <= 3


# E ---------------------------------------------------------------------------

def test_redaction_cannot_break_snapshot_json():
    # 직렬화 뒤 가리면 `API_KEY=...\` 끝의 역슬래시가 지워져 닫는 따옴표가 풀렸다.
    line = 'set API_KEY=abcdefgh1234\\'
    text = metacog._fit({"changed_sessions": [{"tail": [line, "TOKEN: \"zzzzzzzzzz\\\""]}], "other": "x"},
                        Redactor({"pool-secret-value"}))
    data = json.loads(text)
    assert "abcdefgh1234" not in text and "REDACTED" in data["changed_sessions"][0]["tail"][0]


def test_reasoner_reply_is_parsed_before_redaction(tmp_path, sessions):
    reply = json.dumps({"observations": [{"what": "PASSWORD=hunter2hunter2\\", "evidence": "x", "importance": "high"}],
                        "actions": [], "notes": ""})
    result = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                          reasoner=lambda p, w: reply, config=FAST, force=True)
    assert result["status"] == "done" and "hunter2" not in json.dumps(result["observations"])


# F ---------------------------------------------------------------------------

def test_quota_message_parsing():
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    text = "Exit code 3: error: Individual quota reached. Please upgrade. Resets in 150h28m49s."
    assert cooldown.quota_reset(text, now) == now + timedelta(hours=150, minutes=28, seconds=49)
    assert cooldown.quota_reset("You've hit your usage limit.", now) == now + cooldown.DEFAULT_WAIT
    assert cooldown.quota_reset("stream disconnected before completion", now) is None


def test_exhausted_reasoner_is_skipped_until_reset(tmp_path, sessions, monkeypatch):
    calls = []

    def agy(prompt, workdir):
        calls.append("antigravity")
        raise cooldown.QuotaExhausted(datetime.now(timezone.utc) + timedelta(hours=147))

    def codex(prompt, workdir):
        calls.append("codex")
        return EMPTY

    monkeypatch.setenv("ALL_TOMORROW_METACOG_REASONER", "antigravity")
    monkeypatch.setattr(metacog, "antigravity_reasoner", agy)
    monkeypatch.setattr(metacog, "codex_reasoner", codex)
    for _ in range(3):
        result = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                              config=FAST, force=True)
        assert result["status"] == "done" and result["reasoner"] == "codex"
    assert calls == ["antigravity", "codex", "codex", "codex"]
    assert "쿼터 초기화 대기" in result["fallback_reason"]


def test_codex_exhausted_by_usage_and_all_waiting_skips_without_calls(tmp_path, sessions, monkeypatch):
    reset = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    usage = {"providers": [{"id": "codex", "status": "connected", "source": "live",
                            "windows": [{"label": "5-hour", "percent": 100, "resets_at": reset}]}]}
    cooldown.Cooldowns(tmp_path / cooldown.FILE_NAME).set("antigravity", datetime.now(timezone.utc) + timedelta(hours=1))
    cooldown.Cooldowns(tmp_path / cooldown.FILE_NAME).set("claude", datetime.now(timezone.utc) + timedelta(hours=1))
    for name in ("codex_reasoner", "antigravity_reasoner", "claude_reasoner"):
        monkeypatch.setattr(metacog, name, lambda *a: pytest.fail("쿼터 대기 중인 판단자 호출"))
    result = metacog.wake(sessions.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                          config=FAST, force=True, usage=usage)
    assert result["status"] == "skipped" and "쿼터" in result["reason"]


async def test_worker_quota_is_remembered_by_the_executor(tmp_path, monkeypatch):
    from all_tomorrow import local_workers
    root, base = tmp_path / "project", tmp_path / "state"
    (root / "src").mkdir(parents=True)
    (root / "src/demo.py").write_text("answer = 1\n", encoding="utf-8")
    workers = tmp_path / "workers.json"
    workers.write_text(json.dumps({"workers": {}}), encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_WORKERS", str(workers))
    runs = []

    class Agy:
        capabilities = frozenset()

        async def is_available(self):
            return True

        async def execute(self, request):
            runs.append(1)
            return WorkerResult("r", "t", WorkerStatus.FAILED,
                                error="error: Individual quota reached. Resets in 147h1m2s.")

    class NoClaude:
        capabilities = frozenset()

        async def is_available(self):
            return False

    monkeypatch.setattr(local_workers, "configured_adapters", lambda c: {"antigravity": Agy()})
    monkeypatch.setattr(loop, "claude_worker", lambda model, candidate: NoClaude())
    monkeypatch.setattr("all_tomorrow.idea_factory.llm.chat", lambda *a, **kw:
                        ('{"edits":[{"file":"src/demo.py","content":"answer = 2\\n"}]}', "fake"))
    for name in ("w1", "w2"):
        change = loop.ProjectChange(root, base / "changes" / name)
        change.prepare()
        result = await loop.run_worker({"objective": "수정", "project_id": "demo"}, change.candidate)
        assert result["worker"] == "free"
    assert runs == [1]
    assert result["attempts"][0]["status"] == "QUOTA_COOLDOWN"
    assert cooldown.Cooldowns(base / cooldown.FILE_NAME).until("antigravity") is not None


def test_control_brief_shows_direction_notes(tmp_path, sessions):
    from all_tomorrow.overseer import control_brief as cb
    (tmp_path / "direction.md").write_text("# 큰 방향\n게임을 만들고 싶다\n", encoding="utf-8")
    (tmp_path / "direction-notes.md").write_text("- AI 게임개발 프로그램: 착수 2026-11-15 이후\n", encoding="utf-8")
    text = cb.render(sessions.con, tmp_path, projects={"projects": []}, notion={}, discord="", counts="",
                     now=datetime(2026, 10, 26, tzinfo=timezone.utc))
    section = text.split("## 2.")[0]
    assert "게임을 만들고 싶다" in section and "착수 2026-11-15 이후" in section


def test_central_view_keeps_open_work_and_results_not_bookkeeping():
    central = {"goals": [{"id": f"g{i}"} for i in range(50)],
               "work": [{"id": "open", "status": "WAITING"}] + [{"id": f"c{i}", "status": "CANCELLED"} for i in range(30)],
               "events": [{"at": "2026-10-27", "type": t, "ref": t} for t in
                          ("metacog.cancelled", "metacog.wake_applied", "metacog.rolled_back", "metacog.report",
                           "metacog.run_started", "discord.question_reply")]}
    view = metacog.central_view(central, "2026-10-26")
    assert [w["id"] for w in view["open_work"]] == ["open"] and len(view["recent_closed_work"]) == 10
    assert view["work_counts"] == {"WAITING": 1, "CANCELLED": 30} and view["goals_total"] == 50
    assert [e["type"] for e in view["events"]] == ["metacog.rolled_back", "metacog.report", "discord.question_reply"]
