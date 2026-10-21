import json
import sqlite3

from all_tomorrow.overseer.__main__ import collect
from all_tomorrow.overseer.redact import MASK, Redactor
from all_tomorrow.overseer.sources import Roots, project_of
from all_tomorrow.overseer.store import SessionStore

SECRET = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789"
POOL_VALUE = "pool-value-1234567890"


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def _roots(tmp_path):
    home = tmp_path / "home"
    roots = Roots.default(home)
    # Claude: one session with a failing tool call and an injected reminder, one subagent.
    _jsonl(roots.claude / "C--projects-game" / "s1.jsonl", [
        {"type": "custom-title", "customTitle": "인코딩 문제"},
        {"type": "user", "cwd": "C:\\projects\\game\\src", "timestamp": "2026-10-01T00:00:00Z",
         "message": {"role": "user", "content": "<system-reminder>ignore me</system-reminder>한글이 깨져 " + SECRET}},
        {"type": "assistant", "timestamp": "2026-10-01T00:01:00Z",
         "message": {"model": "claude-opus-5-5", "content": [
             {"type": "thinking", "thinking": "hidden"},
             {"type": "tool_use", "name": "Bash", "input": {"command": "python run.py"}}]}},
        {"type": "user", "timestamp": "2026-10-01T00:02:00Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "is_error": True, "content": "UnicodeEncodeError: 'cp949' codec"},
            {"type": "tool_result", "content": "ordinary output"}]}},
        {"type": "assistant", "timestamp": "2026-10-01T00:03:00Z",
         "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": "PYTHONIOENCODING=utf-8로 해결"}]}},
    ])
    _jsonl(roots.claude / "C--projects-game" / "s1" / "subagents" / "a1.jsonl", [
        {"type": "user", "cwd": "C:\\projects\\game", "message": {"role": "user", "content": "find files"}}])
    # Codex
    _jsonl(roots.codex / "2026" / "10" / "01" / "rollout-2026-10-01T00-00-00-01a1-2b2b-3c3c-4d4d-5e5e.jsonl", [
        {"type": "session_meta", "timestamp": "2026-10-01T00:00:00Z", "payload": {"cwd": "C:\\projects\\web"}},
        {"type": "turn_context", "payload": {"model": "gpt-5.5", "cwd": "C:\\projects\\web"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
                                              "content": [{"type": "input_text", "text": "빌드 실패"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{\"cmd\":\"npm run build\"}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "Exit code: 1\nModule not found"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "Exit code: 0\nok"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": "경로 수정함"}]}},
    ])
    # OpenCode: v1 session with an image part and a failing tool, plus a v2-only session.
    roots.opencode_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(roots.opencode_db)
    con.executescript("""
        create table session (id, parent_id, directory, title, agent, model, time_created, time_updated);
        create table session_v2 (id, parent_id, directory, title, agent, model, time_created, time_updated);
        create table message (id, session_id, time_created, data);
        create table part (id, message_id, session_id, time_created, data);
        create table session_message (id, session_id, type, seq, time_created, data);
    """)
    con.execute("insert into session values ('o1', null, 'C:/projects/tin', '에셋', 'build', ?, 1, 2)",
                (json.dumps({"id": "glm-5.3-flash-free"}),))
    con.execute("insert into session_v2 values ('o2', null, 'C:/projects/tin', '', 'build', null, 1, 3)")
    con.execute("insert into message values ('m1', 'o1', 1, ?)", (json.dumps({"role": "user"}),))
    con.execute("insert into message values ('m2', 'o1', 2, ?)", (json.dumps({"role": "assistant", "modelID": "glm-5.3-flash-free"}),))
    con.executemany("insert into part values (?, ?, 'o1', ?, ?)", [
        ("p1", "m1", 1, json.dumps({"type": "text", "text": "이미지 묶음 만들어"})),
        ("p2", "m1", 2, json.dumps({"type": "file", "url": "data:image/png;base64," + "A" * 5000})),
        ("p3", "m2", 3, json.dumps({"type": "tool", "tool": "read", "state": {
            "status": "error", "input": {"filePath": "README.md"}, "error": "File not found"}})),
        ("p4", "m2", 4, json.dumps({"type": "text", "text": "다른 경로로 읽음"})),
    ])
    con.execute("insert into session_message values ('x', 'o2', 'idle', 1, 1, ?)",
                (json.dumps({"error": {"type": "provider.auth", "status": 403}}),))
    con.commit()
    con.close()
    # Kiro
    roots.kiro.mkdir(parents=True, exist_ok=True)
    (roots.kiro / "k1.json").write_text(json.dumps({
        "session_id": "k1", "cwd": "C:\\projects\\tin", "title": None, "session_created_reason": "subagent",
        "created_at": "2026-09-26T00:00:00Z", "updated_at": "2026-09-26T01:00:00Z",
        "session_state": {"rts_model_state": {"model_info": {"model_id": "claude-opus-5.5"}}}}), encoding="utf-8")
    _jsonl(roots.kiro / "k1.jsonl", [
        {"kind": "Prompt", "data": {"content": [{"kind": "text", "data": "적 그림 그려"},
                                                {"kind": "image", "data": {"bytes": [1, 2]}}]}},
        {"kind": "AssistantMessage", "data": {"content": [{"kind": "thinking", "data": {"text": "hidden"}},
                                                          {"kind": "text", "data": "그렸음"}]}},
        # Results come both as objects and as plain strings.
        {"kind": "ToolResults", "data": {"content": [], "results": {
            "t1": {"tool": {}, "result": {"status": "error", "error": "permission denied"}},
            "t2": {"tool": {}, "result": "Traceback (most recent call last): boom"},
            "t3": {"tool": {}, "result": "ok"}}}},
    ])
    # Antigravity summaries DB with its FTS index
    roots.antigravity_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(roots.antigravity_db)
    con.executescript("""
        create table conversation_summaries (conversation_id, title, last_modified_time, step_count,
            workspace_uris, agent_name, parent_conversation_id);
        create virtual table conversations_fts using fts5(conversation_id UNINDEXED, chunk_index UNINDEXED,
            title, workspace, project, user_body, agent_body);
    """)
    con.execute("insert into conversation_summaries values ('g1', 'money 푸시', '2026-10-02', 65, "
                "'[\"file:///c%3A/projects/money\"]', null, null)")
    con.execute("insert into conversations_fts values ('g1', '0', '', '', '', '푸시 안 돼', 'credential manager 확인')")
    con.commit()
    con.close()
    return roots


def test_collects_all_five_sources_condensed_and_redacted(tmp_path) -> None:
    roots = _roots(tmp_path)
    store = SessionStore(tmp_path / "o.sqlite")
    report = collect(store, roots, Redactor({POOL_VALUE}))
    assert {k: v["found"] for k, v in report.items()} == {
        "claude": 2, "codex": 1, "kiro": 1, "antigravity": 1}
    assert all(v["failed"] == 0 for v in report.values())

    rows = {(r[0], r[1]): r for r in store.con.execute(
        "select source, session_id, project, title, models, text, n_errors, parent_id from sessions")}
    claude = rows[("claude", "s1")]
    assert claude[2] == "game" and claude[3] == "인코딩 문제" and "claude-opus-5-5" in claude[4]
    text = claude[5]
    assert "[U] 한글이 깨져" in text and "ignore me" not in text and "hidden" not in text
    assert "[T] Bash:" in text and "[E] UnicodeEncodeError" in text and "ordinary output" not in text
    assert SECRET not in text and MASK in text
    assert rows[("claude", "s1/a1")][7] == "s1"

    codex = next(v for k, v in rows.items() if k[0] == "codex")
    assert codex[2] == "web" and "gpt-5.5" in codex[4] and codex[6] == 1
    assert "Module not found" in codex[5] and "ok" not in codex[5].split("Module not found")[1]

    assert not any(k[0] == "opencode" for k in rows)

    kiro = rows[("kiro", "k1")]
    assert "[U] 적 그림 그려" in kiro[5] and "[A] 그렸음" in kiro[5] and "hidden" not in kiro[5]
    assert kiro[6] == 2 and "permission denied" in kiro[5] and "boom" in kiro[5]
    ag = rows[("antigravity", "g1")]
    assert ag[2] == "money" and "credential manager" in ag[5]


def test_unchanged_sessions_are_skipped_and_changed_ones_reloaded(tmp_path) -> None:
    roots = _roots(tmp_path)
    store = SessionStore(tmp_path / "o.sqlite")
    collect(store, roots, Redactor())
    again = collect(store, roots, Redactor())
    assert all(v["same"] == v["found"] for v in again.values())
    import json as _json
    k = roots.kiro / "k1.json"
    k.write_text(_json.dumps(dict(_json.loads(k.read_text(encoding="utf-8")), title="바뀜")), encoding="utf-8")
    assert collect(store, roots, Redactor(), ["kiro"])["kiro"]["changed"] == 1


def test_redactor_masks_pool_values_key_shapes_and_assignments() -> None:
    r = Redactor({POOL_VALUE})
    out = r(f"pool {POOL_VALUE} key AIza{'x' * 35} OPENAI_API_KEY=abcd1234efgh aws AKIAABCDEFGHIJKLMNOP "
            "token count 12 Bearer abcdefghijklmnopqrstuvwxyz")
    assert POOL_VALUE not in out and "AIza" not in out and "abcd1234efgh" not in out
    assert "AKIAABCDEFGHIJKLMNOP" not in out and "abcdefghijklmnopqrstuvwxyz" not in out
    assert "OPENAI_API_KEY=" in out and "token count 12" in out


def test_project_of_prefers_the_folder_under_projects() -> None:
    assert project_of("C:\\projects\\all-tomorrow\\src") == "all-tomorrow"
    assert project_of("C:/Users/x/Desktop/common/.프로그램/wobnovel") == "wobnovel"
    assert project_of("") == ""
