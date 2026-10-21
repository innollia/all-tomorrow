"""Stdio MCP server with one tool, `oracle_ask`, for every coding agent on this PC.

Kept separate from all_tomorrow.mcp_server on purpose: that one can dispatch work
into projects, while this one only reads the distilled cards.

It speaks MCP's JSON-RPC directly instead of using fastmcp: fastmcp takes ~2.5s to
import, and Codex fixed its tool list before the server finished starting
(2026-10-20), so the tool never appeared there. This starts in well under a second.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any

from all_tomorrow.overseer import oracle
from all_tomorrow.overseer.store import default_dir

PROTOCOL = "2025-06-18"
INSTRUCTIONS = (
    "신탁: 이 PC의 다른 에이전트 세션들(Claude Code·Codex·OpenCode·Kiro·Antigravity)이 겪고 해결한 문제 기록. "
    "같은 문제로 두 번 실패했거나 처음 보는 도구·환경 오류를 만나면, 세 번째 시도 전에 oracle_ask를 부른다."
)
TOOL = {
    "name": "oracle_ask",
    "description": (
        "막혔을 때 묻는다. 이 PC의 다른 세션에서 같은 문제를 해결한 기록이 있으면 돌려준다. "
        "돌아온 기록은 다른 세션의 경험이니 근거를 보고 지금 상황에 맞는지 판단해서 쓴다."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "problem": {"type": "string", "description": "증상, 오류 메시지 핵심 문구, 이미 시도한 것. 구체적일수록 잘 찾는다."},
            "project": {"type": "string", "description": "지금 작업 중인 프로젝트 폴더 이름(선택)"},
            "agent": {"type": "string", "description": "묻는 쪽 도구 이름(선택, 예: codex)"},
        },
        "required": ["problem"],
    },
}


def oracle_ask(problem: str, project: str = "", agent: str = "") -> dict:
    path = default_dir() / "overseer.sqlite"
    if not path.is_file():
        return {"found": False, "message": "신탁 기록이 아직 없습니다.", "cards": []}
    from all_tomorrow.overseer.store import open_peer, peer_paths
    con = sqlite3.connect(path, timeout=10)
    peers = []
    for peer_path in peer_paths(path.parent):   # the other PC's cards too
        try:
            peers.append(open_peer(peer_path))
        except Exception:
            pass
    try:
        return oracle.ask(con, problem, caller=agent, project=project or None, peers=peers)
    finally:
        for peer in peers:
            peer.close()
        con.close()


def handle(request: dict) -> dict | None:
    method, rid = request.get("method"), request.get("id")
    if rid is None:  # notification
        return None
    if method == "initialize":
        version = (request.get("params") or {}).get("protocolVersion") or PROTOCOL
        result: Any = {"protocolVersion": version, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "oracle", "version": "1"}, "instructions": INSTRUCTIONS}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = request.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}}
        args = params.get("arguments") or {}
        try:
            answer = oracle_ask(str(args.get("problem", "")), str(args.get("project", "")), str(args.get("agent", "")))
            result = {"content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}],
                      "structuredContent": answer, "isError": False}
        except Exception as error:  # report to the caller instead of dying
            result = {"content": [{"type": "text", "text": f"신탁 오류: {error}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main() -> None:
    stdin = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False, newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
