import json
import os
import sys
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from all_tomorrow.overseer import distill, oracle, oracle_mcp
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore


def _with_cards(tmp_path):
    store = SessionStore(tmp_path / "overseer.sqlite")
    distill.ensure_schema(store.con)
    cards = {
        ("codex", "c1", "web"): {"problem": "Windows 콘솔에서 UnicodeEncodeError cp949 출력 오류",
                                 "solution": "PYTHONIOENCODING=utf-8 설정", "outcome": "해결"},
        ("claude", "a1", "game"): {"problem": "UnicodeEncodeError cp949 로그 저장 실패",
                                   "solution": "", "outcome": "미해결"},
        ("opencode", "o1", "tin"): {"problem": "git push 인증 창이 뜨지 않음",
                                    "solution": "credential manager 재설정", "outcome": "해결"},
    }
    for (source, sid, project), card in cards.items():
        s = Session(source, sid, cwd=f"C:\\projects\\{project}", agent=source)
        s.lines = ["[U] x"]
        store.put(s, "fp", lambda t: t)
        store.commit()
        distill.distill_session(store.con, source, sid, redact=Redactor(), secrets=frozenset(),
                                chat=lambda g, sy, u, c=card: ([dict(c, situation=["windows"])], "d"))
    return store


def test_search_finds_cards_from_other_sessions_solved_first(tmp_path) -> None:
    store = _with_cards(tmp_path)
    found = oracle.search(store.con, "python 스크립트가 UnicodeEncodeError: 'cp949' codec 오류로 죽음", project="game")
    assert [c["session"] for c in found] == ["codex:c1", "claude:a1"]
    assert found[0]["solution"] == "PYTHONIOENCODING=utf-8 설정" and found[0]["project"] == "web"
    assert oracle.search(store.con, "전혀 관계없는 그래픽 셰이더 문제") == []


def test_ask_logs_every_question_with_returned_cards(tmp_path) -> None:
    store = _with_cards(tmp_path)
    answer = oracle.ask(store.con, "git push 인증 창이 안 뜸", caller="codex", project="money")
    assert answer["found"] and answer["cards"][0]["session"] == "opencode:o1"
    empty = oracle.ask(store.con, "셰이더 컴파일", caller="claude")
    assert not empty["found"]
    logged = store.con.execute("select caller, project, card_ids from oracle_log order by asked_at").fetchall()
    assert logged[0][:2] == ("codex", "money") and json.loads(logged[0][2]) == [answer["cards"][0]["card_id"]]
    assert logged[1][2] == "[]"


def test_redistilling_keeps_the_index_in_step(tmp_path) -> None:
    store = _with_cards(tmp_path)
    distill.distill_session(store.con, "opencode", "o1", redact=Redactor(), secrets=frozenset(),
                            chat=lambda g, s, u: ([], "d"))
    assert oracle.search(store.con, "git push 인증 창") == []
    assert store.con.execute("select count(*) from cards_fts").fetchone()[0] == 2


async def test_mcp_server_over_real_stdio_exposes_only_the_oracle_tool(tmp_path) -> None:
    _with_cards(tmp_path).close()
    transport = StdioTransport(command=sys.executable, args=["-m", "all_tomorrow.overseer.oracle_mcp"],
                               env={**os.environ, "ALL_TOMORROW_OVERSEER_DIR": str(tmp_path)})
    started = time.monotonic()
    async with Client(transport) as client:
        assert {t.name for t in await client.list_tools()} == {"oracle_ask"}
        assert time.monotonic() - started < 2.0   # Codex drops servers that start slowly
        result = await client.call_tool("oracle_ask", {"problem": "cp949 UnicodeEncodeError", "agent": "kiro"})
    answer = json.loads(result.content[0].text)
    assert answer["found"] is True and answer["cards"][0]["session"] == "codex:c1"


def test_unknown_tool_and_method_are_errors_not_crashes() -> None:
    assert oracle_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "other"}})["error"]["code"] == -32602
    assert oracle_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"] == -32601
    assert oracle_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
