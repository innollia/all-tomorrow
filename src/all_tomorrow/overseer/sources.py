"""Read the session logs of each coding agent on this PC into one shape.

Each source lists its sessions cheaply (id + fingerprint) so the collector can
skip unchanged ones, and loads one session into a condensed transcript:

    [U] user message            [A] agent's visible text
    [T] tool call (name + input head)
    [E] failed tool output (head + tail)

Successful tool output, thinking, images and injected context are dropped: the
distiller only needs what was asked, what was tried, what failed and the answer.
All stores are opened read-only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

MAX_MESSAGE = 2000
MAX_TOOL_INPUT = 200
ERROR_HEAD = 400
ERROR_TAIL = 400

# Narrow on purpose: ordinary output that merely mentions "error" is not a failure.
_FAILED_OUTPUT = re.compile(
    r"Traceback \(most recent call last\)|Exit code:? [1-9]|exit code [1-9]|\"exit_code\":\s*[1-9]"
    r"|^(?:error|fatal|ERROR|FATAL)\b", re.M)
_INJECTED = re.compile(r"<(system-reminder|environment_context|user_instructions|local-command-[a-z]+|command-[a-z]+)>"
                       r"[\s\S]*?</\1>")


@dataclass
class Session:
    source: str
    session_id: str
    cwd: str = ""
    title: str = ""
    parent_id: str | None = None
    models: set[str] = field(default_factory=set)
    agent: str = ""
    started_at: str = ""
    updated_at: str = ""
    lines: list[str] = field(default_factory=list)
    n_user: int = 0
    n_agent: int = 0
    n_errors: int = 0

    def user(self, text: str) -> None:
        text = _INJECTED.sub("", text or "").strip()
        if text:
            self.lines.append("[U] " + _clip(text, MAX_MESSAGE))
            self.n_user += 1

    def said(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.lines.append("[A] " + _clip(text, MAX_MESSAGE))
            self.n_agent += 1

    def tool(self, name: str, tool_input: object) -> None:
        if not isinstance(tool_input, str):
            tool_input = json.dumps(tool_input, ensure_ascii=False)
        self.lines.append(f"[T] {name}: " + _clip(" ".join(tool_input.split()), MAX_TOOL_INPUT))

    def failed(self, output: object) -> None:
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False)
        output = output.strip()
        if len(output) > ERROR_HEAD + ERROR_TAIL:
            output = output[:ERROR_HEAD] + " … " + output[-ERROR_TAIL:]
        self.lines.append("[E] " + output)
        self.n_errors += 1

    def stamp(self, when: str) -> None:
        if when:
            self.started_at = min(self.started_at or when, when)
            self.updated_at = max(self.updated_at, when)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def project(self) -> str:
        return project_of(self.cwd)


@dataclass(frozen=True)
class Listing:
    source: str
    session_id: str
    fingerprint: str
    load: Callable[[], Session]


def project_of(cwd: str) -> str:
    parts = [p for p in re.split(r"[\\/]+", cwd or "") if p]
    lowered = [p.lower() for p in parts]
    if "projects" in lowered:
        i = lowered.index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else ""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …"


def _ms(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _file_fingerprint(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def _jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:" + str(path).replace("\\", "/") + "?mode=ro", uri=True)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c) for c in content)
    if isinstance(content, dict):
        for key in ("text", "content", "output"):
            if key in content:
                return _text_of(content[key])
    return ""


# ---------------------------------------------------------------- Claude Code

def claude_sessions(root: Path) -> Iterator[Listing]:
    for path in sorted(root.glob("*/*.jsonl")) + sorted(root.glob("*/*/subagents/*.jsonl")):
        parent = path.parent.parent.name if path.parent.name == "subagents" else None
        sid = f"{parent}/{path.stem}" if parent else path.stem
        yield Listing("claude", sid, _file_fingerprint(path),
                      lambda p=path, s=sid, par=parent: _load_claude(p, s, par))


def _load_claude(path: Path, sid: str, parent: str | None) -> Session:
    s = Session("claude", sid, parent_id=parent, agent="claude-code")
    for d in _jsonl(path):
        kind = d.get("type")
        if kind in ("custom-title", "summary"):
            s.title = d.get("customTitle") or d.get("summary") or s.title
            continue
        if kind not in ("user", "assistant"):
            continue
        s.cwd = d.get("cwd") or s.cwd
        s.stamp(d.get("timestamp", ""))
        msg = d.get("message") or {}
        content = msg.get("content")
        if kind == "user":
            if d.get("isMeta"):
                continue
            if isinstance(content, str):
                s.user(content)
                continue
            for block in content or []:
                if block.get("type") == "text":
                    s.user(block.get("text", ""))
                elif block.get("type") == "tool_result" and block.get("is_error"):
                    s.failed(_text_of(block.get("content")))
        else:
            if msg.get("model") and not msg["model"].startswith("<"):
                s.models.add(msg["model"])
            for block in content or []:
                if block.get("type") == "text":
                    s.said(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    s.tool(block.get("name", "?"), block.get("input", {}))
    return s


# ---------------------------------------------------------------------- Codex

def codex_sessions(root: Path) -> Iterator[Listing]:
    for path in sorted(root.rglob("*.jsonl")):
        sid = path.stem.rsplit("-", 5)[-5:]
        sid = "-".join(sid) if len(sid) == 5 else path.stem
        yield Listing("codex", sid, _file_fingerprint(path), lambda p=path, s=sid: _load_codex(p, s))


def _load_codex(path: Path, sid: str) -> Session:
    s = Session("codex", sid, agent="codex")
    for d in _jsonl(path):
        kind, p = d.get("type"), d.get("payload") or {}
        s.stamp(d.get("timestamp", ""))
        if kind == "session_meta":
            s.cwd = p.get("cwd") or s.cwd
        elif kind == "turn_context":
            s.cwd = p.get("cwd") or s.cwd
            if p.get("model"):
                s.models.add(p["model"])
        elif kind == "event_msg" and p.get("type") == "thread_name_updated":
            s.title = p.get("thread_name") or s.title
        elif kind == "response_item":
            t = p.get("type")
            if t == "message" and p.get("role") == "user":
                s.user(_text_of(p.get("content")))
            elif t == "message" and p.get("role") == "assistant":
                s.said(_text_of(p.get("content")))
            elif t in ("function_call", "custom_tool_call"):
                s.tool(p.get("name", "?"), p.get("arguments") or p.get("input") or "")
            elif t in ("function_call_output", "custom_tool_call_output"):
                out = _text_of(p.get("output"))
                if _FAILED_OUTPUT.search(out):
                    s.failed(out)
    return s


# ------------------------------------------------------------------- OpenCode

def opencode_sessions(db: Path) -> Iterator[Listing]:
    if not db.is_file():
        return
    con = _ro(db)
    try:
        # Older OpenCode builds have no session_v2 table.
        has_v2 = con.execute("select 1 from sqlite_master where type='table' and name='session_v2'").fetchone()
        sql = "select id, time_updated, 'v1' from session"
        if has_v2:
            sql += (" union all select id, time_updated, 'v2' from session_v2 "
                    "where id not in (select id from session)")
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    for sid, updated, kind in rows:
        yield Listing("opencode", sid, str(updated), lambda s=sid, k=kind: _load_opencode(db, s, k))


def _load_opencode(db: Path, sid: str, kind: str) -> Session:
    con = _ro(db)
    try:
        table = "session" if kind == "v1" else "session_v2"
        row = con.execute(f"select parent_id, directory, title, agent, model, time_created, time_updated "
                          f"from {table} where id=?", (sid,)).fetchone()
        s = Session("opencode", sid, agent="opencode")
        if row:
            s.parent_id, s.cwd, s.title, agent, model, created, updated = row
            s.agent = f"opencode:{agent}" if agent else "opencode"
            s.stamp(_ms(created))
            s.stamp(_ms(updated))
            if model:
                try:
                    s.models.add(json.loads(model).get("id", ""))
                except (json.JSONDecodeError, AttributeError):
                    s.models.add(str(model))
        if kind == "v1":
            _opencode_v1(con, s)
        else:
            _opencode_v2(con, s)
        s.models.discard("")
        return s
    finally:
        con.close()


def _opencode_v1(con: sqlite3.Connection, s: Session) -> None:
    roles = {}
    for mid, data in con.execute("select id, data from message where session_id=? order by time_created",
                                 (s.session_id,)):
        info = json.loads(data)
        roles[mid] = info.get("role")
        if info.get("modelID"):
            s.models.add(info["modelID"])
    # File parts carry whole images as data URLs; skip them without decoding.
    for mid, data in con.execute(
            "select message_id, data from part where session_id=? and substr(data, 1, 30) not like '%\"file\"%' "
            "order by time_created", (s.session_id,)):
        part = json.loads(data)
        t = part.get("type")
        if t == "text" and not part.get("synthetic"):
            (s.user if roles.get(mid) == "user" else s.said)(part.get("text", ""))
        elif t == "tool":
            state = part.get("state") or {}
            s.tool(part.get("tool", "?"), state.get("input", {}))
            exit_code = (state.get("metadata") or {}).get("exit")
            if state.get("status") == "error":
                s.failed(state.get("error", ""))
            elif isinstance(exit_code, int) and exit_code != 0:
                s.failed(state.get("output", ""))


def _opencode_v2(con: sqlite3.Connection, s: Session) -> None:
    for kind, data in con.execute("select type, data from session_message where session_id=? order by seq",
                                  (s.session_id,)):
        d = json.loads(data)
        if kind == "user":
            s.user(d.get("text", ""))
        elif kind == "assistant":
            s.said(_text_of(d.get("content")))
            if d.get("error"):
                s.failed(d["error"])
        elif kind == "idle" and d.get("error"):
            s.failed(d["error"])


# ----------------------------------------------------------------------- Kiro

def kiro_sessions(root: Path) -> Iterator[Listing]:
    for meta in sorted(root.glob("*.json")):
        log = meta.with_suffix(".jsonl")
        fp = _file_fingerprint(meta) + ("|" + _file_fingerprint(log) if log.is_file() else "")
        yield Listing("kiro", meta.stem, fp, lambda m=meta, lg=log: _load_kiro(m, lg))


def _load_kiro(meta: Path, log: Path) -> Session:
    info = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
    s = Session("kiro", info.get("session_id", meta.stem), cwd=info.get("cwd", ""),
                title=info.get("title") or "", agent="kiro")
    state = info.get("session_state") or {}
    s.agent = f"kiro:{state['agent_name']}" if state.get("agent_name") else "kiro"
    model = ((state.get("rts_model_state") or {}).get("model_info") or {}).get("model_id")
    if model:
        s.models.add(model)
    if info.get("session_created_reason") == "subagent":
        s.parent_id = "subagent"
    s.stamp(info.get("created_at", ""))
    s.stamp(info.get("updated_at", ""))
    if not log.is_file():
        return s
    for d in _jsonl(log):
        kind, data = d.get("kind"), d.get("data") or {}
        for c in data.get("content") or []:
            ck, cd = c.get("kind"), c.get("data")
            if ck == "text":
                (s.user if kind == "Prompt" else s.said)(cd if isinstance(cd, str) else _text_of(cd))
            elif ck == "toolUse" and isinstance(cd, dict):
                s.tool(cd.get("name", "?"), cd.get("input", cd.get("args", {})))
        for result in (data.get("results") or {}).values():
            res = result.get("result") if isinstance(result, dict) else result
            if isinstance(res, dict):
                status = str(res.get("status", "")).lower()
                if status in ("error", "failed", "failure") or res.get("error"):
                    s.failed(res.get("error") or _text_of(res))
            elif _FAILED_OUTPUT.search(_text_of(res)):
                s.failed(_text_of(res))
    return s


# ---------------------------------------------------------------- Antigravity

def antigravity_sessions(summaries_db: Path) -> Iterator[Listing]:
    if not summaries_db.is_file():
        return
    con = _ro(summaries_db)
    try:
        rows = con.execute("select conversation_id, last_modified_time, step_count "
                           "from conversation_summaries").fetchall()
    finally:
        con.close()
    for cid, modified, steps in rows:
        yield Listing("antigravity", cid, f"{modified}:{steps}", lambda c=cid: _load_antigravity(summaries_db, c))


def _load_antigravity(db: Path, cid: str) -> Session:
    con = _ro(db)
    try:
        title, modified, workspaces, agent, parent = con.execute(
            "select title, last_modified_time, workspace_uris, agent_name, parent_conversation_id "
            "from conversation_summaries where conversation_id=?", (cid,)).fetchone()
        s = Session("antigravity", cid, title=title or "", parent_id=parent or None,
                    agent=f"antigravity:{agent}" if agent else "antigravity")
        s.cwd = _first_workspace(workspaces)
        s.stamp(str(modified or ""))
        # The local search index is the only plain-text copy; step payloads are protobuf.
        for user_body, agent_body in con.execute(
                "select user_body, agent_body from conversations_fts where conversation_id=? "
                "order by cast(chunk_index as integer)", (cid,)):
            s.user(user_body)
            s.said(agent_body)
        return s
    finally:
        con.close()


def _first_workspace(raw: object) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    match = re.search(r"file:///?([^\"'\],\s]+)", text)
    if not match:
        return text.strip("[]\" ")
    from urllib.parse import unquote
    return unquote(match.group(1))


# --------------------------------------------------------------------- roots

@dataclass(frozen=True)
class Roots:
    claude: Path
    codex: Path
    opencode_db: Path
    kiro: Path
    antigravity_db: Path

    @classmethod
    def default(cls, home: Path | None = None) -> "Roots":
        home = home or Path(os.path.expanduser("~"))
        return cls(
            claude=home / ".claude" / "projects",
            codex=home / ".codex" / "sessions",
            opencode_db=home / ".local" / "share" / "opencode" / "opencode.db",
            kiro=home / ".kiro" / "sessions" / "cli",
            antigravity_db=home / ".gemini" / "antigravity" / "conversation_summaries.db",
        )

    def listings(self) -> dict[str, Callable[[], Iterator[Listing]]]:
        return {
            "claude": lambda: claude_sessions(self.claude),
            "codex": lambda: codex_sessions(self.codex),
            # OpenCode is no longer collected (user, 2026-10-20: "오픈코드는 버려"); the adapter stays for reuse.
            "kiro": lambda: kiro_sessions(self.kiro),
            "antigravity": lambda: antigravity_sessions(self.antigravity_db),
        }
