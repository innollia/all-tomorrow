import json

from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app


def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ALL_TOMORROW_STUDY_REPO", str(tmp_path / "study"))
    c = TestClient(create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path / "console")), base_url="https://testserver")
    c.__enter__()
    return c


def test_merges_plan_with_both_learners_progress_and_writes_nothing(tmp_path, monkeypatch) -> None:
    data = tmp_path / "study/data"
    data.mkdir(parents=True)
    plan = {"days": [{"id": "D1", "date": "2026-11-03", "theme": "지도"}, {"id": "D2", "date": "2026-11-04", "theme": "선택"}]}
    progress = {"days": {"D1": {"pai": {"status": "done", "date": "2026-11-03", "actual_min": 75, "note": "끝"}}}}
    (data / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (data / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    before = (data / "progress.json").read_bytes()
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/study").status_code == 401
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    d1, d2 = c.get("/api/study").json()["days"]
    assert d1["theme"] == "지도"
    assert d1["progress"]["pai"] == {"status": "done", "date": "2026-11-03", "actual_min": 75, "note": "끝"}
    assert d1["progress"]["innollia"]["status"] == "todo"
    assert d2["progress"]["pai"]["status"] == "todo"
    assert (data / "progress.json").read_bytes() == before


def test_missing_plan_is_a_readable_error(tmp_path, monkeypatch) -> None:
    c = client(tmp_path, monkeypatch)
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    r = c.get("/api/study")
    assert r.status_code == 503 and "공부 계획" in r.text
