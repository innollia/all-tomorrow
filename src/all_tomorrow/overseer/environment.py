"""DP7의 비밀값은 환경에만 적재한다. 값은 반환하거나 기록하지 않는다."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_key_pool(path: Path | None = None) -> None:
    path = path or Path.home() / ".all-tomorrow" / "key-pool.env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name and not name.startswith("#"):
                if not os.environ.get(name.strip()):
                    os.environ[name.strip()] = value.strip().strip("\"'")


def project_registry() -> dict:
    import json
    path = Path(os.environ.get("ALL_TOMORROW_PROJECTS", REPO / "config/projects.local.json"))
    return json.loads(path.read_text(encoding="utf-8"))["projects"]
