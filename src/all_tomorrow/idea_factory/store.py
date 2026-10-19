"""Application state of the idea factory (topics, ideas, council, proposals, staff, audit).

DBOS keeps the execution journal in its own system database; this store holds the
user-facing records. Writes from workflow steps use deterministic ids so a replayed
step overwrites instead of duplicating.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
  finished_at TEXT);
CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, idx INTEGER NOT NULL, title TEXT NOT NULL,
  problem TEXT, approach TEXT, status TEXT NOT NULL, ideator_id TEXT,
  synth_id TEXT, evidence TEXT, verdict_reason TEXT, review TEXT, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS council (
  idea_id TEXT NOT NULL, round INTEGER NOT NULL, staff_id TEXT NOT NULL, stance TEXT NOT NULL,
  reason TEXT, PRIMARY KEY (idea_id, round, staff_id));
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, idea_id TEXT NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS staff (
  id TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL, model_group TEXT NOT NULL,
  generation INTEGER NOT NULL, status TEXT NOT NULL, hired_at TEXT NOT NULL, retired_at TEXT,
  changed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, topic_id TEXT, staff_id TEXT,
  kind TEXT NOT NULL, text TEXT NOT NULL, dedupe TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL);
"""

LOOP_STATES = ("RUN", "PAUSED", "KILLED")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, args)

    def _rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._exec(sql, args).fetchall()]

    # control ---------------------------------------------------------------
    def loop_state(self) -> str:
        row = self._exec("SELECT value FROM control WHERE key='loop'").fetchone()
        return row["value"] if row else "RUN"

    def set_loop_state(self, state: str, actor: str) -> None:
        if state not in LOOP_STATES:
            raise ValueError(f"loop state must be one of {LOOP_STATES}")
        self._exec("INSERT INTO control (key, value) VALUES ('loop', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (state,))
        self.audit(actor, "loop_state", {"state": state})

    # topics ----------------------------------------------------------------
    def add_topic(self, topic_id: str, text: str) -> None:
        self._exec("INSERT INTO topics (id, text, created_at, status) VALUES (?, ?, ?, 'RUNNING')",
                   (topic_id, text, now()))

    def set_topic_status(self, topic_id: str, status: str) -> None:
        self._exec("UPDATE topics SET status=?, finished_at=? WHERE id=?", (status, now(), topic_id))

    def topics(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM topics ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in rows:
            counts = self._rows("SELECT status, COUNT(*) n FROM ideas WHERE topic_id=? GROUP BY status", (row["id"],))
            row["idea_counts"] = {c["status"]: c["n"] for c in counts}
        return rows

    def topic(self, topic_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM topics WHERE id=?", (topic_id,))
        return rows[0] if rows else None

    # ideas -----------------------------------------------------------------
    def put_idea(self, idea: dict[str, Any]) -> None:
        self._exec("INSERT INTO ideas (id, topic_id, idx, title, problem, approach, status, ideator_id) "
                   "VALUES (:id, :topic_id, :idx, :title, :problem, :approach, 'GENERATED', :ideator_id) "
                   "ON CONFLICT(id) DO UPDATE SET title=excluded.title, problem=excluded.problem, "
                   "approach=excluded.approach", idea)

    def set_idea_verdict(self, idea_id: str, status: str, *, synth_id: str | None = None,
                         evidence: list[dict[str, Any]] | None = None, reason: str | None = None) -> None:
        self._exec("UPDATE ideas SET status=?, synth_id=COALESCE(?, synth_id), "
                   "evidence=COALESCE(?, evidence), verdict_reason=COALESCE(?, verdict_reason) WHERE id=?",
                   (status, synth_id, json.dumps(evidence, ensure_ascii=False) if evidence is not None else None,
                    reason, idea_id))

    def ideas(self, topic_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM ideas WHERE 1=1", []
        if topic_id:
            sql += " AND topic_id=?"; args.append(topic_id)
        if status:
            sql += " AND status=?"; args.append(status)
        rows = self._rows(sql + " ORDER BY rowid DESC LIMIT ?", (*args, limit))
        for row in rows:
            row["evidence"] = json.loads(row["evidence"]) if row["evidence"] else []
        return rows

    def idea(self, idea_id: str) -> dict[str, Any] | None:
        rows = [r for r in self.ideas(limit=100000) if r["id"] == idea_id]
        return rows[0] if rows else None

    def review_kill(self, idea_id: str, verdict: str, actor: str) -> None:
        if verdict not in ("correct", "overkill"):
            raise ValueError("verdict must be correct or overkill")
        idea = self.idea(idea_id)
        if not idea or idea["status"] != "KILLED":
            raise ValueError("only killed ideas can be reviewed")
        self._exec("UPDATE ideas SET review=?, reviewed_at=? WHERE id=?", (verdict, now(), idea_id))
        self.audit(actor, "kill_review", {"idea_id": idea_id, "verdict": verdict})

    # council ---------------------------------------------------------------
    def put_vote(self, idea_id: str, round_no: int, staff_id: str, stance: str, reason: str) -> None:
        self._exec("INSERT INTO council VALUES (?, ?, ?, ?, ?) ON CONFLICT(idea_id, round, staff_id) "
                   "DO UPDATE SET stance=excluded.stance, reason=excluded.reason",
                   (idea_id, round_no, staff_id, stance, reason))

    def votes(self, idea_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM council WHERE idea_id=? ORDER BY round, staff_id", (idea_id,))

    # proposals -------------------------------------------------------------
    def put_proposal(self, proposal_id: str, topic_id: str, idea_id: str, body: dict[str, Any]) -> None:
        self._exec("INSERT INTO proposals (id, topic_id, idea_id, body, status, created_at) "
                   "VALUES (?, ?, ?, ?, 'PENDING', ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                   (proposal_id, topic_id, idea_id, json.dumps(body, ensure_ascii=False), now()))

    def proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT p.*, t.text AS topic FROM proposals p JOIN topics t ON t.id=p.topic_id"
        rows = self._rows(sql + (" WHERE p.status=?" if status else "") + " ORDER BY p.created_at DESC",
                          (status,) if status else ())
        for row in rows:
            row["body"] = json.loads(row["body"])
        return rows

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        rows = [p for p in self.proposals() if p["id"] == proposal_id]
        return rows[0] if rows else None

    def decide_proposal(self, proposal_id: str, decision: str, reason: str, actor: str) -> None:
        if decision not in ("APPROVED", "REJECTED"):
            raise ValueError("decision must be APPROVED or REJECTED")
        cursor = self._exec("UPDATE proposals SET status=?, decided_at=?, reason=? WHERE id=?",
                            (decision, now(), reason, proposal_id))
        if cursor.rowcount == 0:
            raise ValueError("unknown proposal")
        self.audit(actor, "proposal_decision", {"proposal_id": proposal_id, "decision": decision, "reason": reason})

    # staff -----------------------------------------------------------------
    def hire(self, role: str, name: str, model_group: str, generation: int = 1) -> str:
        staff_id = f"{role}-g{generation}"
        stamp = now()
        self._exec("INSERT OR IGNORE INTO staff VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, NULL, ?)",
                   (staff_id, role, name, model_group, generation, stamp, stamp))
        return staff_id

    def staff(self, include_retired: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM staff" + ("" if include_retired else " WHERE status='ACTIVE'")
        return self._rows(sql + " ORDER BY role, generation")

    def active_staff(self, role: str) -> dict[str, Any]:
        rows = self._rows("SELECT * FROM staff WHERE role=? AND status='ACTIVE' ORDER BY generation DESC", (role,))
        if not rows:
            raise LookupError(f"no active staff for role {role}")
        return rows[0]

    def set_staff_group(self, staff_id: str, model_group: str) -> None:
        self._exec("UPDATE staff SET model_group=?, changed_at=? WHERE id=?", (model_group, now(), staff_id))

    def retire(self, staff_id: str) -> None:
        self._exec("UPDATE staff SET status='RETIRED', retired_at=? WHERE id=?", (now(), staff_id))

    # events / audit --------------------------------------------------------
    def event(self, kind: str, text: str, *, topic_id: str | None = None, staff_id: str | None = None,
              dedupe: str | None = None) -> None:
        self._exec("INSERT OR IGNORE INTO events (ts, topic_id, staff_id, kind, text, dedupe) VALUES (?, ?, ?, ?, ?, ?)",
                   (now(), topic_id, staff_id, kind, text, dedupe))

    def events(self, limit: int = 50, topic_id: str | None = None) -> list[dict[str, Any]]:
        if topic_id:
            return self._rows("SELECT * FROM events WHERE topic_id=? ORDER BY id DESC LIMIT ?", (topic_id, limit))
        return self._rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    def audit(self, actor: str, action: str, detail: dict[str, Any]) -> None:
        self._exec("INSERT INTO audit (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
                   (now(), actor, action, json.dumps(detail, ensure_ascii=False)))

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["detail"] = json.loads(row["detail"])
        return rows
