from fastapi.testclient import TestClient

from all_tomorrow.console.ideas import parse_results
from all_tomorrow.web import Auth, create_app


def result(idea_id: str, sid: str, title: str, body: str, status: str = "완료") -> str:
    return (f"=== 자료봉 결과 ===\n아이디어 ID: {idea_id}\n하위과제 ID: {sid}\n하위과제: {title}\n상태: {status}\n---\n"
            f"## 결론\n{body}\n## 주장과 근거\n- [C1] 비슷한 서비스가 있다\n  - 출처: https://example.com/a\n"
            f"  - 인용: \"we make covers\"\n  - 구분: 확인\n- [C2] 시장이 크다\n  - 구분: 추정\n=== 끝 ===")


def test_parse_results_splits_blocks_and_keeps_unformatted_text() -> None:
    text = "잡담\n" + result("I-1", "s1", "기존 서비스", "있다") + "\n\n" + result("I-1", "S2", "수요", "있음")
    parsed = parse_results(text)
    assert [(p["idea_id"], p["subtask_id"], p["subtask_title"]) for p in parsed] == [
        ("I-1", "S1", "기존 서비스"), ("I-1", "S2", "수요")]
    assert parsed[0]["body"].startswith("## 결론") and parsed[0]["status"] == "완료"
    assert parsed[0]["claims"] == [
        {"id": "C1", "claim": "비슷한 서비스가 있다", "source": "https://example.com/a", "quote": '"we make covers"', "kind": "확인"},
        {"id": "C2", "claim": "시장이 크다", "source": "", "quote": "", "kind": "추정"}]
    assert parse_results(result("I-1", "S3", "x", "y", status="불완전 | 실패"))[0]["status"] == "불완전"
    loose = parse_results("형식 없이 온 답")
    assert loose == [{"idea_id": "", "subtask_id": "", "subtask_title": "", "status": "", "claims": [],
                      "body": "형식 없이 온 답"}]


def test_idea_desk_flow_prompt_paste_list_and_brief(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/api/ideas").status_code == 401
        c.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert "/static/console/pages/ideas.js" in c.get("/").text
        idea = c.post("/api/ideas", json={"text": "웹소설 표지 자동 생성기\n작가가 줄거리를 넣으면 표지를 만든다"}).json()
        iid = idea["id"]
        assert idea["title"] == "웹소설 표지 자동 생성기"
        assert f"아이디어 ID: {iid}" in idea["prompt"] and "작가가 줄거리를" in idea["prompt"]
        assert "{idea_id}" not in idea["prompt"]
        for field in ("idea_brief", "task_id", "objective", "scope", "exclusions", "source_policy",
                      "deliverables", "completion_rule", "교차검증", "현장검증", "핵심 불확실성"):
            assert field in idea["prompt"]

        other = c.post(f"/api/ideas/{iid}/results", json={"text": result("I-000000-zzzz", "S1", "x", "y")})
        assert other.status_code == 422
        paste = result(iid, "S1", "기존 서비스", "옛 결과") + "\n" + result(iid, "S2", "수요", "수요 있음")
        assert c.post(f"/api/ideas/{iid}/results", json={"text": paste}).json()["added"] == [
            {"subtask_id": "S1", "subtask_title": "기존 서비스", "status": "완료", "claims": 2},
            {"subtask_id": "S2", "subtask_title": "수요", "status": "완료", "claims": 2}]
        c.post(f"/api/ideas/{iid}/results", json={"text": result(iid, "S1", "기존 서비스", "새 결과", "불완전")})

        listed = c.get("/api/ideas").json()
        assert listed[0]["id"] == iid and listed[0]["results"] == 3 and listed[0]["subtasks"] == 2
        detail = c.get(f"/api/ideas/{iid}").json()
        assert len(detail["pastes"]) == 2
        brief = detail["brief"]
        assert "새 결과" in brief.split("## 붙여넣은 원문")[0] and "옛 결과" not in brief.split("## 붙여넣은 원문")[0]
        assert "옛 결과" in brief  # raw pastes stay in full
        assert "| S1 기존 서비스 | 불완전 | 2 | 1 | 1 |" in brief
        assert detail["results"][0]["claims"][0]["source"] == "https://example.com/a"
        assert c.get("/api/ideas/I-nope").status_code == 404

    on_disk = (tmp_path / "ideas" / "briefs" / f"{iid}.md").read_text(encoding="utf-8")
    assert on_disk == brief
    assert (tmp_path / "ideas" / "ideas.sqlite").exists()


def test_plan_paste_and_deletes(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": "owner", "password": "correct horse"})
        iid = c.post("/api/ideas", json={"text": "아이디어"}).json()["id"]
        assert c.put(f"/api/ideas/{iid}/plan", json={"text": "## 과제 표\n| S1 | 기존 서비스 | 독립 |"}).status_code == 200
        detail = c.get(f"/api/ideas/{iid}").json()
        assert detail["plan"].startswith("## 과제 표") and detail["plan_at"]
        assert "| S1 | 기존 서비스 | 독립 |" in detail["brief"].split("## 정리본")[0]

        c.post(f"/api/ideas/{iid}/results", json={"text": result(iid, "S1", "a", "첫째")})
        c.post(f"/api/ideas/{iid}/results", json={"text": result(iid, "S2", "b", "둘째")})
        rid = next(r["id"] for r in c.get(f"/api/ideas/{iid}").json()["results"] if r["subtask_id"] == "S2")
        assert c.delete(f"/api/ideas/{iid}/results/{rid}").status_code == 204
        assert c.delete(f"/api/ideas/{iid}/results/{rid}").status_code == 404
        detail = c.get(f"/api/ideas/{iid}").json()
        assert [r["subtask_id"] for r in detail["results"]] == ["S1"] and len(detail["pastes"]) == 1
        assert "둘째" not in detail["brief"]

        assert c.delete(f"/api/ideas/{iid}").status_code == 204
        assert c.get(f"/api/ideas/{iid}").status_code == 404
        assert c.get("/api/ideas").json() == []
    assert not (tmp_path / "ideas" / "briefs" / f"{iid}.md").exists()


def test_history_status_counts_and_overseer_summary(tmp_path) -> None:
    from datetime import UTC, datetime, timedelta

    from all_tomorrow.console.ideas import IdeaStore

    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("공모전 알림", "본문")
    store.set_plan(iid, "첫 쪼개기")
    store.set_plan(iid, "둘째 쪼개기")
    store.add_results(iid, result(iid, "S1", "a", "옛", "실패"))
    store.add_results(iid, result(iid, "S1", "a", "새", "완료") + result(iid, "S2", "b", "x", "불완전"))
    idea = store.get(iid)
    assert [p["text"] for p in idea["plans"]] == ["둘째 쪼개기", "첫 쪼개기"]
    assert [(r["subtask_id"], r["status"], r["latest"]) for r in idea["results"]] == [
        ("S2", "불완전", True), ("S1", "완료", True), ("S1", "실패", False)]
    assert "첫 쪼개기" in store.brief(iid)  # replaced decompositions stay in the brief
    listed = store.list()[0]
    assert listed["subtasks"] == 2 and listed["results"] == 3
    assert listed["status_counts"] == {"완료": 1, "불완전": 1, "실패": 0, "": 0}
    summary = store.recent_summary(7)
    assert iid in summary and "완료 1/불완전 1/실패 0" in summary and str(store.briefs / f"{iid}.md") in summary
    assert "없음" in store.recent_summary(7, datetime.now(UTC) + timedelta(days=8))
