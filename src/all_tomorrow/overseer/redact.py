"""Mask secrets before session text is stored or sent to any model.

Session logs hold keys the user pasted into chats. Free model providers may log
or train on their input, so every value from the key pool, the AWS credentials
file and repo ``.env`` files is masked by exact match, plus common key shapes.
"""

from __future__ import annotations

import re
from pathlib import Path

MASK = "[REDACTED]"
_MIN_SECRET_LEN = 8

_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{20,}",                  # OpenAI / Anthropic / OpenRouter style
    r"AIza[0-9A-Za-z_\-]{30,}",                  # Google API keys
    r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}",
    r"github_pat_[A-Za-z0-9_]{40,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    r"hf_[A-Za-z0-9]{30,}",
    r"gsk_[A-Za-z0-9]{30,}",
    r"(?:ntn|secret)_[A-Za-z0-9]{30,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",   # JWT
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"(?i:bearer)\s+[A-Za-z0-9_\-\.=]{20,}",
]
# NAME=value / "name": "value" where the name says it is a credential; the name is kept.
_ASSIGNMENT = re.compile(
    r"(?i)(\b[A-Z0-9_\-]*(?:API[_\-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|ACCESS[_\-]?KEY)[A-Z0-9_\-]*[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s\"',;]{8,})")


def _env_values(path: Path) -> set[str]:
    values: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip().strip("'\"")
        if len(value) >= _MIN_SECRET_LEN:
            values.add(value)
    return values


def default_secret_files(home: Path) -> list[Path]:
    files = [home / ".all-tomorrow" / "key-pool.env", home / ".aws" / "credentials"]
    projects = Path("C:/projects")
    if projects.is_dir():
        files += [p for p in projects.glob("*/.env")]
    return files


class Redactor:
    def __init__(self, secret_values: set[str] | None = None) -> None:
        values = sorted((v for v in (secret_values or set()) if len(v) >= _MIN_SECRET_LEN),
                        key=len, reverse=True)
        parts = [re.escape(v) for v in values] + _PATTERNS
        self._exact = re.compile("|".join(parts))
        self.values = frozenset(values)
        self.value_count = len(values)

    @classmethod
    def from_files(cls, files: list[Path]) -> "Redactor":
        values: set[str] = set()
        for path in files:
            values |= _env_values(path)
        return cls(values)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        text = self._exact.sub(MASK, text)
        return _ASSIGNMENT.sub(lambda m: m.group(1) + MASK, text)
