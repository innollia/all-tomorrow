"""사용자가 쓰는 크롬(로그인된 그 프로필)으로 페이지를 읽는다. 조사하는 Codex가 로그인이 필요한 곳(ChatGPT 프로젝트 등)을 읽는 길.

- 크롬은 사용자가 chrome://inspect에서 켠 원격 디버깅으로 127.0.0.1에 열려 있다(포트는 User Data/DevToolsActivePort).
  이 방식은 새 연결마다 크롬이 허용을 물을 수 있어서, 연결 하나를 붙들고 있는 중계(serve)를 따로 띄운다.
  크롬을 다시 켰을 때만 한 번 더 허용하면 된다.
- 중계: 127.0.0.1:PORT, 한 줄 JSON 요청 {"url", "scroll"} → 한 줄 JSON 답 {"url", "title", "text", "links"} 또는 {"error"}.
  읽을 때마다 뒤쪽 탭을 하나 열고 다 읽으면 닫는다. 쿠키·저장소는 꺼내지 않고 화면 글만 읽는다.
- mcp: Codex에 붙이는 도구 read_logged_in_page. 읽은 페이지는 AT_PAGES_DIR에 원문으로 남긴다(실행이 끝나면 자료로 넣는다).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PORT = int(os.environ.get("AT_CHROME_PAGES_PORT", "8771"))
ACTIVE_PORT = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"
TEXT_LIMIT = 200_000
READ_JS = """(() => {
  const root = document.querySelector('main') || document.body;
  const links = [...document.querySelectorAll('a[href]')].map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 200)}));
  return JSON.stringify({url: location.href, title: document.title, text: root ? root.innerText : '', links});
})()"""
SCROLL_JS = """(() => {
  let moved = 0;
  for (const el of [document.scrollingElement, ...document.querySelectorAll('*')]) {
    if (el && el.scrollHeight > el.clientHeight + 50 && /(auto|scroll)/.test(getComputedStyle(el).overflowY + (el === document.scrollingElement ? 'auto' : ''))) {
      const before = el.scrollTop; el.scrollTop = el.scrollHeight; moved += el.scrollTop - before;
    }
  }
  return moved;
})()"""


class Chrome:
    """크롬 브라우저 하나에 붙은 CDP 연결(flatten 세션). 읽기는 한 번에 하나."""

    def __init__(self) -> None:
        self.ws: Any = None
        self.next_id = 0
        self.waiting: dict[int, asyncio.Future] = {}
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()
        self.state = "connecting"

    async def keep_connected(self) -> None:
        """연결을 붙들고, 끊기면 다시 붙는다. 크롬의 허용 창은 사용자가 답할 때까지 기다린다(시간 제한 없음)."""
        import websockets
        while True:
            try:
                port, path = ACTIVE_PORT.read_text(encoding="utf-8").split()[:2]
                self.state = "waiting_for_chrome_allow"
                async with websockets.connect(f"ws://127.0.0.1:{port}{path}", max_size=None, open_timeout=None,
                                              ping_interval=None) as ws:
                    self.ws, self.state = ws, "connected"
                    self.ready.set()
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("id") in self.waiting:
                            self.waiting.pop(msg["id"]).set_result(msg)
            except Exception as error:
                self.state = f"disconnected ({type(error).__name__})"
            self.ready.clear()
            self.ws = None
            for future in self.waiting.values():
                future.set_exception(ConnectionError("chrome connection closed"))
            self.waiting.clear()
            await asyncio.sleep(5)

    async def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 60) -> dict:
        if self.ws is None:
            try:
                await asyncio.wait_for(self.ready.wait(), timeout)
            except TimeoutError:
                raise ConnectionError(f"Chrome not connected: {self.state}. The user must click Allow on Chrome's "
                                      "remote debugging prompt once.") from None
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.waiting[self.next_id] = future
        msg: dict[str, Any] = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        reply = await asyncio.wait_for(future, timeout)
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result", {})

    async def read(self, url: str, scroll: bool = False, settle: float = 25) -> dict:
        async with self.lock:
            target = (await self.call("Target.createTarget", {"url": "about:blank", "background": True}))["targetId"]
            try:
                session = (await self.call("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
                await self.call("Page.navigate", {"url": url}, session)
                return await self._settle(session, scroll, settle)
            finally:
                try:
                    await self.call("Target.closeTarget", {"targetId": target}, timeout=10)
                except Exception:
                    pass

    async def _settle(self, session: str, scroll: bool, settle: float) -> dict:
        """글이 더 늘지 않을 때까지 기다린다(SPA). scroll이면 끝까지 내려 더 불러온다.
        ChatGPT 대화는 질문이 먼저 뜨고 답이 몇 초 뒤에 붙어서, 짧게 멈춘 것을 끝으로 보면 답이 빠진다(실측)."""
        deadline = time.monotonic() + settle + (60 if scroll else 0)
        last, same, page = -1, 0, {}
        await asyncio.sleep(4)
        while time.monotonic() < deadline:
            value = await self.call("Runtime.evaluate", {"expression": READ_JS, "returnByValue": True}, session)
            page = json.loads(value.get("result", {}).get("value") or "{}")
            size = len(page.get("text", "")) + len(page.get("links", []))
            moved = 0
            if scroll:
                moved = (await self.call("Runtime.evaluate", {"expression": SCROLL_JS, "returnByValue": True}, session)
                         ).get("result", {}).get("value") or 0
            same = same + 1 if size == last and not moved else 0
            if same >= 4 and size > 0:
                break
            last = size
            await asyncio.sleep(1.5)
        page["text"] = page.get("text", "")[:TEXT_LIMIT]
        if re.search(r"/(auth/)?log-?in\b", page.get("url", "")):
            page["login_required"] = True
        return page


async def _serve() -> None:
    chrome = Chrome()
    asyncio.get_running_loop().create_task(chrome.keep_connected())

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads(await reader.readline())
            try:
                reply = ({"state": chrome.state} if req.get("status") else
                         await chrome.read(req["url"], bool(req.get("scroll"))))
            except Exception as error:
                reply = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
            writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", PORT, limit=1 << 20)
    async with server:
        await server.serve_forever()


def broker_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2):
            return True
    except OSError:
        return False


def start_broker() -> None:
    """중계를 이 프로세스 트리 밖(WMI)에 띄운다. Codex가 끝나도 연결이 남아 다음 조사도 허용 없이 쓴다."""
    argv = [sys.executable, "-m", "all_tomorrow.adapters.chrome_pages", "serve"]
    if os.name != "nt":
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return
    command = subprocess.list2cmdline(argv).replace("'", "''")
    script = f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine='{command}'}} | Out-Null"
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   capture_output=True, timeout=60, stdin=subprocess.DEVNULL)


def ensure_broker(wait: float = 30) -> bool:
    """중계가 없으면 띄운다. 조사를 시작할 때 미리 불러 두면 크롬 허용 창이 조사 전에 뜬다."""
    if broker_up():
        return True
    start_broker()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(1)
        if broker_up():
            return True
    return False


def _ask(request: dict, timeout: float) -> dict:
    ensure_broker()
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(1 << 16)
            if not chunk:
                break
            data += chunk
    return json.loads(data or b'{"error": "no reply"}')


def read(url: str, scroll: bool = False, timeout: float = 900) -> dict:
    """중계로 한 페이지를 읽는다. 중계가 없으면 띄운다."""
    return _ask({"url": url, "scroll": scroll}, timeout)


def status() -> str:
    return _ask({"status": True}, 30).get("state", "")


def archive(folder: Path, page: dict) -> Path:
    """읽은 페이지 원문을 실행 폴더에 남긴다. 첫 줄은 주소, 둘째 줄은 제목."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{len(list(folder.glob('*.md'))) + 1:03d}.md"
    path.write_text(f"{page.get('url', '')}\n{page.get('title', '')}\n\n{page.get('text', '')}", encoding="utf-8")
    return path


def archived(folder: Path) -> list[dict]:
    """archive로 남긴 페이지들(같은 주소는 마지막 것만)."""
    pages: dict[str, dict] = {}
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        url, _, rest = path.read_text(encoding="utf-8").partition("\n")
        title, _, text = rest.partition("\n\n")
        if text.strip():
            pages[url] = {"url": url, "title": title, "text": text}
    return list(pages.values())


PROMPT_NOTE = """
## 로그인이 필요한 페이지
- chatgpt.com처럼 로그인해야 보이는 페이지는 MCP 서버 chrome_pages의 read_logged_in_page로 읽는다. 사용자가 쓰는 크롬(로그인된 프로필)에서 열린다.
  지연 도구라 functions.exec 안에서 `await tools.mcp__chrome_pages__read_logged_in_page({url, scroll, offset})`로 부른다(ALL_TOOLS에 있다).
- Aside나 다른 브라우저·셸 명령으로 열려고 하지 않는다.
- 목록 페이지(예: ChatGPT 프로젝트)는 scroll=true로 읽어 링크를 모두 얻고, 요청에 해당하는 하위 페이지(각 대화)를 하나씩 모두 읽는다.
  긴 페이지는 text_length를 보고 offset으로 끝까지 읽는다. 읽은 페이지 원문은 시스템이 따로 보관하니 보고서에는 옮겨 적지 말고 정리만 한다.
- 도구가 크롬 연결 오류를 내면 그 사실을 보고서에 적고 웹 검색으로 할 수 있는 만큼만 한다.
"""


def codex_args(pages_dir: Path) -> list[str]:
    """codex exec에 read_logged_in_page 도구를 붙이는 -c 설정(--ignore-user-config여도 들어간다)."""
    key = "mcp_servers.chrome_pages"
    return ["-c", f"{key}.command={json.dumps(sys.executable)}",
            "-c", f'{key}.args=["-m", "all_tomorrow.adapters.chrome_pages", "mcp"]',
            "-c", f"{key}.env={{AT_PAGES_DIR = {json.dumps(str(pages_dir))}}}",
            "-c", f"{key}.startup_timeout_sec=60",
            "-c", f"{key}.tool_timeout_sec=900"]


def _mcp() -> None:
    from fastmcp import FastMCP
    pages_dir = Path(os.environ["AT_PAGES_DIR"]) if os.environ.get("AT_PAGES_DIR") else None
    # Codex가 시작할 때 띄워 두면 크롬 허용 창이 필요해도 조사 초반에 뜬다. 도구 목록이 늦지 않게 따로 돈다.
    threading.Thread(target=ensure_broker, kwargs={"wait": 0}, daemon=True).start()
    mcp = FastMCP("chrome_pages", instructions=(
        "Reads a page in the user's own Chrome, where they are logged in (ChatGPT, etc.). Use it for pages that need login. "
        "Do not use Aside or any other browser."))

    # 읽기만 하는 도구라고 알려야 approval_policy="never"인 codex exec가 승인 없이 부른다.
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    def read_logged_in_page(url: str, scroll: bool = False, offset: int = 0) -> dict[str, Any]:
        """Open url in the user's logged-in Chrome (background tab) and return its visible text and links.

        scroll=True scrolls to the end first so lazily loaded lists (e.g. all chats of a ChatGPT project) appear.
        Text is returned 40,000 characters at a time; pass offset to read further (the page is fetched again).
        """
        page = read(url, scroll)
        if page.get("error"):
            return page
        if pages_dir is not None and offset == 0:
            archive(pages_dir, page)
        text = page.get("text", "")
        links = [link for link in page.get("links", []) if link.get("href", "").startswith("http")]
        return {"url": page.get("url"), "title": page.get("title"), "login_required": page.get("login_required", False),
                "text": text[offset:offset + 40_000], "text_length": len(text), "links": links[:400]}

    mcp.run(show_banner=False)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "serve":
        asyncio.run(_serve())
    elif command == "mcp":
        _mcp()
    elif command == "status":
        print(status())
    elif command == "read":   # 확인용: python -m all_tomorrow.adapters.chrome_pages read <url> [scroll]
        page = read(sys.argv[2], len(sys.argv) > 3)
        print(json.dumps({k: (v[:2000] if k == "text" else v[:50] if k == "links" else v) for k, v in page.items()},
                         ensure_ascii=False, indent=1))
    else:
        raise SystemExit("usage: chrome_pages serve|mcp|status|read <url> [scroll]")


if __name__ == "__main__":
    main()
