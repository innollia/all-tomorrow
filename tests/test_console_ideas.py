from fastapi.testclient import TestClient

from all_tomorrow.console.ideas import parse_results
from all_tomorrow.web import Auth, create_app


def result(idea_id: str, sid: str, title: str, body: str) -> str:
    return (f"=== 자료봉 결과 ===\n아이디어 ID: {idea_id}\n하위과제 ID: {sid}\n하위과제: {title}\n---\n"
            f"## 결론\n{body}\n=== 끝 ===")


def test_parse_results_splits_blocks_and_keeps_unformatted_text() -> None:
    text = "잡담\n" + result("I-1", "s1", "기존 서비스", "있다") + "\n\n" + result("I-1", "S2", "수요", "있음")
    parsed = parse_results(text)
    assert [(p["idea_id"], p["subtask_id"], p["subtask_title"]) for p in parsed] == [
        ("I-1", "S1", "기존 서비스"), ("I-1", "S2", "수요")]
    assert parsed[0]["body"].startswith("## 결론")
    loose = parse_results("형식 없이 온 답")
    assert loose == [{"idea_id": "", "subtask_id": "", "subtask_title": "", "body": "형식 없이 온 답"}]


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

        other = c.post(f"/api/ideas/{iid}/results", json={"text": result("I-000000-zzzz", "S1", "x", "y")})
        assert other.status_code == 422
        paste = result(iid, "S1", "기존 서비스", "옛 결과") + "\n" + result(iid, "S2", "수요", "수요 있음")
        assert c.post(f"/api/ideas/{iid}/results", json={"text": paste}).json()["added"] == [
            {"subtask_id": "S1", "subtask_title": "기존 서비스"}, {"subtask_id": "S2", "subtask_title": "수요"}]
        c.post(f"/api/ideas/{iid}/results", json={"text": result(iid, "S1", "기존 서비스", "새 결과")})

        listed = c.get("/api/ideas").json()
        assert listed[0]["id"] == iid and listed[0]["results"] == 3 and listed[0]["subtasks"] == 2
        detail = c.get(f"/api/ideas/{iid}").json()
        assert len(detail["pastes"]) == 2
        brief = detail["brief"]
        assert "새 결과" in brief.split("## 붙여넣은 원문")[0] and "옛 결과" not in brief.split("## 붙여넣은 원문")[0]
        assert "옛 결과" in brief  # raw pastes stay in full
        assert c.get("/api/ideas/I-nope").status_code == 404

    on_disk = (tmp_path / "ideas" / "briefs" / f"{iid}.md").read_text(encoding="utf-8")
    assert on_disk == brief
    assert (tmp_path / "ideas" / "ideas.sqlite").exists()
