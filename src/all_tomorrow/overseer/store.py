"""Local store of condensed, redacted sessions (outside the repo: it holds chat text)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from all_tomorrow.overseer.sources import Session

_SCHEMA = """
create table if not exists sessions (
    source       text not null,
    session_id   text not null,
    fingerprint  text not null,
    parent_id    text,
    cwd          text,
    project      text,
    title        text,
    agent        text,
    models       text,
    started_at   text,
    updated_at   text,
    n_user       integer,
    n_agent      integer,
    n_errors     integer,
    text         text,
    collected_at text not null,
    primary key (source, session_id)
);
create index if not exists sessions_project on sessions(project);
create index if not exists sessions_updated on sessions(updated_at);
"""


def default_dir() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_OVERSEER_DIR")
                or Path(os.path.expanduser("~")) / ".all-tomorrow" / "overseer")


def host_name() -> str:
    import socket
    return re.sub(r"[^A-Za-z0-9_-]", "_", socket.gethostname()) or "host"


def peers_dir(base: Path) -> Path:
    """~/.all-tomorrow/peers: the Syncthing folder all-tomorrow-secrets carries only this and the key pool."""
    return base.parent / "peers"


def peer_paths(base: Path) -> list[Path]:
    """Other PCs' published stores."""
    own = f"{host_name()}.sqlite"
    return sorted(p for p in peers_dir(base).glob("*.sqlite") if p.name != own)


def open_peer(path: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:" + str(path).replace("\\", "/") + "?mode=ro", uri=True, timeout=10)


class SessionStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, timeout=120)
        self.con.execute("pragma journal_mode=wal")
        self.con.executescript(_SCHEMA)

    def fingerprints(self, source: str) -> dict[str, str]:
        return dict(self.con.execute("select session_id, fingerprint from sessions where source=?", (source,)))

    def put(self, s: Session, fingerprint: str, redact) -> None:
        self.con.execute(
            "insert or replace into sessions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.source, s.session_id, fingerprint, s.parent_id, s.cwd, s.project, redact(s.title), s.agent,
             json.dumps(sorted(s.models)), s.started_at, s.updated_at, s.n_user, s.n_agent, s.n_errors,
             redact(s.text), datetime.now(timezone.utc).isoformat()))

    def commit(self) -> None:
        self.con.commit()

    def stats(self) -> list[tuple]:
        return self.con.execute(
            "select source, count(*), sum(parent_id is not null), sum(n_user), sum(n_errors), "
            "sum(length(text)) from sessions group by source order by source").fetchall()

    def publish(self, base: Path) -> Path:
        """Write a consistent copy for the other PC (peers/<host>.sqlite, swapped in atomically)."""
        peers = peers_dir(base)
        peers.mkdir(parents=True, exist_ok=True)
        target = peers / f"{host_name()}.sqlite"
        tmp = peers / f".{host_name()}.sqlite.tmp"
        tmp.unlink(missing_ok=True)
        out = sqlite3.connect(tmp)
        try:
            self.con.backup(out)
        finally:
            out.close()
        os.replace(tmp, target)
        return target

    def close(self) -> None:
        self.con.close()
