import json
import tomllib

from all_tomorrow.adapters import chrome_pages


def test_codex_args_are_valid_toml_overrides(tmp_path) -> None:
    args = chrome_pages.codex_args(tmp_path / "pages" / "RR-1")
    assert args[::2] == ["-c"] * 5
    table = tomllib.loads("\n".join(a.replace("mcp_servers.chrome_pages.", "", 1) for a in args[1::2]))
    assert table["args"] == ["-m", "all_tomorrow.adapters.chrome_pages", "mcp"]
    assert table["env"]["AT_PAGES_DIR"] == str(tmp_path / "pages" / "RR-1") and table["tool_timeout_sec"] == 900


def test_archive_keeps_last_copy_of_each_page(tmp_path) -> None:
    assert chrome_pages.archived(tmp_path / "none") == []
    chrome_pages.archive(tmp_path, {"url": "https://a/1", "title": "하나", "text": "첫\n\n둘째 문단"})
    chrome_pages.archive(tmp_path, {"url": "https://a/2", "title": "", "text": ""})          # 빈 페이지는 넣지 않는다
    chrome_pages.archive(tmp_path, {"url": "https://a/1", "title": "하나", "text": "새 글"})
    assert chrome_pages.archived(tmp_path) == [{"url": "https://a/1", "title": "하나", "text": "새 글"}]


def test_read_asks_the_broker_over_one_json_line(monkeypatch) -> None:
    sent = []

    class Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def settimeout(self, t): pass
        def sendall(self, data): sent.append(json.loads(data))
        def recv(self, n): return json.dumps({"url": "u", "text": "글"}).encode() + b"\n"

    monkeypatch.setattr(chrome_pages, "ensure_broker", lambda wait=30: True)
    monkeypatch.setattr(chrome_pages.socket, "create_connection", lambda *a, **k: Sock())
    assert chrome_pages.read("https://chatgpt.com/x", scroll=True)["text"] == "글"
    assert sent == [{"url": "https://chatgpt.com/x", "scroll": True}]


def test_research_mcp_args_turns_off_only_the_users_extra_servers(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.node_repl]\ncommand = "n"\n[mcp_servers.Roblox_Studio]\ncommand = "cmd.exe"\n'
                      '[mcp_servers.oracle]\ncommand = "py"\n[mcp_servers."odd.name"]\ncommand = "x"\n', encoding="utf-8")
    args = chrome_pages.research_mcp_args(config)
    assert args == ["-c", "mcp_servers.Roblox_Studio.enabled=false", "-c", "mcp_servers.oracle.enabled=false"]
    assert chrome_pages.research_mcp_args(tmp_path / "missing.toml") == []


def test_wmi_create_hides_the_new_console(monkeypatch):
    import subprocess
    from all_tomorrow import winspawn
    seen = {}

    def run(argv, **kw):
        seen["script"], seen["flags"] = argv[-1], kw.get("creationflags")
        return subprocess.CompletedProcess(argv, 0, "0 1234\n", "")
    monkeypatch.setattr(winspawn.subprocess, "run", run)
    assert winspawn.wmi_create_hidden(["python", "-c", "print('x')"], "C:/repo") == 1234
    assert "ShowWindow=[uint16]0" in seen["script"] and "ProcessStartupInformation=$si" in seen["script"]
    assert "CurrentDirectory='C:/repo'" in seen["script"] and "print(''x'')" in seen["script"]
    assert seen["flags"] == winspawn.NO_WINDOW
