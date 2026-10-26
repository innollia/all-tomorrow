"""쿼터가 소진된 판단자·작업자를 초기화 시각까지 건너뛴다.

Antigravity 개인 쿼터가 147시간 막혀 있는데 매 깨어남마다 먼저 불렀다가 실패하고 다음으로
넘어갔다(2026-10-24~26). 실패 문구에서 초기화까지 남은 시간만 읽어 파일에 기억한다.
오류 원문은 저장하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

FILE_NAME = "worker-cooldowns.json"
_QUOTA = re.compile(r"(?i)quota|usage limit|rate limit|rate_limit|resource_exhausted|too many requests")
_RESETS_IN = re.compile(r"(?i)resets?\s+in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?")
DEFAULT_WAIT = timedelta(hours=1)


class QuotaExhausted(RuntimeError):
    """메시지는 로컬에서 만든 시각뿐이라 비밀값이 섞이지 않는다."""

    def __init__(self, until: datetime):
        self.until = until
        super().__init__("쿼터 소진, 초기화 " + until.astimezone().strftime("%m-%d %H:%M"))


def quota_reset(text: str | bytes | None, now: datetime | None = None) -> datetime | None:
    """쿼터 소진 문구면 초기화 시각(모르면 1시간 뒤), 아니면 None."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if not text or not _QUOTA.search(text):
        return None
    now = now or datetime.now(timezone.utc)
    match = _RESETS_IN.search(text)
    if match and any(match.groups()):
        hours, minutes, seconds = (int(value or 0) for value in match.groups())
        return now + timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return now + DEFAULT_WAIT


class Cooldowns:
    def __init__(self, path: Path | None):
        self.path = path
        self._memory: dict[str, str] = {}

    def _load(self) -> dict[str, str]:
        if self.path is None:
            return dict(self._memory)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def until(self, name: str, now: datetime | None = None) -> datetime | None:
        now = now or datetime.now(timezone.utc)
        try:
            value = datetime.fromisoformat(self._load()[name])
        except (KeyError, ValueError):
            return None
        return value if value > now else None

    def set(self, name: str, until: datetime) -> None:
        data = self._load()
        data[name] = until.astimezone(timezone.utc).isoformat()
        if self.path is None:
            self._memory = data
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix="cooldowns-", suffix=".tmp", dir=self.path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=1)
        Path(temp).replace(self.path)

    def note(self, name: str, text, now: datetime | None = None) -> datetime | None:
        """실패 문구가 쿼터 소진이면 기억하고 초기화 시각을 돌려준다."""
        until = quota_reset(text, now)
        if until is not None:
            self.set(name, until)
        return until
