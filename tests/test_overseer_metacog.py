import json

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
