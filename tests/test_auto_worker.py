import json

from all_tomorrow.adapters.workers import ClaudeWorker
from all_tomorrow.overseer import auto_worker, idle_research, metacog


def test_setting_switches_every_default(monkeypatch) -> None:
    monkeypatch.delenv("ALL_TOMORROW_AUTO_WORKER", raising=False)
    assert auto_worker.worker() == "claude"
    assert "codex" not in metacog._reasoners("claude")
    assert idle_research.settings()["short_max_percent"] == 80
    assert idle_research.short_job_args(auto_worker.COMPRESS_MODEL)[:2] == ["--model", "claude-haiku-5-5"]
    monkeypatch.setenv("ALL_TOMORROW_AUTO_WORKER", "codex")
    assert auto_worker.worker() == "codex"
    assert metacog._reasoners("codex")[0] == "codex"
    assert idle_research.settings()["short_max_percent"] == 95
    assert "--model" not in idle_research.short_job_args()


def test_claude_quota_uses_its_own_window_and_tolerates_a_failed_probe(tmp_path) -> None:
    usage = tmp_path / "subscription-usage.json"
    usage.write_text(json.dumps({"providers": [{"id": "claude", "status": "error"}]}), encoding="utf-8")
    assert idle_research.quota_ok(tmp_path, 80, 0, "claude")[0]
    assert not idle_research.quota_ok(tmp_path, 80, 0, "codex")[0]
    usage.write_text(json.dumps({"providers": [{"id": "claude", "status": "connected",
                                                "windows": [{"label": "Weekly", "percent": 85}]}]}), encoding="utf-8")
    assert not idle_research.quota_ok(tmp_path, 80, 0, "claude")[0]


def test_claude_worker_can_take_the_prompt_on_stdin() -> None:
    worker = ClaudeWorker(allowed_roots=("x",), argv=["claude"])
    assert "--" not in worker.build_argv("-")
    assert worker.build_argv("hi")[-2:] == ["--", "hi"]
