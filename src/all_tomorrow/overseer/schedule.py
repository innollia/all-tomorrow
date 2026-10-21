"""PC 미사용 시간과 초기화 전에 남은 사용량으로 깨어날 때를 정한다."""
from datetime import datetime, timezone
import ctypes
import os


def local_idle_seconds() -> float | None:
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]
    info = LastInput()
    info.size = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - info.tick) & 0xffffffff) / 1000


def idle_seconds(base=None) -> float | None:
    value = _session_idle_seconds()
    if value is not None or base is None:
        return value
    # 일부 Windows 로컬 세션은 WTS LastInputTime=0이다. 로그인 세션의 별도 관측값을 쓴다.
    import json
    import time
    try:
        data = json.loads((base / "pc-activity.json").read_text(encoding="utf-8"))
        age = time.time() - data["at"]
        if 0 <= age <= 120 and data["idle_seconds"] is not None:
            return data["idle_seconds"] + age
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _session_idle_seconds() -> float | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    # S4U 예약 작업은 session 0이므로 GetLastInputInfo 대신 실제 사용자 세션을 읽는다.
    class Session(ctypes.Structure):
        _fields_ = [("id", wintypes.DWORD), ("name", wintypes.LPWSTR), ("state", ctypes.c_int)]

    class Info(ctypes.Structure):
        _fields_ = [("state", wintypes.DWORD), ("id", wintypes.DWORD),
                    ("counters", wintypes.DWORD * 6), ("station", wintypes.WCHAR * 32),
                    ("domain", wintypes.WCHAR * 17), ("user", wintypes.WCHAR * 21),
                    ("connect", ctypes.c_longlong), ("disconnect", ctypes.c_longlong),
                    ("last_input", ctypes.c_longlong), ("logon", ctypes.c_longlong),
                    ("current", ctypes.c_longlong)]
    api = ctypes.windll.wtsapi32
    api.WTSEnumerateSessionsW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                        ctypes.POINTER(ctypes.POINTER(Session)), ctypes.POINTER(wintypes.DWORD)]
    api.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    api.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    sessions, count = ctypes.POINTER(Session)(), wintypes.DWORD()
    if not api.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(sessions), ctypes.byref(count)):
        return None
    values = []
    try:
        for i in range(count.value):
            session = sessions[i]
            if session.state != 0:
                continue
            pointer, size = ctypes.c_void_p(), wintypes.DWORD()
            if not api.WTSQuerySessionInformationW(None, session.id, 24, ctypes.byref(pointer), ctypes.byref(size)):
                return None
            try:
                if size.value < ctypes.sizeof(Info):
                    return None
                info = ctypes.cast(pointer, ctypes.POINTER(Info)).contents
                if info.last_input <= 0 or info.current < info.last_input:
                    return None
                values.append((info.current - info.last_input) / 10_000_000)
            finally:
                api.WTSFreeMemory(pointer)
        return min(values) if values else 86400.0
    finally:
        api.WTSFreeMemory(sessions)


def wake_delay(usage: dict, idle: float | None, *, now=None) -> tuple[float | None, str]:
    now = now or datetime.now(timezone.utc)
    if idle is None or idle < 300:
        return None, "PC 사용 중이거나 미사용 시간 확인 불가"
    codex = next((p for p in usage.get("providers", []) if p.get("id") == "codex"), {})
    if codex.get("status") != "connected" or not codex.get("windows"):
        return None, "Codex 잔량 확인 불가"
    try:
        observed = datetime.fromisoformat(codex["observed_at"].replace("Z", "+00:00"))
        if (now - observed).total_seconds() > 1800:
            return None, "사용량 관측이 오래됨"
        intervals = []
        for window in codex["windows"]:
            reset = datetime.fromisoformat(window["resets_at"].replace("Z", "+00:00"))
            seconds = (reset - now).total_seconds()
            if seconds <= 0:
                return None, "초기화 뒤 사용량 재수집 필요"
            remaining = 100 - float(window["percent"])
            if remaining <= 0:
                return None, "Codex 잔량 없음"
            # 한 번에 약 1포인트를 쓰는 시작 추정치. 매번 최신 잔량으로 다시 계산한다.
            intervals.append(seconds / remaining)
        return max(60, min(1800, min(intervals))), "PC 미사용 · 잔량과 초기화 시각에 맞춤"
    except (KeyError, TypeError, ValueError):
        return None, "사용량 형식 확인 불가"
