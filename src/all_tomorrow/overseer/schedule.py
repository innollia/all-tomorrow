"""PC 미사용 시간과 설정한 간격으로 메타인지를 깨울지 정한다."""
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


def _in_user_session() -> bool:
    """이 프로세스가 session 0(서비스·S4U)이 아닌 로그인 세션에서 도는지."""
    if os.name != "nt":
        return False
    from ctypes import wintypes
    session = wintypes.DWORD()
    kernel = ctypes.windll.kernel32
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        return False
    return session.value != 0


def idle_seconds(base=None) -> float | None:
    # 이 PC는 WTS LastInputTime이 늘 0이라 WTS만으로는 None이다(2026-10-27 확인).
    # 예약 작업이 Interactive 로그온(사용자 세션)이면 GetLastInputInfo를 바로 읽을 수 있다.
    value = _session_idle_seconds()
    if value is None and _in_user_session():
        value = local_idle_seconds()
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


def settings() -> dict:
    """메타인지 깨어남 설정. 환경 변수(예: key-pool.env)로 바꾼다."""
    def number(name: str, default: float) -> float:
        try:
            value = float(os.environ.get(name, "") or default)
        except ValueError:
            return default
        return value if value >= 0 else default
    return {"min_interval": number("ALL_TOMORROW_METACOG_MIN_INTERVAL_MINUTES", 30) * 60,
            "daily_limit": int(number("ALL_TOMORROW_METACOG_DAILY_LIMIT", 24)),
            "idle_seconds": number("ALL_TOMORROW_METACOG_IDLE_SECONDS", 300),
            "check_interval": number("ALL_TOMORROW_METACOG_CHECK_MINUTES", 10) * 60}


def wake_gate(idle: float | None, config: dict | None = None) -> tuple[bool, str]:
    """코드만으로 깨어남을 확인해도 되는지. 모델 호출 여부는 metacog.wake가 변화·간격·하루 상한으로 정한다.

    예전에는 Codex 잔량을 초기화 전에 다 쓰도록 60~1800초 간격을 계산했다(사흘 562회 깨어남).
    잔량이 0이거나 초기화 시각이 지나면 조용히 멈춰 원인도 남지 않았다(2026-10-26 12:17 이후)."""
    config = config or settings()
    need = config["idle_seconds"]
    if need <= 0:
        return True, "PC 사용 여부 무시(설정)"
    if idle is None:
        # 모르면 영영 안 깨어나던 것이 2026-10-26 23:29 이후 멈춤의 원인이었다.
        # 변화 있음·최소 간격·하루 상한이 모델 호출을 이미 제한하므로 이 조건만 건너뛴다.
        return True, "PC 미사용 시간 확인 불가(다른 조건으로만 판단)"
    if idle < need:
        return False, "PC 사용 중"
    return True, "PC 미사용"
