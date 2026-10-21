import json

from all_tomorrow.overseer import distill, metacog, oracle, store as store_mod
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore, open_peer, peer_paths


def _pc(base, sid, project, card):
    s = SessionStore(base / "overseer.sqlite")
    distill.ensure_schema(s.con)
    sess = Session("codex", sid, cwd=f"C:\\projects\\{project}", title=sid, updated_at="2026-10-20T00:00:00")
    sess.lines = ["[U] x"]
    s.put(sess, "fp", lambda t: t)
    s.commit()
    distill.distill_session(s.con, "codex", sid, redact=Redactor(), secrets=frozenset(),
                            chat=lambda g, sy, u: ([card], "d"))
    return s


def test_published_store_is_read_by_the_other_pc_for_oracle_and_metacog(tmp_path, monkeypatch) -> None:
    a, b = tmp_path / "aaaa", tmp_path / "dp7"
    a.mkdir(), b.mkdir()
    monkeypatch.setattr(store_mod, "host_name", lambda: "aaaa")
    sa = _pc(a, "a1", "web", {"problem": "OpenRouter 402 Payment Required", "solution": "max_tokens 4096",
                              "outcome": "해결"})
    published = sa.publish(a)
    assert published.name == "aaaa.sqlite" and json.loads("[]") == []

    # Both bases share tmp_path/peers here, as Syncthing makes ~/.all-tomorrow/peers shared.
    monkeypatch.setattr(store_mod, "host_name", lambda: "dp7")
    monkeypatch.setattr(metacog, "host_name", lambda: "dp7")
    sb = _pc(b, "b1", "game", {"problem": "Godot 셰이더 컴파일 실패", "solution": "", "outcome": "미해결"})
    assert [p.name for p in peer_paths(b)] == ["aaaa.sqlite"]

    peers = [open_peer(p) for p in peer_paths(b)]
    answer = oracle.ask(sb.con, "OpenRouter 402 Payment Required 오류", caller="claude", peers=peers)
    assert answer["found"] and answer["cards"][0]["solution"] == "max_tokens 4096"

    seen = {}

    def reasoner(prompt, workdir):
        seen["snap"] = json.loads(open(prompt.split("스냅샷 파일: ")[1].split("\n")[0], encoding="utf-8").read())
        return json.dumps({"observations": [], "actions": [], "notes": ""})

    metacog.wake(sb.con, b, redact=Redactor(), projects=None, notion=None, reasoner=reasoner)
    snap = seen["snap"]
    assert {s["host"] for s in snap["changed_sessions"]} == {"aaaa", "dp7"}
    assert snap["system"]["this_pc"] == "dp7" and snap["system"]["other_pcs"] == {"aaaa": {"codex": 1}}
    for p in peers:
        p.close()
