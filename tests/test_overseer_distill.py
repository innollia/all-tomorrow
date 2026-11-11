import json
import subprocess

import pytest

from all_tomorrow.idea_factory.llm import LLMError
from all_tomorrow.overseer import distill
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore

POOL_VALUE = "pool-value-1234567890"


def _store(tmp_path, text):
    store = SessionStore(tmp_path / "o.sqlite")
    s = Session("codex", "c1", cwd="C:\\projects\\web", title="빌드", agent="codex", models={"gpt-5.5"})
    s.lines = text.splitlines()
    store.put(s, "fp1", lambda t: t)
    store.commit()
    distill.ensure_schema(store.con)
    return store


def test_cards_are_stored_with_provenance_and_failed_groups_fall_back(tmp_path) -> None:
    store = _store(tmp_path, "[U] 빌드 실패\n[E] Exit code: 1 Module not found\n[A] 경로 수정")
    seen = []

    def chat(group, system, user):
        seen.append((group, user))
        if group == distill.MODEL_GROUPS[0]:
            raise LLMError("429")
        return [{"problem": "npm build에서 Module not found", "situation": ["node", "windows"],
                 "attempts": "", "solution": "import 경로 대소문자 수정", "outcome": "해결", "evidence": "경로 수정"},
                "not a card"], "dep-1"

    made = distill.distill_session(store.con, "codex", "c1", redact=Redactor(), secrets=frozenset(), chat=chat)
    assert made == 1
    assert [g for g, _ in seen] == list(distill.MODEL_GROUPS[:2])
    assert "도구: codex" in seen[0][1] and "프로젝트: web" in seen[0][1]
    row = store.con.execute("select project, outcome, solution, distilled_by, status from cards").fetchone()
    assert row == ("web", "해결", "import 경로 대소문자 수정", f"{distill.MODEL_GROUPS[1]}:dep-1", "candidate")
    assert store.con.execute("select cards, failed_chunks from distilled").fetchone() == (1, 0)

    # Re-distilling a session replaces its cards instead of piling up duplicates.
    distill.distill_session(store.con, "codex", "c1", redact=Redactor(), secrets=frozenset(), chat=chat)
    assert store.con.execute("select count(*) from cards").fetchone()[0] == 1


def test_failed_sessions_stay_pending_and_done_ones_do_not(tmp_path) -> None:
    store = _store(tmp_path, "[U] 빌드 실패\n" + "[A] 로그 " * 400)
    store.con.execute("update sessions set updated_at = '2026-01-01T00:00:00', n_user = 1")
    assert distill.pending_sessions(store.con, 10) == [("codex", "c1")]

    def down(group, system, user):
        raise LLMError("gateway down")

    distill.distill_session(store.con, "codex", "c1", redact=Redactor(), secrets=frozenset(), chat=down)
    assert distill.pending_sessions(store.con, 10) == [("codex", "c1")]
    distill.distill_session(store.con, "codex", "c1", redact=Redactor(), secrets=frozenset(),
                            chat=lambda g, s, u: ([], "d"))
    assert distill.pending_sessions(store.con, 10) == []

    # A session still being worked in (updated just now) waits.
    store.con.execute("update sessions set fingerprint = 'fp2', updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')")
    assert distill.pending_sessions(store.con, 10) == []


def test_known_secret_never_reaches_the_model(tmp_path) -> None:
    store = _store(tmp_path, f"[U] 키는 {POOL_VALUE} 야")
    sent = []
    redact = Redactor({POOL_VALUE})
    distill.distill_session(store.con, "codex", "c1", redact=redact, secrets=redact.values,
                            chat=lambda g, s, u: (sent.append(u), ([], "d"))[1])
    assert sent and all(POOL_VALUE not in u for u in sent)

    # If redaction ever misses a known value, the call is refused rather than sent.
    with pytest.raises(distill.SecretLeak):
        distill.distill_session(store.con, "codex", "c1", redact=lambda t: t, secrets=frozenset({POOL_VALUE}),
                                chat=lambda g, s, u: ([], "d"))


def test_chunks_split_on_line_boundaries() -> None:
    text = "\n".join(f"[U] line {i} " + "x" * 50 for i in range(100))
    parts = distill.chunks(text, size=1000)
    assert len(parts) > 1 and all(len(p) <= 1100 for p in parts)
    assert "\n".join(parts) == text


def test_quota_errors_close_the_gateway_for_the_day_and_use_the_cli(tmp_path) -> None:
    calls = []

    def spent(group, system, user):
        calls.append(group)
        raise distill.LLMError("429 free-models-per-day")

    budget = distill.Budget(tmp_path / "b.json")
    cli = lambda system, user: ([{"problem": "p"}], "cli:test")
    assert distill._call(spent, "x", budget, cli) == ([{"problem": "p"}], "cli:test")
    assert len(calls) == len(distill.MODEL_GROUPS)
    again = distill.Budget(tmp_path / "b.json")
    assert not again.gateway_open()
    assert distill._call(spent, "x", again, cli)[1] == "cli:test"
    assert len(calls) == len(distill.MODEL_GROUPS)


def test_daily_cap_stops_gateway_calls(tmp_path) -> None:
    budget = distill.Budget(tmp_path / "b.json", daily=1)
    ok = lambda g, s, u: ([{"problem": "p"}], "dep")
    assert distill._call(ok, "x", budget, None)[1].endswith(":dep")
    assert not budget.gateway_open()


def test_own_cli_sessions_are_never_pending(tmp_path) -> None:
    store = _store(tmp_path, "[U] " + distill.SYSTEM + "\n" + "[A] 로그 " * 400)
    store.con.execute("update sessions set updated_at = '2026-01-01T00:00:00', n_user = 1")
    assert distill.pending_sessions(store.con, 10) == []


def test_cli_chat_runs_without_tools_or_transcript(monkeypatch) -> None:
    seen = {}

    def run(cmd, **_):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, '{"cards": []}', "")

    monkeypatch.setattr(distill.subprocess, "run", run)
    monkeypatch.setattr(distill.shutil, "which", lambda _: "claude")
    monkeypatch.setattr("all_tomorrow.overseer.idle_research.quota_ok", lambda *_: (True, ""))
    assert distill.cli_chat("s", "u")[0] == []
    assert {"--strict-mcp-config", "--no-session-persistence"} <= set(seen["cmd"])
