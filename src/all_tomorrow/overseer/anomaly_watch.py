"""문턱 아래 이상 감시: 감시가 스스로 '막혔다'고 판정하지는 않지만 오래 이어지는 이상을 찾아 메타인지 세션을 깨운다.

메타인지 세션(metacog_session)은 server_watch가 서버를 3번 켜도 안 살아나거나 api_watchdog가 재기동 한도에
닿을 때만 깨어났다. 2026-10-28 뒤로는 그런 일이 없어서, 11/3 API 헬스 실패 22번, 서버 점검 unknown 1시간 넘게,
사용량 push 시간 초과 14번이 있었는데도 아무도 깨지 않았다(마지막 세션 10/28 05:22).

PC 메모리 부족·부하는 이상이 아니다(사용자 판단, 2026-11-04). 부하로 생긴 시간 초과는 점검이 unknown으로 두고
여기서도 세지 않는다: 메모리를 이상으로 열었더니 메타인지가 사용자에게 '세션 닫을까요' 같은 답할 근거 없는 질문만 보냈다.

서버 점검(server_watch.sweep, 5분 안팎)마다 한 번 아래를 본다. 모델 호출 없이 파일만 읽는다.
- API 헬스 깜빡임: api-watchdog.jsonl에서 지난 1시간 시간 초과가 아닌 health_failed가 HEALTH_FAILS번 이상.
- 서버 확인 불가: server-watch.json에서 같은 서버가 STREAK번 연속 unknown(응답 지연 때문인 것은 뺀다).
- 로그 반복 경고: overseer·executor·collect 로그에서 지난 1시간 같은 WARNING/ERROR가 LOG_REPEATS번 이상
  (TimeoutError 같은 시간 초과 경고는 뺀다).

이상마다 지문으로 anomalies.json(items)에 남기고, 열리면 metacog_session.wake로 지문당 한 번 깨운다(하루 상한은
wake가 지킨다). 조건이 RECOVER번 연속 사라지면 닫고 지문을 풀어, 다시 생기면 새 이상으로 깨운다.
지문의 서버 id는 'watch.<대상>'이다: api_watchdog가 API가 살 때마다 부르는 resolve(base, "api")에 지워지지 않게.
비밀값은 읽지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

from all_tomorrow.overseer import metacog_session
from all_tomorrow.overseer.workspace import save

log = logging.getLogger(__name__)

FILE = "anomalies.json"
WINDOW = 3600
HEALTH_FAILS = 6
LOG_REPEATS = 6
STREAK = 3            # 점검 3번(15분 안팎) 연속이어야 연다
RECOVER = 6           # 30분 안팎 조용해야 닫는다(깜빡이는 이상으로 하루 상한을 다 쓰지 않게)
KEEP_CLOSED = 7 * 86400
LOGS = ("overseer", "executor", "collect")
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (WARNING|ERROR) (.+)$")
SLOW = re.compile(r"timeout|timed out|응답 지연|시간 초과", re.I)   # 부하로 생긴 시간 초과: 이상으로 세지 않는다


def tail(path: Path, size: int = 256_000) -> list[str]:
    try:
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - size))
            return file.read().decode("utf-8", errors="replace").splitlines()[1:]
    except OSError:
        return []


def health_flapping(base: Path, now: float) -> dict | None:
    fails = 0
    for line in tail(base / "api-watchdog.jsonl"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("event") == "health_failed" and not entry.get("timeout") and now - entry.get("at", 0) < WINDOW:
            fails += 1
    if fails < HEALTH_FAILS:
        return None
    return {"target": "api", "kind": "health_flapping", "title": f"중앙 API 헬스 검사가 지난 1시간 {fails}번 실패",
            "detail": ("재기동 한도에는 안 닿았지만 /healthz가 시간 초과가 아닌 거절·오류로 자주 실패한다. "
                       "기록 api-watchdog.jsonl·api.log·api-watchdog.log."),
            "facts": {"health_failed_last_hour": fails}, "now": True}


def unknown_servers(base: Path) -> list[dict]:
    try:
        entries = json.loads((base / "server-watch.json").read_text(encoding="utf-8")).get("servers", {})
    except (OSError, ValueError):
        return []
    return [{"target": server, "kind": "unknown", "title": f"서버 {server} 상태를 계속 확인하지 못함",
             "detail": (f"server_watch 점검이 연속으로 unknown({entry.get('detail', '')})이라 죽어도 켜지 않는다. "
                        "확인 방법(console/servers.py observe)이 왜 실패하는지 본다."),
             "facts": {"detail": entry.get("detail", "")}}
            for server, entry in entries.items()
            if entry.get("status") == "unknown" and not SLOW.search(entry.get("detail", ""))]


def log_repeats(base: Path, now: float) -> list[dict]:
    found = []
    for component in LOGS:
        counts: Counter[str] = Counter()
        for line in tail(base / f"{component}.log"):
            match = LOG_LINE.match(line)
            if not match:
                continue
            try:
                at = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            if now - at < WINDOW and not SLOW.search(match.group(3)):
                counts[re.sub(r"\d+", "N", match.group(3)).strip()[:80]] += 1
        for message, count in counts.items():
            if count >= LOG_REPEATS:
                found.append({"target": component, "kind": "log:" + message,
                              "title": f"{component}.log에 같은 경고가 지난 1시간 {count}번: {message}",
                              "detail": f"{component} 로그에 같은 WARNING/ERROR가 되풀이된다. 원인을 찾는다.",
                              "facts": {"message": message, "count": count}, "now": True})
    return found


def observations(base: Path, now: float) -> list[dict]:
    flapping = health_flapping(base, now)
    return [*unknown_servers(base), *log_repeats(base, now), *([flapping] if flapping else [])]


def check(base: Path, *, now: float | None = None, found: list[dict] | None = None,
          wake=metacog_session.safe_wake, resolve=metacog_session.resolve) -> dict:
    """한 번 점검. 반환: 지문 → opened|seen|closed 등 이번에 바뀐 것."""
    now = time.time() if now is None else now
    found = observations(base, now) if found is None else found
    try:
        data = json.loads((base / FILE).read_text(encoding="utf-8"))
        items = data["items"] if isinstance(data.get("items"), dict) else {}
    except (OSError, ValueError, KeyError, AttributeError):
        data, items = {}, {}
    data["items"] = items
    changes: dict[str, str] = {}
    seen = set()
    for obs in found:
        server_id = "watch." + obs["target"]
        fp = metacog_session.fingerprint(server_id, obs["kind"])
        seen.add(fp)
        item = items.get(fp)
        if item is None or item.get("closed_at"):
            item = items[fp] = {"fingerprint": fp, "first_seen": now, "streak": 0, "open": False}
        item.update(title=obs["title"], detail=obs["detail"], facts=obs.get("facts", {}), last_seen=now, clear=0)
        item["streak"] = item.get("streak", 0) + 1
        if not item["open"] and (obs.get("now") or item["streak"] >= STREAK):
            item.update(open=True, opened_at=now)
            changes[fp] = "opened"
        if item["open"] and item.get("woke") not in ("woken", "duplicate"):
            # 깨우기가 바빴거나(busy) 실패했으면 다음 점검에서 다시 시도한다. 같은 지문은 wake가 한 번만 깨운다.
            item["woke"] = wake(base, metacog_session.Incident(
                fingerprint=fp, source="anomaly_watch", title=item["title"],
                detail=item["detail"] + f" 이상 장부 {base / FILE}.", facts=item["facts"]))
            changes.setdefault(fp, "wake:" + str(item["woke"]))
    for fp, item in list(items.items()):
        if fp in seen or item.get("closed_at"):
            if item.get("closed_at") and now - item["closed_at"] > KEEP_CLOSED:
                del items[fp]
            continue
        item["streak"] = 0
        if not item.get("open"):
            del items[fp]
            continue
        item["clear"] = item.get("clear", 0) + 1
        if item["clear"] >= RECOVER:
            item.update(open=False, closed_at=now)
            resolve(base, fp.split(":", 1)[0], only=fp)
            changes[fp] = "closed"
    save(base / FILE, data)
    return changes


def run(base: Path) -> None:
    changes = check(base)
    if changes:
        log.info("anomaly watch: %s", changes)
