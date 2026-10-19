import hashlib
import json
import os
import sqlite3

from all_tomorrow import projects_snapshot as ps
from all_tomorrow.project_panels import plugins, wobnovel

STATUS = """# 현재 구현 상태

## 태그팁 작품별 옵트인 — 2026-10-19

- 작가 결정: 작품마다 고른 것만 넣는다.
- 검증: pytest 통과.
- 미확인: 실제 브라우저 화면 확인은 하지 않았다.
- **미확인**: 로그인 안 된 claude.exe로 모델 턴을 못 돌렸다.
- 미확인:
  - 1440px 겹침
  - 390px 스크롤
본문 중간의 미확인 언급은 항목이 아니다.

## 터미널 엔진 추가 — 2026-10-18

- 미확인: 없음

## 이전 기록

### 2026-10-12 승인 후 적용

## 2026-10-16 중계 프롬프트 정리

- 미확인: 오래된 항목
"""


def _studio_db(path):
    db = path / ".studio" / "studio-muvel.sqlite3"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE studio_sessions (session_id TEXT PRIMARY KEY, work_id TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE studio_runs (run_id TEXT PRIMARY KEY, session_id TEXT, work_id TEXT, status TEXT, engine TEXT,
                                  error_json TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE studio_approvals (approval_id TEXT PRIMARY KEY, proposed_content TEXT, status TEXT, created_at TEXT);
        CREATE TABLE document_revisions (document_id TEXT, revision INTEGER, content TEXT, PRIMARY KEY(document_id, revision));
    """)
    con.executemany("insert into studio_sessions values (?,?,?,?)", [(f"s{i}", "w1", "t", "t") for i in range(3)])
    con.executemany("insert into studio_runs values (?,?,?,?,?,?,?,?)", [
        (f"run-{i:02d}-aaaaaaaa", "s0", "work-uuid-1" if i % 2 else "unknown", status, "codex", None,
         f"2026-10-1{i}T00:00:00.000Z", f"2026-10-1{i}T01:00:00.000Z")
        for i, status in enumerate(["succeeded", "failed", "canceled", "interrupted", "running", "queued", "succeeded"])])
    con.executemany("insert into studio_approvals values (?,?,?,?)", [
        ("a1", "SECRET MANUSCRIPT", "pending", "t"), ("a2", "x", "pending", "t"), ("a3", "x", "applied", "t")])
    con.executemany("insert into document_revisions values (?,?,?)", [("d", i, "본문 원고") for i in range(4)])
    con.commit()
    con.close()
    return db


def _works(root):
    for name, work_id, episodes in (("헌터보험", "work-uuid-1", 3), ("빈작품", "work-uuid-2", 0)):
        folder = root / name
        (folder / "episodes" / "snapshots").mkdir(parents=True)
        (folder / f"{name}.muvl").write_text(json.dumps({"id": work_id, "title": "긴 제목", "description": "줄거리"}),
                                              encoding="utf-8")
        for i in range(episodes):
            ep = folder / "episodes" / f"ep{i}.mvle"
            ep.write_text("회차 원고 본문", encoding="utf-8")
            os.utime(ep, (1_760_000_000 + i * 100, 1_760_000_000 + i * 100))
        (folder / "episodes" / "notes.txt").write_text("x", encoding="utf-8")
    (root / ".git").mkdir()
    (root / "loose-folder").mkdir()


def _project(tmp_path):
    project = tmp_path / "wobnovel"
    (project / "docs" / "tracking").mkdir(parents=True)
    (project / "docs" / "tracking" / "status.md").write_text(STATUS, encoding="utf-8")
    (project / "novelpiacr").mkdir()
    (project / "novelpiacr" / "config.json").write_text('{"cookie": "SESSION-COOKIE-VALUE"}', encoding="utf-8")
    return project


def test_collect_reads_status_studio_and_works(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    db = _studio_db(project)
    _works(tmp_path / "MuvelProjects")
    monkeypatch.setattr(wobnovel, "works_root", lambda: tmp_path / "MuvelProjects")
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    panel = wobnovel.collect(project)

    status = panel["status"]
    assert (status["title"], status["date"], status["unverified"]) == ("태그팁 작품별 옵트인", "2026-10-19", 4)
    assert [r["date"] for r in status["recent"]] == ["2026-10-19", "2026-10-18", "2026-10-16"]
    assert status["recent"][1]["unverified"] == 0 and status["recent"][2]["title"] == "중계 프롬프트 정리"

    studio = panel["studio"]
    assert studio["approvals_pending"] == 2
    assert (studio["sessions"], studio["runs"], studio["revisions"]) == (3, 7, 4)
    runs = studio["recent_runs"]
    assert [r["status"] for r in runs] == ["succeeded", "queued", "running", "interrupted", "canceled"]
    assert runs[0] == {"id": "run-06-a", "status": "succeeded", "engine": "codex", "work": None,
                       "at": "2026-10-16T00:00:00.000Z", "updated": "2026-10-16T01:00:00.000Z"}
    assert runs[1]["work"] == "헌터보험"

    works = panel["works"]
    assert works["found"] and [w["title"] for w in works["items"]] == ["헌터보험", "빈작품"]
    assert works["items"][0]["episodes"] == 3 and works["items"][0]["newest"].startswith("2025-10-09T08:56:40")
    assert works["items"][1] == {"title": "빈작품", "episodes": 0, "newest": None}

    encoded = json.dumps(panel, ensure_ascii=False)
    for private in ("SESSION-COOKIE", "원고", "SECRET", "줄거리", "work-uuid"):
        assert private not in encoded
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert not list(db.parent.glob("*-journal")) and not list(db.parent.glob("*-wal"))


def test_missing_sources_degrade_and_plugin_is_registered(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wobnovel, "works_root", lambda: tmp_path / "nowhere")
    assert wobnovel.collect(tmp_path) == {"status": None, "studio": None, "works": {"found": False, "items": []}}
    assert plugins()["wobnovel"] is wobnovel
    item = ps.collect_project("wobnovel", {"path": str(tmp_path)}, plugins())
    assert item["panel"]["works"]["found"] is False


def test_unreadable_studio_db_reports_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wobnovel, "works_root", lambda: tmp_path / "nowhere")
    db = tmp_path / ".studio" / "studio-muvel.sqlite3"
    db.parent.mkdir()
    db.write_bytes(b"not a database" * 100)
    assert wobnovel.collect(tmp_path)["studio"] == {"error": "DatabaseError"}
