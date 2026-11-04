import json

from all_tomorrow.console import memory

MB = 2 ** 20
CLI = r"C:\Users\u\AppData\Local\Claude-Data\claude_x\claude-code\2.1\abc\claude.exe --output-format stream-json"
SID = "29434c29-e204-4d39-aa37-965af61edd63"


def proc(pid, ppid, name, cmd, mb, started=None):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "private": mb * MB, "started": started}


def tree():
    return [
        proc(1, 0, "explorer.exe", "explorer", 50),
        proc(2, 1, "Claude.exe", r'"C:\Program Files\WindowsApps\Claude_1\app\Claude.exe"', 300),
        proc(10, 2, "claude.exe", f"{CLI} --resume {SID} --model x", 700),
        proc(11, 10, "python.exe", "C:/at/.venv/Scripts/python.exe -m all_tomorrow.mcp_server", 2),
        proc(12, 11, "python.exe", "C:/at/.venv/Scripts/python.exe -m all_tomorrow.mcp_server", 100),
        proc(13, 10, "uvx.exe", "uvx mcp-proxy-for-aws-cli==1.7.0 https://aws-mcp.example/mcp", 6),
        proc(14, 13, "python.exe", "python mcp-proxy-for-aws-cli.exe https://aws-mcp.example/mcp", 90),
        proc(15, 10, "bash.exe", "bash -c ls", 5),
        proc(20, 2, "claude.exe", CLI + " --model y", 600, started=1_000_000.0),   # fresh session, no --resume
        proc(21, 20, "python.exe", "python -m all_tomorrow.overseer.oracle_mcp", 40),
        proc(30, 0, "svchost.exe", "svchost -k netsvcs", 20),
        proc(31, 30, "python.exe", r'"C:\rt\python.exe" -m all_tomorrow.overseer.runtime api', 2),
        proc(32, 31, "python.exe", r'"C:\rt\python.exe" -m all_tomorrow.overseer.runtime api', 120),
        proc(40, 1, "chrome.exe", "chrome.exe", 400),
        proc(41, 40, "chrome.exe", "chrome.exe --type=renderer", 200),
        proc(50, 0, "headless", "x", 0),
    ]


def test_groups_sessions_mcp_components_and_apps():
    now = 1_000_000.0 + 3600
    sessions = {SID: {"cliSessionId": SID, "title": "블로그", "cwd": r"C:\projects\blog", "lastActivityAt": (now - 7200) * 1000},
                "new": {"cliSessionId": "new", "title": "새 세션", "cwd": r"C:\projects", "createdAt": 1_000_030_000,
                        "lastActivityAt": (now - 60) * 1000}}
    view = memory.classify(tree(), sessions, now)
    rows = {r["title"]: r for r in view["sessions"]}
    blog = rows["블로그"]
    assert blog["folder"] == "blog" and blog["idle_minutes"] == 120
    parts = {p["label"]: p["gb"] for p in blog["parts"]}
    assert set(parts) == {"Claude Code 본체", "All Tomorrow MCP", "AWS 플러그인 MCP", memory.OTHER_HELPER}
    assert parts["All Tomorrow MCP"] == round(102 * MB / memory.GB, 2)    # venv redirector + interpreter together
    assert rows["새 세션"]["idle_minutes"] == 1                            # matched by start time, no --resume
    assert {m["label"]: m["count"] for m in view["mcp"]} == {"All Tomorrow MCP": 1, "AWS 플러그인 MCP": 1, "신탁 MCP": 1}
    assert [a["label"] for a in view["all_tomorrow"]] == ["api"]
    apps = {a["label"]: a for a in view["apps"]}
    assert apps["Chrome"]["count"] == 2 and "Claude 데스크톱 앱" in apps
    assert "Windows 시스템" in apps


def test_response_never_carries_command_lines():
    secretish = "--token=sk-THIS-MUST-NOT-LEAK"
    procs = tree() + [proc(60, 1, "tool.exe", f"tool.exe {secretish}", 10)]
    view = memory.classify(procs, {}, 1_000_000.0)
    text = json.dumps(view, ensure_ascii=False)
    assert "sk-THIS" not in text and "aws-mcp.example" not in text and "--resume" not in text


def test_session_records_follow_earlier_ids(tmp_path):
    folder = tmp_path / "claude-code-sessions" / "a" / "b"
    folder.mkdir(parents=True)
    (folder / "local_1.json").write_text(json.dumps(
        {"cliSessionId": "now", "priorCliSessionIds": ["before"], "title": "t"}), encoding="utf-8")
    records = memory.session_records(tmp_path)
    assert records["before"]["title"] == records["now"]["title"] == "t"
    procs = [proc(1, 0, "claude.exe", str(tmp_path) + r"\claude-code\2.1\x\claude.exe --resume " + SID, 1)]
    assert memory.claude_data_dir(procs) == tmp_path


def test_wmi_time():
    assert memory.wmi_time("19700101010000.000000+060") == 0      # 01:00 at UTC+60min = epoch 0
    assert memory.wmi_time(None) is None


def test_snapshot_shape_with_injected_reader():
    data = memory.snapshot(read=tree, now=1_000_000.0)
    assert data["available"] and data["process_count"] == len(tree())
    assert [g["label"] for g in data["summary"]] == ["Claude Code 세션", "All Tomorrow", "그 밖의 앱"]
