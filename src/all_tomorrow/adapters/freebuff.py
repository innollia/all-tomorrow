"""Freebuff worker: drives the interactive freebuff CLI in a pseudo console.

freebuff has no print/headless mode, so the adapter types the task into its TUI and reads the
answer from the chat files the CLI writes (~/.config/manicode/projects/<cwd name>/chats/<stamp>/).
A turn is finished when that chat's log.jsonl records "Main prompt finished"; the reply is the
assistant text of run-state.json's lastMessage.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from all_tomorrow.contracts import WorkerRequest, WorkerResult, WorkerStatus

CHATS_ROOT = Path.home() / ".config" / "manicode" / "projects"
READY_MARK = "Enter a coding task"
LOGIN_MARK = "to login"
FINISHED_MARK = '"Main prompt finished"'
COLS, ROWS = 200, 50


def default_executable() -> str | None:
    candidate = Path.home() / ".config" / "manicode" / ("freebuff.exe" if os.name == "nt" else "freebuff")
    return str(candidate) if candidate.is_file() else None


def chat_dirs(cwd: Path) -> set[str]:
    folder = CHATS_ROOT / cwd.name / "chats"
    return {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()


def submitted(cwd: Path, before: set[str]) -> bool:
    return any((CHATS_ROOT / cwd.name / "chats" / name / "chat-messages.json").is_file()
               for name in chat_dirs(cwd) - before)


def finished_chat(cwd: Path, before: set[str]) -> Path | None:
    """The chat this run created, once its turn is finished."""
    for name in sorted(chat_dirs(cwd) - before, reverse=True):
        chat = CHATS_ROOT / cwd.name / "chats" / name
        try:
            log = (chat / "log.jsonl").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if FINISHED_MARK in log and (chat / "run-state.json").is_file():
            return chat
    return None


def reply_from_run_state(state: dict[str, Any]) -> str:
    output = state.get("output") or {}
    if output.get("type") != "lastMessage":
        raise ValueError(f"freebuff ended with {output.get('type')!r}: {str(output.get('message') or output)[:500]}")
    texts = []
    for message in output.get("value") or []:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
            continue
        texts += [part["text"] for part in content or []
                  if isinstance(part, dict) and part.get("type") == "text" and part.get("text")]
    reply = "\n".join(t.strip() for t in texts if t.strip())
    if not reply:
        raise ValueError("freebuff finished without assistant text")
    return reply


class FreebuffWorker:
    """Worker adapter for the freebuff CLI (free Codebuff) through a pseudo console."""

    def __init__(self, *, allowed_roots: tuple[str, ...], argv: list[str] | None = None,
                 timeout_seconds: float = 1800.0, boot_seconds: float = 60.0,
                 env: dict[str, str] | None = None) -> None:
        self._argv = list(argv or [default_executable() or "freebuff"])
        self._allowed_roots = allowed_roots
        self._timeout_seconds = timeout_seconds
        self._boot_seconds = boot_seconds
        self._env = env or {}

    @property
    def worker_id(self) -> str:
        return "freebuff"

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"coding", "repo_edit", "analysis"})

    async def is_available(self) -> bool:
        from all_tomorrow.adapters.workers import _check_executable_available
        return _check_executable_available(self._argv)

    def build_argv(self, cwd: Path) -> list[str]:
        return [*self._argv, "--cwd", str(cwd), "--trust-agents"]

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        from all_tomorrow.adapters.workers import WorkerError, _build_worker_prompt, _resolve_cwd, _sanitize_error
        start = time.perf_counter()

        def result(status: WorkerStatus, payload: dict[str, Any] | None = None, error: str | None = None):
            return WorkerResult(request.request_id, request.trace_id, status, payload=payload or {},
                                duration_ms=int((time.perf_counter() - start) * 1000),
                                error=_sanitize_error(error) if error else None)

        try:
            cwd = _resolve_cwd(request.payload.get("cwd"), self._allowed_roots)
        except WorkerError as error:
            return result(WorkerStatus.TRAVERSAL_BLOCKED, error=str(error))
        try:
            status, payload, error = await asyncio.to_thread(self._session, cwd, _build_worker_prompt(request))
        except FileNotFoundError:
            return result(WorkerStatus.EXECUTABLE_NOT_FOUND, error=f"Executable not found: {self._argv[0]}")
        except Exception as error:   # pty or job failures
            return result(WorkerStatus.FAILED, error=f"freebuff session failed: {error}")
        return result(status, payload, error)

    def _session(self, cwd: Path, prompt: str) -> tuple[WorkerStatus, dict[str, Any], str | None]:
        import pyte
        from winpty import PtyProcess
        from all_tomorrow.adapters.workers import _attach_windows_job, _worker_environment

        screen = pyte.Screen(COLS, ROWS)
        stream = pyte.Stream(screen)
        lock = threading.Lock()
        before = chat_dirs(cwd)
        proc = PtyProcess.spawn(self.build_argv(cwd), cwd=str(cwd), env=_worker_environment(self._env),
                                dimensions=(ROWS, COLS))
        _attach_windows_job(proc)   # closing the job ends freebuff and every shell it started

        def pump() -> None:
            while True:
                try:
                    data = proc.read(65536)
                except EOFError:
                    return
                with lock:
                    stream.feed(data)

        def shown() -> str:
            with lock:
                return "\n".join(line.rstrip() for line in screen.display if line.strip())

        threading.Thread(target=pump, daemon=True).start()
        try:
            deadline = time.monotonic() + self._boot_seconds
            while READY_MARK not in shown():
                if LOGIN_MARK in shown():
                    return WorkerStatus.FAILED, {}, "freebuff CLI is not logged in: run freebuff once and sign in"
                if not proc.isalive():
                    return WorkerStatus.FAILED, {"screen": shown()[-2000:]}, "freebuff exited during startup"
                if time.monotonic() > deadline:
                    return WorkerStatus.TIMEOUT, {"screen": shown()[-2000:]}, "freebuff input box never appeared"
                time.sleep(0.5)
            # Bracketed paste keeps newlines inside the prompt instead of submitting each line.
            proc.write("\x1b[200~" + prompt.replace("\r\n", "\n") + "\x1b[201~")
            # Enter sent while the TUI is still taking in a paste is dropped; resend until the chat starts.
            for _ in range(10):
                time.sleep(2.0)
                proc.write("\r")
                time.sleep(1.0)
                if submitted(cwd, before):
                    break
            else:
                return WorkerStatus.FAILED, {"screen": shown()[-2000:]}, "freebuff did not accept the prompt"
            deadline = time.monotonic() + self._timeout_seconds
            while (chat := finished_chat(cwd, before)) is None:
                if not proc.isalive():
                    return WorkerStatus.FAILED, {"screen": shown()[-2000:]}, "freebuff exited before finishing"
                if time.monotonic() > deadline:
                    return (WorkerStatus.TIMEOUT, {"screen": shown()[-2000:], "timed_out": True},
                            f"freebuff timed out after {self._timeout_seconds}s")
                time.sleep(2)
            state = json.loads((chat / "run-state.json").read_text(encoding="utf-8"))
            try:
                reply = reply_from_run_state(state)
            except ValueError as error:
                return WorkerStatus.INVALID_OUTPUT, {"chat": str(chat)}, str(error)
            return WorkerStatus.SUCCESS, {"response": reply, "text": reply, "chat": str(chat)}, None
        finally:
            job = getattr(proc, "_windows_job", None)
            if job is not None:
                job.Close()
                proc._windows_job = None
            try:
                proc.terminate(force=True)
            except Exception:
                pass
