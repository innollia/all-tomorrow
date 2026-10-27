"""Windows: 이 프로세스 트리 밖(WMI)에 창 없이 프로세스를 띄운다.

WMI Win32_Process.Create는 새 콘솔을 만든다. 기본 터미널이 Windows Terminal이면 그 콘솔이 화면에 새 창으로 뜬다.
ShowWindow=0(SW_HIDE)으로 만들면 숨은 conhost 콘솔이 되고, 그 아래 자식(codex, cmd /c mcp.bat 등)도 그 콘솔을
물려받아 창이 뜨지 않는다(2026-10-27 실측).
"""
from __future__ import annotations

import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wmi_create_hidden(argv: list[str], cwd: str | None = None) -> int:
    """argv를 숨은 콘솔로 띄우고 PID를 돌려준다. 실패하면 RuntimeError."""
    command = subprocess.list2cmdline(argv).replace("'", "''")
    args = f"CommandLine='{command}'; ProcessStartupInformation=$si"
    if cwd:
        args += "; CurrentDirectory='" + str(cwd).replace("'", "''") + "'"
    script = ("$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; "
              f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{{args}}}; "
              "\"$($r.ReturnValue) $($r.ProcessId)\"")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)
    code, _, pid = result.stdout.strip().partition(" ")
    if code != "0":
        raise RuntimeError(f"WMI process creation failed: {result.stdout.strip()} {result.stderr.strip()[:300]}")
    return int(pid)
