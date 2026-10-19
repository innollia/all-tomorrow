import hashlib
import json
import os
import sqlite3
from pathlib import Path

from all_tomorrow.project_panels import plugins, roblox_ugc

SECRET = "SECRET-FREE-TEXT"
SCHEMA = """
CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, category TEXT NOT NULL DEFAULT 'Back',
  brief TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'new', failed_from TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, kind TEXT NOT NULL,
  ref TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, from_state TEXT,
  to_state TEXT NOT NULL, note TEXT, at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE provider_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, provider TEXT NOT NULL,
  preset TEXT, provider_job_id TEXT, status TEXT NOT NULL, usage TEXT, error TEXT, local_path TEXT, format TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, job_id INTEGER,
  purchase_count INTEGER, favorite_count INTEGER, price INTEGER, rank INTEGER,
  taken_at TEXT NOT NULL DEFAULT (datetime('now')));
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "core").mkdir()
    # Deliberately not alphabetical, so the funnel order must come from this file.
    (tmp_path / "core" / "states.js").write_text(
        "export const STATES = [\n  'new', 'generated', 'approved',\n  'failed',\n];\nexport const X = ['zzz'];\n",
        encoding="utf-8")
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "factory.db")
    conn.executescript(SCHEMA)
    long_brief = "a very long brief " * 10
    conn.executemany("INSERT INTO jobs (id, category, brief, state, error, updated_at) VALUES (?,?,?,?,?,?)", [
        (1, "Back", long_brief, "generated", None, "2026-10-03 11:00:00"),
        (2, "Hat", "short one", "generated", None, "2026-10-03 10:00:00"),
        (3, "Back", "broken", "failed", SECRET, "2026-10-03 12:00:00"),
        (4, "Back", "odd", "legacy_state", None, "2026-10-03 12:00:00"),
    ])
    conn.executemany("INSERT INTO events (job_id, from_state, to_state, note, at) VALUES (?,?,?,?,?)",
                     [(1, None, "new", SECRET, f"2026-10-03 0{i}:00:00") for i in range(6)]
                     + [(3, "new", "failed", SECRET, "2026-10-03 09:00:00")])
    conn.executemany("INSERT INTO provider_jobs (job_id, provider, status, error) VALUES (?,?,?,?)", [
        (1, "hi3d", "success", None), (2, "hi3d", "failed", SECRET), (3, "hi3d", "submit_unknown", None),
        (1, "varco", "success", None)])
    conn.commit()
    conn.close()
    old = tmp_path / "data" / "prepared" / "1"
    new = tmp_path / "data" / "prepared" / "2"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "report.json").write_text(json.dumps({"triangle_count": 1, "vertex_count": 2}), encoding="utf-8")
    (new / "report_baked.json").write_text(
        json.dumps({"triangle_count": 3788, "vertex_count": 1897, "passed": True, "source_path": SECRET}),
        encoding="utf-8")
    (new / "notes.json").write_text("{}", encoding="utf-8")  # not a report
    os.utime(old / "report.json", (2_000_000_000, 2_000_000_000))
    os.utime(new / "report_baked.json", (2_000_000_100, 2_000_000_100))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "SPIKE_LOG.md").write_text(
        "# Spike log\n\n## 2026-10-02 Older\n\n## 2026-10-03 First\n## Findings\n## 2026-10-03 Gate PASS\n"
        "## 2026-09-30 Out of order\n", encoding="utf-8")
    return tmp_path


def _fingerprint(file: Path) -> tuple[int, int, str]:
    stat = file.stat()
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(file.read_bytes()).hexdigest()


def test_plugin_is_registered() -> None:
    assert plugins()["roblox-ugc-factory"] is roblox_ugc


def test_collects_funnel_triage_providers_report_spike_events(tmp_path) -> None:
    project = _project(tmp_path)
    db = project / "data" / "factory.db"
    before = _fingerprint(db)
    panel = roblox_ugc.collect(project)

    assert panel["states_source"] == "core/states.js"
    assert [(r["state"], r["count"]) for r in panel["funnel"]] == [
        ("new", 0), ("generated", 2), ("approved", 0), ("failed", 1), ("legacy_state", 1)]
    assert panel["jobs_total"] == 4 and panel["triage_total"] == 2
    assert [t["id"] for t in panel["triage"]] == [2, 1]  # oldest waiting first
    assert len(panel["triage"][1]["brief"]) <= 60 and panel["triage"][1]["brief"].endswith("…")
    assert panel["triage"][0]["updated_at"] == "2026-10-03T10:00:00Z"
    assert panel["providers"] == [{"provider": "hi3d", "success": 1, "failed": 1, "other": 1},
                                  {"provider": "varco", "success": 1, "failed": 0, "other": 0}]
    assert len(panel["events"]) == 5
    assert panel["events"][0] == {"job_id": 3, "from": "new", "to": "failed", "at": "2026-10-03T09:00:00Z"}
    assert panel["report"]["job"] == "2" and panel["report"]["file"] == "report_baked.json"
    assert (panel["report"]["triangle_count"], panel["report"]["vertex_count"], panel["report"]["passed"]) == (
        3788, 1897, True)
    assert panel["spike"] == {"date": "2026-10-03", "title": "Gate PASS"}
    assert panel["problems"] == []

    encoded = json.dumps(panel, ensure_ascii=False)
    assert SECRET not in encoded
    assert _fingerprint(db) == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["factory.db", "prepared"]  # no -wal/-shm/-journal


def test_report_without_verdict_is_unknown(tmp_path) -> None:
    job = tmp_path / "data" / "prepared" / "7"
    job.mkdir(parents=True)
    (job / "report.json").write_text(json.dumps({"triangle_count": 5, "vertex_count": "x", "status": "FAILED"}),
                                     encoding="utf-8")
    report = roblox_ugc.collect(tmp_path)["report"]
    assert report["triangle_count"] == 5 and report["vertex_count"] is None and report["passed"] is False
    (job / "report.json").write_text(json.dumps({"triangle_count": 5}), encoding="utf-8")
    assert roblox_ugc.collect(tmp_path)["report"]["passed"] is None


def test_missing_files_and_tables_degrade(tmp_path) -> None:
    panel = roblox_ugc.collect(tmp_path)
    assert panel["states_source"] == "fallback" and panel["report"] is None and panel["spike"] is None
    assert any("factory.db" in p for p in panel["problems"])

    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "factory.db")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, category TEXT, brief TEXT, state TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO jobs VALUES (1, 'Back', 'b', 'generated', '2026-10-03 00:00:00')")
    conn.commit()
    conn.close()
    panel = roblox_ugc.collect(tmp_path)
    assert panel["triage_total"] == 1 and "providers" not in panel and "events" not in panel
    assert {"provider_jobs 읽기 실패", "events 읽기 실패"} <= set(panel["problems"])

    (tmp_path / "data" / "prepared" / "1").mkdir(parents=True)
    (tmp_path / "data" / "prepared" / "1" / "report.json").write_text("{not json", encoding="utf-8")
    panel = roblox_ugc.collect(tmp_path)
    assert panel["report"]["job"] == "1" and "triangle_count" not in panel["report"]
    assert any("리포트" in p for p in panel["problems"])
