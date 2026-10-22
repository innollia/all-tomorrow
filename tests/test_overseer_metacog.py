import json
import subprocess

import pytest

from all_tomorrow.overseer import metacog
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore

SECRET = "pool-value-1234567890"


def _store(tmp_path):
    store = SessionStore(tmp_path / "overseer.sqlite")
    s = Session("codex", "c1", cwd="C:\\projects\\web", title="빌드", updated_at="2026-10-20T00:00:00")
    s.lines = ["[U] 빌드가 또 실패", f"[E] Exit code: 1 key {SECRET}"]
    store.put(s, "fp", lambda t: t)
    own = Session("codex", "self", cwd="C:\\projects")
    own.lines = [f"[U] {metacog.WAKE_MARK} 너는 메타인지 계층이다"]
    store.put(own, "fp", lambda t: t)
    store.commit()
    return store


def test_wake_sees_changes_keeps_journal_and_rewrites_its_own_notes(tmp_path) -> None:
    store = _store(tmp_path)
    seen = {}

    def reasoner(prompt, workdir):
        snapshot_path = prompt.split("스냅샷 파일: ")[1].split("\n")[0]
        seen["snapshot"] = json.loads(open(snapshot_path, encoding="utf-8").read())
        seen["prompt"] = prompt
        return json.dumps({"observations": [{"what": "web 빌드 반복 실패", "evidence": "codex:c1", "importance": "high"}],
                           "actions": [{"kind": "report", "title": "web 빌드", "detail": "같은 실패 반복", "evidence": "codex:c1"}],
                           "notes": "web 빌드를 지켜본다"}, ensure_ascii=False)

    result = metacog.wake(store.con, tmp_path, redact=Redactor({SECRET}), projects=None,
                          notion={"목표": {"text": "web 출시"}}, reasoner=reasoner)
    assert result["status"] == "done" and result["actions"][0]["title"] == "web 빌드"
    snap = seen["snapshot"]
    assert [s["session"] for s in snap["changed_sessions"]] == ["codex:c1"]   # its own run is excluded
    assert snap["notion"] == {"목표": "web 출시"}
    assert SECRET not in json.dumps(snap, ensure_ascii=False)
    assert "정해진 점검 목록은 없다" in seen["prompt"]
    assert (tmp_path / "metacog-notes.md").read_text(encoding="utf-8").strip() == "web 빌드를 지켜본다"
    journal = (tmp_path / "metacog-journal.md").read_text(encoding="utf-8")
    assert "[보고] web 빌드" in journal and "관찰(high)" in journal

    # Next wake: nothing changed → no model call; its own previous wake is part of what it sees later.
    calls = []
    skipped = metacog.wake(store.con, tmp_path, redact=Redactor(), projects=None, notion=None,
                           reasoner=lambda p, w: calls.append(p) or "{}")
    assert skipped["status"] == "skipped" and calls == []
    forced = metacog.wake(store.con, tmp_path, redact=Redactor(), projects=None, notion=None, force=True,
                          reasoner=lambda p, w: (seen.update(prompt2=p), json.dumps({"observations": [], "actions": [], "notes": ""}))[1])
    assert forced["status"] == "done"
    assert (tmp_path / "metacog-notes.md").read_text(encoding="utf-8").strip() == "web 빌드를 지켜본다"


def test_oversized_snapshot_drops_whole_sessions_and_stays_valid_json(monkeypatch) -> None:
    monkeypatch.setattr(metacog, "MAX_SNAPSHOT_CHARS", 3000)
    sessions = [{"session": f"s{i}", "tail": ["x" * 400]} for i in range(20)]
    text = metacog._fit({"changed_sessions": sessions, "other": 1}, lambda t: t)
    data = json.loads(text)
    assert len(text) <= 3000 and data["omitted_sessions"] == 20 - len(data["changed_sessions"])
    assert data["changed_sessions"][0]["session"] == "s0"      # newest kept


def test_failed_reasoning_is_recorded_and_not_counted_as_a_wake(tmp_path) -> None:
    store = _store(tmp_path)

    def broken(prompt, workdir):
        return "no json here"

    result = metacog.wake(store.con, tmp_path, redact=Redactor(), projects=None, notion=None, reasoner=broken)
    assert result["status"] == "failed"
    assert metacog.last_wake(store.con) is None      # the same changes are seen again next time


@pytest.mark.parametrize("failure", [None, "invalid json", subprocess.TimeoutExpired("secret", 1)])
async def test_default_judge_fallback_and_persisted_event(tmp_path, monkeypatch, failure):
    from all_tomorrow.overseer import loop
    from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore

    sessions = _store(tmp_path)
    central = InMemoryGoalWorkRunStore()
    calls = []
    monkeypatch.delenv("ALL_TOMORROW_METACOG_REASONER", raising=False)
    monkeypatch.setenv("ALL_TOMORROW_METACOG_MODEL", "test-gemini")
    monkeypatch.setattr(loop.reports, "flush", lambda *a: None)

    def gemini(prompt, directory):
        calls.append("antigravity")
        if isinstance(failure, Exception):
            raise failure
        return failure or '{"observations": [], "actions": []}'

    def codex(prompt, directory):
        calls.append("codex")
        return '{"observations": [], "actions": []}'

    monkeypatch.setattr(metacog, "antigravity_reasoner", gemini)
    monkeypatch.setattr(metacog, "codex_reasoner", codex)
    result = await loop.observe(central, sessions, tmp_path, registry={}, redact=lambda t: t, force=True)
    expected = "codex" if failure else "antigravity"
    assert result["status"] == "done" and result["reasoner"] == expected
    assert calls == (["antigravity", "codex"] if failure else ["antigravity"])
    row = sessions.con.execute("select reasoner,model,fallback_reason from metacog_wakes").fetchone()
    assert row == (expected, "default" if failure else "test-gemini", result["fallback_reason"])
    payload = next(e.payload for e in await central.list_events() if e.type == "metacog.wake_applied")
    assert all(payload[k] == result[k] for k in ("reasoner", "model", "fallback_reason"))
    journal = (tmp_path / "metacog-journal.md").read_text(encoding="utf-8")
    assert expected in journal and "secret" not in journal
    assert bool(result["fallback_reason"]) == bool(failure)
    # A fallback must not change the next wake's selected reasoner.
    calls.clear()
    await loop.observe(central, sessions, tmp_path, registry={}, redact=lambda t: t, force=True)
    assert calls[0] == "antigravity"


def test_explicit_codex_and_failed_fallback(tmp_path, monkeypatch):
    sessions = _store(tmp_path)
    monkeypatch.setenv("ALL_TOMORROW_METACOG_REASONER", "codex")
    monkeypatch.setattr(metacog, "antigravity_reasoner", lambda *a: pytest.fail("unexpected Gemini"))
    monkeypatch.setattr(metacog, "codex_reasoner", lambda *a: '{}')
    assert metacog.wake(sessions.con, tmp_path, redact=lambda t: t, projects=None,
                        notion=None, force=True)["reasoner"] == "codex"
    monkeypatch.setenv("ALL_TOMORROW_METACOG_REASONER", "antigravity")
    monkeypatch.setattr(metacog, "antigravity_reasoner", lambda *a: 'bad json')
    monkeypatch.setattr(metacog, "codex_reasoner", lambda *a: 'bad json')
    result = metacog.wake(sessions.con, tmp_path, redact=lambda t: t, projects=None, notion=None, force=True)
    assert result["status"] == "failed" and result["fallback_reason"]
    assert "판단 실패" in (tmp_path / "metacog-journal.md").read_text(encoding="utf-8")


def test_antigravity_adapter_is_read_only_noninteractive(tmp_path, monkeypatch):
    from all_tomorrow.adapters.workers import AntigravityWorker
    from all_tomorrow.contracts import WorkerResult, WorkerStatus
    monkeypatch.setattr("all_tomorrow.local_workers.discover_executable", lambda name: "fake-agy")
    monkeypatch.setenv("ALL_TOMORROW_METACOG_MODEL", "test-gemini")

    async def execute(self, request):
        argv = self.build_argv(request.payload["task"])
        assert argv[argv.index("--mode") + 1] == "plan"
        assert "--print" in argv and "--dangerously-skip-permissions" not in argv
        assert argv[argv.index("--model") + 1] == "test-gemini"
        return WorkerResult(request.request_id, request.trace_id, WorkerStatus.SUCCESS,
                            payload={"response": '{"observations": [], "actions": []}'})

    monkeypatch.setattr(AntigravityWorker, "execute", execute)
    assert metacog._parse(metacog.antigravity_reasoner("test", tmp_path))["actions"] == []
