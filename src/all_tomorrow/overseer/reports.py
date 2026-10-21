"""보고 Event를 파일에 보관하고 Eve edge 전달 또는 선택한 webhook을 지원한다."""
import json
import os
from pathlib import Path

import httpx


def enqueue(base: Path, report_id: str, content: str) -> None:
    folder = base / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (report_id + ".json")
    if not path.exists():
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"id": report_id, "content": content, "sent_parts": 0},
                                   ensure_ascii=False), encoding="utf-8")
        temp.replace(path)


def flush(base: Path, *, post=httpx.post) -> int:
    from all_tomorrow.overseer.environment import load_key_pool
    load_key_pool()
    if os.environ.get("ALL_TOMORROW_DISCORD_TRANSPORT", "eve") != "webhook":
        return 0  # Eve가 edge API로 가져간다. 꺼져 있으면 파일에 그대로 남는다.
    url = os.environ.get("ALL_TOMORROW_DISCORD_WEBHOOK_URL")
    if not url:
        return 0
    # 임의 URL로 보고를 유출하지 않는다. allowed_mentions로 모델의 멘션을 막는다.
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"} \
            or not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("Discord webhook 주소 형식 오류")
    sent = 0
    for path in sorted((base / "reports").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("sent"):
            continue
        parts = [data["content"][i:i + 1800] for i in range(0, len(data["content"]), 1800)]
        for i in range(data.get("sent_parts", 0), len(parts)):
            try:
                response = post(url, json={"content": parts[i], "allowed_mentions": {"parse": []}}, timeout=15)
                response.raise_for_status()
            except httpx.HTTPError:
                return sent  # URL/오류 본문은 비밀값을 포함할 수 있어 기록하지 않는다.
            data["sent_parts"] = i + 1
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        data["sent"] = True
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        sent += 1
    return sent


async def sync_events(store, base: Path) -> None:
    # Event→파일 사이에 중단돼도 다음 번 실행에서 복구한다.
    for event in await store.list_events():
        content = event.payload.get("report")
        if event.actor == "metacog" and content:
            enqueue(base, str(event.event_id), content)


def pending(base: Path) -> list[dict]:
    """파일 이름은 서버에서만 고른다. 외부 Event ID를 경로에 붙이지 않는다."""
    result = []
    for path in sorted((base / "reports").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("sent"):
            # Discord는 UTF-16 길이를 센다. 이모지만 있어도 본문은 1600 이하다.
            parts = [data["content"][i:i + 800] for i in range(0, len(data["content"]), 800)] or [""]
            result.append({"event_id": data["id"], "parts": parts,
                           "next_part": data.get("eve_sent_parts", 0)})
        if len(result) >= 20:
            break
    return result


def acknowledge(base: Path, event_id: str, part: int, message_id: str) -> bool:
    for path in (base / "reports").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["id"] != event_id:
            continue
        next_part = data.get("eve_sent_parts", 0)
        messages = data.setdefault("discord_messages", [])
        if part < next_part:
            return part < len(messages) and messages[part] == message_id
        count = max(1, (len(data["content"]) + 799) // 800)
        if part != next_part or part >= count or data.get("sent"):
            return False
        messages.append(message_id)
        data["eve_sent_parts"] = part + 1
        data["sent"] = part + 1 == count
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        return True
    return False


def event_for_message(base: Path, message_id: str) -> str | None:
    for path in (base / "reports").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if message_id in data.get("discord_messages", []):
            return data["id"]
    return None


def record_reply(base: Path, message_id: str, reply: dict) -> bool:
    from datetime import datetime, timezone
    for path in (base / "reports").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if message_id not in data.get("discord_messages", []):
            continue
        replies = data.setdefault("replies", [])
        if not any(r["discord_message_id"] == reply["discord_message_id"] for r in replies):
            replies.append({**reply, "at": datetime.now(timezone.utc).isoformat(), "approval_granted": False})
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        return True
    return False


def recent_replies(base: Path, since: str | None) -> list[dict]:
    result = []
    for path in (base / "reports").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        result.extend({**reply, "report_id": data["id"], "report": data["content"]}
                      for reply in data.get("replies", []) if not since or reply["at"] > since)
    return sorted(result, key=lambda r: r["at"], reverse=True)[:60]
