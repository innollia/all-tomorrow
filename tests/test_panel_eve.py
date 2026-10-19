import json
import os
import subprocess

from all_tomorrow.project_panels import eve
from all_tomorrow.projects_snapshot import PANEL_MAX_BYTES

HANDOVER = """# Eve Scene Runtime — HANDOVER

## 1. Current Status

```text
PRODUCTION_DEPLOYMENT_VERIFIED / GATE1_PASS / GATE2_PASS
```

- **Gate 1 (Crash/Retry Matrix)**: **PASS** (12/12 verified on AWS EC2)
- **Gate 2 (Live Public-API E2E)**: **FAIL** (pending)
- **Remote Services**: Active & Healthy (svc on 10.0.0.1:3000)

## 2. Frozen Core Contracts
- **Gate 9 (not a status section)**: **PASS** (2026-01-01)
"""

AGENTS = """# Guide

## 5. Principles
- **Gate 8 (outside section 6)**: **PASS** (2026-01-01)

## 6. Milestones & Gates Status
- **Gate 1 (Infrastructure & Crash/Retry Matrix)**: **PASS (12/12 Verified)** (2026-09-07)
  - detail line
- **Gate 2 (Live Public-API E2E & Production Cutover)**: **PASS (Verified)** (2026-09-08)

- **Gate 4.5 (Discord Multi-Persona Control Plane)**: **PASS (100% Verified)** (2026-09-20)
- **Gate 4.10 (Later)**: **PASS (Verified)** (2026-09-21)

---

## 7. Next Workstream Pointer
"""


def test_gates_come_from_handover_section_1_and_agents_section_6(tmp_path) -> None:
    (tmp_path / "HANDOVER.md").write_text(HANDOVER, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
    status = eve.gate_status(tmp_path)
    assert status["handover_status"] == "PRODUCTION_DEPLOYMENT_VERIFIED / GATE1_PASS / GATE2_PASS"
    assert [g["gate"] for g in status["gates"]] == ["1", "2", "4.5", "4.10"]  # numeric order, other sections ignored
    first, second, persona = status["gates"][0], status["gates"][1], status["gates"][2]
    assert first == {"gate": "1", "name": "Infrastructure & Crash/Retry Matrix", "result": "PASS (12/12 Verified)",
                     "date": "2026-09-07", "in_agents": True, "in_handover": True}
    assert second["handover_result"] == "FAIL"  # the two documents disagree
    assert persona["in_handover"] is False and persona["date"] == "2026-09-20"
    assert "10.0.0.1" not in json.dumps(status)


def test_gates_degrade_without_documents(tmp_path) -> None:
    assert eve.gate_status(tmp_path) is None
    (tmp_path / "HANDOVER.md").write_text(HANDOVER, encoding="utf-8")
    assert [g["gate"] for g in eve.gate_status(tmp_path)["gates"]] == ["1", "2"]


def _audit_line(event, ok, ts, **extra):
    return json.dumps({"timestamp": ts, "event_id": "e", "event": event, "ok": ok, **extra})


def test_audit_counts_events_failures_and_never_copies_contents(tmp_path) -> None:
    file = tmp_path / "discord-audit.jsonl"
    file.write_text("\n".join([
        _audit_line("rp_memory.saved", True, "2026-09-20T05:31:21.716Z", saved_count=2),
        _audit_line("rp_memory.parse_failed", False, "2026-09-20T06:00:00.000Z", snippet="SECRET DIALOGUE",
                    error={"message": "SECRET ERROR"}),
        _audit_line("manager.documents.settlement_failed", True, "2026-09-20T07:00:00.000Z"),
        _audit_line("manager.settings.changed", False, "2026-09-20T05:00:00.000Z", user_id="123456"),
        _audit_line("rp_memory.saved", True, "2026-09-20T17:19:07.570Z"),
        "{not json",
        "",
    ]) + "\n", encoding="utf-8")
    audit = eve.audit_summary(file)
    assert audit["total"] == 5 and audit["bad_lines"] == 1 and audit["truncated"] is False
    assert audit["events"][0] == {"event": "rp_memory.saved", "count": 2, "failed": 0}
    by_event = {e["event"]: e for e in audit["events"]}
    assert by_event["rp_memory.parse_failed"]["failed"] == 1
    assert by_event["manager.documents.settlement_failed"]["failed"] == 1  # `_failed` suffix even with ok:true
    assert by_event["manager.settings.changed"]["failed"] == 1  # ok:false
    assert audit["failures"] == 3 and audit["failure_ratio"] == 0.6
    assert audit["last_event_at"] == "2026-09-20T17:19:07+00:00"
    assert audit["last_failure_at"] == "2026-09-20T07:00:00+00:00"
    dumped = json.dumps(audit)
    assert "SECRET" not in dumped and "123456" not in dumped
    assert eve.audit_summary(tmp_path / "missing.jsonl") is None


def test_audit_reads_only_a_bounded_tail(tmp_path, monkeypatch) -> None:
    file = tmp_path / "discord-audit.jsonl"
    lines = [_audit_line("old.event", True, "2026-01-01T00:00:00Z")] * 50
    lines += [_audit_line("new.event", True, "2026-09-01T00:00:00Z")] * 3
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    window = len(_audit_line("new.event", True, "2026-09-01T00:00:00Z")) * 3 + 3 + 10  # 3 lines + a partial one
    monkeypatch.setattr(eve, "AUDIT_MAX_BYTES", window)
    audit = eve.audit_summary(file)
    assert audit["truncated"] is True and audit["bad_lines"] == 0  # the partial first line is skipped, not parsed
    assert [(e["event"], e["count"]) for e in audit["events"]] == [("new.event", 3)]


def test_session_state_ratio_and_statuses(tmp_path) -> None:
    file = tmp_path / "manager-session-state.json"
    file.write_text(json.dumps({
        "version": 1, "conversationId": "interaction-session", "lastStepIndex": 5, "pureDialogueChars": 1234,
        "threshold": 40000, "turnCount": 3, "bootedAt": None, "activeSettings": None,
        "rolloverState": {"status": "committed", "settlementId": "x", "completedAt": "2026-09-20T15:03:33.653Z"},
        "lastRollover": None,
        "lastDocumentRefresh": {"ok": True, "status": "committed", "completedAt": "2026-09-20T15:03:33.653Z"},
        "savedAt": "2026-09-20T15:03:33.655Z",
    }), encoding="utf-8")
    assert eve.session_summary(file) == {
        "chars": 1234, "threshold": 40000, "pct": 3.1, "turns": 3, "rollover_status": "committed",
        "doc_refresh_ok": True, "doc_refresh_at": "2026-09-20T15:03:33.653Z", "saved_at": "2026-09-20T15:03:33.655Z"}
    file.write_text("{broken", encoding="utf-8")
    assert eve.session_summary(file) == {"error": "unparseable"}
    file.write_text(json.dumps({"pureDialogueChars": 10, "threshold": 0}), encoding="utf-8")
    assert eve.session_summary(file)["pct"] is None
    assert eve.session_summary(tmp_path / "missing.json") is None


def test_sqlite_sizes_include_wal_without_opening_the_database(tmp_path) -> None:
    (tmp_path / "a.sqlite").write_bytes(b"x" * 4096)
    (tmp_path / "a.sqlite-wal").write_bytes(b"x" * 100)
    (tmp_path / "b.sqlite").write_bytes(b"not even a database")
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")
    files = eve.sqlite_files(tmp_path)
    assert [(f["name"], f["bytes"], f["wal_bytes"]) for f in files] == [("a.sqlite", 4096, 100), ("b.sqlite", 19, 0)]
    assert eve.sqlite_files(tmp_path / "missing") == []


# ---------------------------------------------------------------- git, against a small real repository
def _run(cwd, *args, date="2026-09-01T00:00:00+09:00"):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], check=True, env=env,
                   capture_output=True)


def _commit(repo, message, date):
    _run(repo, "commit", "-q", "--allow-empty", "-m", message, date=date)


def _make_repo(tmp_path):
    repo = tmp_path / "eve"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "main")
    _commit(repo, "base", "2026-09-01T00:00:00+09:00")
    _run(repo, "branch", "feature/all-tomorrow-edge")
    _commit(repo, "origin tip", "2026-09-02T00:00:00+09:00")
    _run(repo, "update-ref", "refs/remotes/origin/main", "HEAD")  # stands in for a fetched origin
    _commit(repo, "local only", "2026-09-03T00:00:00+09:00")
    _run(repo, "branch", "desktop/old", "HEAD~1")
    _run(repo, "checkout", "-q", "-b", "desktop/new")
    _commit(repo, "wip 1", "2026-10-19T17:00:00+09:00")
    _commit(repo, "wip 2", "2026-10-19T17:30:00+09:00")
    _run(repo, "checkout", "-q", "main")
    _run(repo, "worktree", "add", "-q", str(tmp_path / "edge-wt"), "feature/all-tomorrow-edge")
    _commit(tmp_path / "edge-wt", "edge work", "2026-09-04T00:00:00+09:00")
    return repo


def test_git_reads_local_refs_ahead_behind_and_edge_worktree(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    git = eve.collect(repo)["git"]
    assert git["main"]["ahead"] == 1 and git["main"]["behind"] == 0
    assert git["desktop"]["count"] == 2 and git["desktop"]["newest"] == "desktop/new"
    assert (git["desktop"]["ahead"], git["desktop"]["behind"]) == (2, 0)
    edge = git["edge"]
    assert (edge["ahead"], edge["behind"], edge["merged"]) == (1, 2, False)
    assert edge["worktree"] == {"name": "edge-wt", "missing": False}
    assert git["origin_fetched_at"] is None  # never fetched; we don't fetch either


def test_git_falls_back_when_ahead_behind_atom_is_unsupported(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    real = eve._git
    monkeypatch.setattr(eve, "_git", lambda path, *args: "" if any("ahead-behind" in a for a in args) else real(path, *args))
    git = eve.collect(repo)["git"]
    assert (git["main"]["ahead"], git["main"]["behind"]) == (1, 0)
    assert (git["edge"]["ahead"], git["edge"]["behind"], git["edge"]["merged"]) == (1, 2, False)
    assert git["desktop"]["newest"] == "desktop/new"


def test_merged_edge_branch_is_reported_as_merged(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    _run(repo, "merge", "-q", "--no-edit", "feature/all-tomorrow-edge", date="2026-09-05T00:00:00+09:00")
    assert eve.collect(repo)["git"]["edge"]["merged"] is True


def test_collect_only_runs_local_read_only_git_commands(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    calls = []
    real = eve._git
    monkeypatch.setattr(eve, "_git", lambda path, *args: calls.append(args) or real(path, *args))
    eve.collect(repo)
    assert {args[0] for args in calls} <= {"for-each-ref", "worktree", "rev-list"}
    assert all(args[:2] == ("worktree", "list") for args in calls if args[0] == "worktree")


def test_collect_on_an_empty_folder_degrades_and_fits_the_cap(tmp_path) -> None:
    panel = eve.collect(tmp_path)
    assert panel == {"status": None, "audit": None, "session": None, "sqlite": [], "git": None}
    assert len(json.dumps(panel).encode()) < PANEL_MAX_BYTES
