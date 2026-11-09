from __future__ import annotations

import json
from pathlib import Path

import pytest

from all_tomorrow.adapters import freebuff
from all_tomorrow.local_workers import configured_adapters


def write_chat(root: Path, project: str, stamp: str, *, finished: bool, output: dict) -> Path:
    chat = root / project / "chats" / stamp
    chat.mkdir(parents=True)
    log = '{"msg":"Main prompt finished"}\n' if finished else '{"msg":"started"}\n'
    (chat / "log.jsonl").write_text(log, encoding="utf-8")
    (chat / "run-state.json").write_text(json.dumps({"output": output}), encoding="utf-8")
    return chat


def last_message(*parts: dict) -> dict:
    return {"type": "lastMessage", "value": [{"role": "assistant", "content": list(parts)}]}


def test_reply_skips_reasoning_and_joins_text():
    state = {"output": last_message({"type": "reasoning", "text": "thinking"}, {"type": "text", "text": "add.py"})}
    assert freebuff.reply_from_run_state(state) == "add.py"


def test_reply_reports_error_output():
    with pytest.raises(ValueError, match="error"):
        freebuff.reply_from_run_state({"output": {"type": "error", "message": "out of hours"}})


def test_finished_chat_ignores_old_and_unfinished(tmp_path, monkeypatch):
    monkeypatch.setattr(freebuff, "CHATS_ROOT", tmp_path)
    cwd = tmp_path / "work" / "proj"
    write_chat(tmp_path, "proj", "2026-01-01T00-00-00Z", finished=True, output=last_message())
    before = freebuff.chat_dirs(cwd)
    write_chat(tmp_path, "proj", "2026-01-02T00-00-00Z", finished=False, output=last_message())
    assert freebuff.finished_chat(cwd, before) is None
    done = write_chat(tmp_path, "proj", "2026-01-03T00-00-00Z", finished=True,
                      output=last_message({"type": "text", "text": "ok"}))
    assert freebuff.finished_chat(cwd, before) == done


def test_configured_as_local_worker(tmp_path):
    adapters = configured_adapters({"allowed_roots": [str(tmp_path)],
                                    "workers": {"freebuff": {"argv": ["freebuff.exe"]}}})
    worker = adapters["freebuff"]
    assert worker.worker_id == "freebuff"
    assert worker.build_argv(tmp_path) == ["freebuff.exe", "--cwd", str(tmp_path), "--trust-agents"]
