import sqlite3

from all_tomorrow.overseer import distill, knowhow
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.sources import Session
from all_tomorrow.overseer.store import SessionStore

SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"

CARDS = [
    ("claude", "a1", "alpha", {"problem": "godot 씬 로드 시 GDScript 파싱 오류 Identifier not declared",
                               "solution": "autoload 이름을 project.godot에 등록하고 편집기를 재시작한다 (key " + SECRET + ")", "outcome": "해결"}),
    ("codex", "a2", "beta", {"problem": "godot 씬 로드 시 GDScript 파싱 오류 Identifier not declared 발생",
                             "solution": "autoload 이름을 project.godot에 등록하고 편집기를 재시작한다", "outcome": "해결"}),
    ("claude", "a3", "alpha", {"problem": "unity prefab 참조가 끊어져 Missing 표시", "solution": "meta 파일을 함께 커밋하고 GUID를 유지한다",
                               "outcome": "해결"}),
    ("claude", "a4", "alpha", {"problem": "pygame 창이 닫히지 않음", "solution": "", "outcome": "미해결"}),
    ("codex", "a5", "alpha", {"problem": "PowerShell에서 UnicodeEncodeError cp949 출력 오류", "solution": "PYTHONIOENCODING=utf-8 환경변수를 설정한다",
                              "outcome": "해결"}),
    ("codex", "a6", "beta", {"problem": "sqlite database is locked 오류가 반복됨", "solution": "busy_timeout을 늘리고 쓰기 트랜잭션을 짧게 유지한다",
                             "outcome": "Resolved"}),
]


def _store(tmp_path):
    store = SessionStore(tmp_path / "overseer.sqlite")
    distill.ensure_schema(store.con)
    for source, sid, project, card in CARDS:
        s = Session(source, sid, cwd=rf"C:\projects\{project}", agent=source)
        s.lines = ["[U] x"]
        store.put(s, "fp", lambda t: t)
        store.commit()
        distill.distill_session(store.con, source, sid, redact=Redactor(), secrets=frozenset(),
                                chat=lambda g, sy, u, c=card: ([dict(c, situation=[])], "d"))
    store.close()
    return tmp_path


def test_select_queries_card_db_merges_duplicates_and_skips_unsolved(tmp_path) -> None:
    base = _store(tmp_path / "ov")
    lessons = knowhow.select(base, "godot-game", [], 10, known={"alpha", "beta"})
    merged = [l for l in lessons if "autoload" in l["solution"]]
    assert len(merged) == 1 and len(merged[0]["sources"]) == 2              # godot pair merged, both card ids kept
    assert merged[0]["projects"] == ["alpha", "beta"] and merged[0]["scope"] == "common" and merged[0]["fts"] > 0
    assert not any("unity" in l["problem"] for l in lessons)                # other engine's lesson stays out
    assert not any("pygame" in l["problem"] for l in lessons)               # unsolved card skipped


def test_seed_picks_by_stack_never_overwrites_links_and_masks_secrets(tmp_path) -> None:
    base = _store(tmp_path / "ov")
    project = tmp_path / "newgame"
    project.mkdir()
    (project / "project.godot").write_text("", encoding="utf-8")
    (project / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
    (project / "docs").mkdir()
    (project / "docs" / "knowhow.md").write_text("my own notes", encoding="utf-8")
    result = knowhow.seed(project, base=base, use_jev=False, redact=Redactor({SECRET}))
    assert result["kind"] == "godot-game" and result["file"].endswith("knowhow-seed.md") and result["lessons"] >= 1
    assert (project / "docs" / "knowhow.md").read_text(encoding="utf-8") == "my own notes"
    seed_text = (project / "docs" / "knowhow-seed.md").read_text(encoding="utf-8")
    assert "autoload" in seed_text and "unity" not in seed_text.lower()       # other engine's lesson stays out
    assert SECRET not in seed_text and "출처 카드" in seed_text
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# mine") and "docs/knowhow-seed.md" in agents
    knowhow.seed(project, base=base, use_jev=False, redact=Redactor())       # idempotent link
    assert (project / "AGENTS.md").read_text(encoding="utf-8").count("knowhow-seed.md") == 2   # link text + target, once


def test_seed_without_cards_writes_nothing(tmp_path) -> None:
    empty = tmp_path / "ov"
    empty.mkdir()
    sqlite3.connect(empty / "overseer.sqlite").execute("create table cards (card_id text)").connection.close()  # no cards_fts
    project = tmp_path / "p"
    project.mkdir()
    result = knowhow.seed(project, base=empty, kind="python-service", use_jev=False, redact=Redactor())
    assert result["lessons"] == 0 and "skipped" in result
    assert not (project / "docs").exists() and not (project / "AGENTS.md").exists()


def test_jev_filter_drops_not_applicable_and_survives_failure(tmp_path) -> None:
    base = _store(tmp_path / "ov")
    lessons = knowhow.select(base, None, ["godot", "unity", "sqlite", "python"], 10, known={"alpha", "beta"})
    assert lessons
    calls = []

    def ask(state, questions):
        calls.append(len(questions))
        return {lid: {"probabilities": {"적용": 0.1, "해당 없음": 0.9}} for lid in questions}

    kept, note = knowhow.jev_filter(lessons, {}, ask)
    assert kept == [] and calls == [len(lessons)] and "제외" in note       # one request for all candidates

    def broken(state, questions):
        raise RuntimeError("down")

    kept, note = knowhow.jev_filter(lessons, {}, broken)
    assert kept == lessons and "규칙만" in note


def test_resolve_project_and_outcomes() -> None:
    known = {"TINProject", "all-tomorrow"}
    assert knowhow.resolve_project("decision", r"C:\Users\x\Desktop\TINProject-avatar-judge\tools\decision", known) == "TINProject"
    assert knowhow.resolve_project("subagent_ab12cd34", "", known) == ""
    assert knowhow.resolve_project("projects", r"C:\projects", known) == ""
    assert knowhow.is_solved("해결") and knowhow.is_solved("Resolved") and not knowhow.is_solved("미해결") and not knowhow.is_solved("unresolved")
