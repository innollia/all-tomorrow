import hashlib
import json
import os
import sqlite3
import shutil
from pathlib import Path

from all_tomorrow.project_panels import plugins, survey_copilot

SECRET = "SECRET-FREE-TEXT"
SCHEMA = """
CREATE TABLE IF NOT EXISTS platforms (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
  policy TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS offers (id INTEGER PRIMARY KEY AUTOINCREMENT, platform_id TEXT, title TEXT NOT NULL,
  url TEXT, reward_krw REAL, minutes REAL, deadline TEXT, provider TEXT, fingerprint TEXT, dup_of INTEGER,
  p_qualify REAL, is_offer REAL, status TEXT NOT NULL DEFAULT 'new', actual_minutes REAL, raw TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, platform_id TEXT NOT NULL, offer_id INTEGER,
  kind TEXT NOT NULL, amount_krw REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS copilot_sessions (id TEXT PRIMARY KEY, offer_id INTEGER, question TEXT NOT NULL,
  options TEXT, jev TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
"""


def _fill(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO platforms (id, name, kind, policy, notes) VALUES (?,?,?,?,?)", [
        ("pp", "패널파워", "panel", "manual", SECRET), ("pr", "Prolific", "research", "manual", SECRET)])
    offer = ("INSERT INTO offers (platform_id, title, url, raw, reward_krw, minutes, p_qualify, deadline, status, dup_of)"
             " VALUES (?,?,?,?,?,?,?,?,?,?)")
    conn.executemany(offer, [
        ("pp", SECRET, SECRET, SECRET, 1000, 10, 0.5, "2026-10-30", "new", None),   # 50/min
        ("pr", SECRET, SECRET, SECRET, 3000, 10, 0.9, None, "new", None),           # 270/min
        ("pp", SECRET, SECRET, SECRET, 500, 5, 0.2, None, "new", None),             # 20/min
        ("pr", SECRET, SECRET, SECRET, 2000, 20, 0.9, None, "new", None),           # 90/min
        ("pr", SECRET, SECRET, SECRET, 99999, 1, 1.0, None, "new", 2),              # duplicate: ignored
        ("pp", SECRET, SECRET, SECRET, 5000, None, 0.9, None, "new", None),         # unscored
        ("pp", SECRET, SECRET, SECRET, 1000, 10, 0.5, None, "approved", None),
        ("pp", SECRET, SECRET, SECRET, 1000, 10, 0.5, None, "odd_status", None),
    ])
    ledger = "INSERT INTO ledger (platform_id, kind, amount_krw, note, created_at) VALUES (?,?,?,?,{})"
    conn.executemany(ledger.format("datetime('now','localtime','-1 day')"),
                     [("pp", "earned", 1000, SECRET), ("pp", "approved", 700, SECRET)])
    conn.executemany(ledger.format("datetime('now','localtime','-60 days')"),
                     [("pp", "earned", 5000, SECRET), ("pp", "paid", 4000, SECRET)])
    conn.execute("INSERT INTO profile (id, notes) VALUES (1, ?)", (SECRET,))
    conn.execute("INSERT INTO copilot_sessions (id, question) VALUES ('s1', ?)", (SECRET,))
    conn.commit()


def _bridge(project: Path) -> None:
    for box in ("inbox", "outbox"):
        (project / "bridge" / box).mkdir(parents=True)
        (project / "bridge" / box / ".gitkeep").write_text("", encoding="utf-8")
    for name in ("a.json", "b.json", "c.json"):
        (project / "bridge" / "inbox" / name).write_text(json.dumps({"profile": SECRET}), encoding="utf-8")
    (project / "bridge" / "outbox" / "a.json").write_text("{}", encoding="utf-8")


def _fingerprints(db: Path) -> dict[str, tuple[int, int, str]]:
    out = {}
    for file in sorted(db.parent.iterdir()):
        stat = file.stat()
        out[file.name] = (stat.st_size, stat.st_mtime_ns, hashlib.sha256(file.read_bytes()).hexdigest())
    return out


def _check(panel: dict) -> None:
    assert panel["db"] is True and panel["note"] is None and panel["problems"] == []
    counts = {r["status"]: r["count"] for r in panel["statuses"]}
    assert [r["status"] for r in panel["statuses"]][:7] == list(survey_copilot.STATUS_ORDER)
    assert counts["new"] == 5 and counts["approved"] == 1 and counts["odd_status"] == 1 and counts["skipped"] == 0
    assert panel["offers_total"] == 7 and panel["duplicates"] == 1
    assert [(o["platform"], o["krw_per_min"]) for o in panel["top_new"]] == [
        ("Prolific", 270.0), ("Prolific", 90.0), ("패널파워", 50.0)]
    assert panel["top_new"][2] == {"platform": "패널파워", "reward_krw": 1000, "minutes": 10, "p_qualify": 0.5,
                                   "deadline": "2026-10-30", "krw_per_min": 50.0}
    assert panel["unscored_new"] == 1
    assert panel["ledger"] == {"earned": {"entries": 2, "all_krw": 6000, "d30_krw": 1000},
                               "approved": {"entries": 1, "all_krw": 700, "d30_krw": 700},
                               "paid": {"entries": 1, "all_krw": 4000, "d30_krw": 0}}
    assert SECRET not in json.dumps(panel, ensure_ascii=False)


def test_plugin_is_registered() -> None:
    assert plugins()["survey-copilot"] is survey_copilot


def test_rollback_journal_db_and_bridge_queue(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "copilot.db")
    _fill(conn)
    conn.close()
    _bridge(tmp_path)
    before = _fingerprints(tmp_path / "data" / "copilot.db")
    panel = survey_copilot.collect(tmp_path)
    _check(panel)
    assert panel["bridge"]["requests"] == 3 and panel["bridge"]["pending"] == 2
    assert panel["bridge"]["oldest_pending_at"]
    assert _fingerprints(tmp_path / "data" / "copilot.db") == before


def _immutable_count(db: Path) -> int | str:
    """What a reader that ignores the WAL would see."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?immutable=1", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM offers").fetchone()[0]
    except sqlite3.Error as error:
        return str(error)
    finally:
        conn.close()


def test_wal_data_with_live_writer_is_visible(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "copilot.db"
    writer = sqlite3.connect(db)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        _fill(writer)
        assert "no such table" in str(_immutable_count(db))  # the rows are only in copilot.db-wal
        panel = survey_copilot.collect(tmp_path)
        _check(panel)
        assert panel["bridge"] is None
    finally:
        writer.close()


def test_orphaned_wal_is_read_without_touching_any_db_file(tmp_path) -> None:
    """The app stopped without a checkpoint: data lives only in -wal and nobody holds the DB open."""
    live, orphan = tmp_path / "live", tmp_path / "orphan" / "data"
    live.mkdir()
    orphan.mkdir(parents=True)
    writer = sqlite3.connect(live / "copilot.db")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        _fill(writer)
        for name in ("copilot.db", "copilot.db-wal", "copilot.db-shm"):  # copy before close() checkpoints
            shutil.copy2(live / name, orphan / name)
    finally:
        writer.close()
    db = orphan / "copilot.db"
    assert db.with_name("copilot.db-wal").stat().st_size > 0
    assert "no such table" in str(_immutable_count(db))
    before = _fingerprints(db)
    _check(survey_copilot.collect(orphan.parent))
    _check(survey_copilot.collect(orphan.parent))
    assert _fingerprints(db) == before


def test_missing_db_or_schema_is_explained(tmp_path) -> None:
    panel = survey_copilot.collect(tmp_path)
    assert panel["db"] is False and "copilot.db 없음" in panel["note"] and panel["bridge"] is None
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "copilot.db")
    conn.execute("CREATE TABLE platforms (id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    panel = survey_copilot.collect(tmp_path)
    assert panel["db"] is True and panel["note"] == "스키마 없음: offers, ledger"
    assert "statuses" not in panel and "ledger" not in panel
    os.remove(tmp_path / "data" / "copilot.db")
    (tmp_path / "data" / "copilot.db").write_bytes(b"not a database at all" * 100)
    panel = survey_copilot.collect(tmp_path)
    assert panel["note"] == "data/copilot.db를 열 수 없음"
