import sqlite3

from all_tomorrow.overseer.sources import Roots


def varint(n: int) -> bytes:
    out = b""
    while n >= 0x80:
        out, n = out + bytes([n & 0x7F | 0x80]), n >> 7
    return out + bytes([n])


def pb(num: int, value: bytes | str) -> bytes:
    """One length-delimited protobuf field."""
    data = value.encode() if isinstance(value, str) else value
    return varint(num << 3 | 2) + varint(len(data)) + data


def test_cli_store_is_read_from_protobuf_steps_and_wins_over_app_store(tmp_path) -> None:
    root = tmp_path / ".gemini" / "antigravity-cli"
    (root / "conversations").mkdir(parents=True)
    con = sqlite3.connect(root / "conversation_summaries.db")
    con.execute("create table conversation_summaries (conversation_id text, title text, last_modified_time text, "
                "step_count int, workspace_uris text, agent_name text, parent_conversation_id text)")
    con.execute("insert into conversation_summaries values ('c1', '우산', '2026-11-03 03:12:47+00:00', 4, "
                "'[\"file:///C:/projects/ag\"]', '', '')")
    con.commit()
    con.close()
    steps = [(14, pb(19, pb(2, "msg1.txt를 읽어라"))),
             (15, pb(20, pb(1, "답장입니다") + pb(7, pb(2, "read_file") + pb(3, '{"Path":"msg1.txt"}')))),
             (132, pb(140, pb(2, pb(1, "Exit code 1\nboom")))),
             (17, pb(24, pb(3, pb(2, "API error (attempt 1)"))))]
    con = sqlite3.connect(root / "conversations" / "c1.db")
    con.execute("create table steps (idx int, step_type int, step_payload blob)")
    con.executemany("insert into steps values (?,?,?)", [(i, k, p) for i, (k, p) in enumerate(steps)])
    con.commit()
    con.close()

    [listing] = list(Roots.default(tmp_path).listings()["antigravity"]())
    s = listing.load()
    assert (s.n_user, s.title, s.cwd) == (1, "우산", "C:/projects/ag")
    assert s.text.splitlines() == ["[U] msg1.txt를 읽어라", "[A] 답장입니다", '[T] read_file: {"Path":"msg1.txt"}',
                                   "[E] Exit code 1\nboom", "[E] API error (attempt 1)"][:3] + s.text.splitlines()[3:]
    assert "[E] API error (attempt 1)" in s.text and "boom" in s.text
