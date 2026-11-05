"""All Tomorrow가 스스로 돌리는 일(압축·종합·유휴 조사·메타인지·수리)을 어느 구독 CLI로 할지 정하는 한 곳.

Codex로 되돌리려면 ALL_TOMORROW_AUTO_WORKER=codex로 두거나 DEFAULT만 바꾼다(사용자 결정 2026-11-04: 당분간 Claude).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT = "claude"
# 값싼 등급만 쓴다: 글을 줄이는 압축은 Haiku, 종합·조사는 Sonnet. Fable·최상위 모델은 쓰지 않는다.
COMPRESS_MODEL = "claude-haiku-5-5"
WORK_MODEL = "claude-sonnet-5-5"
# (유휴 조사 상한, 압축·종합 상한) 퍼센트. Claude는 사용자가 직접 쓰는 주력이라 더 일찍 멈춘다.
LIMITS = {"codex": (80.0, 95.0), "claude": (60.0, 80.0)}
_CLAUDE_BASE = ["--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
                "--disable-slash-commands"]


def worker() -> str:
    name = os.environ.get("ALL_TOMORROW_AUTO_WORKER", DEFAULT).strip().lower()
    return name if name in LIMITS else DEFAULT


def short_args(model: str) -> list[str]:
    """압축·종합용 인자: 도구도 MCP도 끄고 추론을 낮춘다."""
    return ["--model", model, "--effort", "low", "--tools", "", "--mcp-config", '{"mcpServers":{}}', *_CLAUDE_BASE]


def research_args(pages_dir: Path, python: str, model: str = WORK_MODEL) -> list[str]:
    """조사용 인자: 웹 검색과 로그인 페이지 읽기(chrome_pages)만 켠다."""
    servers = {"mcpServers": {"chrome_pages": {
        "command": python, "args": ["-m", "all_tomorrow.adapters.chrome_pages", "mcp"],
        "env": {"AT_PAGES_DIR": str(pages_dir)}}}}
    return ["--model", model, "--effort", "medium", "--tools", "WebSearch,WebFetch,Read,Grep,Glob",
            "--mcp-config", json.dumps(servers), *_CLAUDE_BASE]
