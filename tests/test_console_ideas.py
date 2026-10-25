import re

import pytest

from fastapi.testclient import TestClient

from all_tomorrow.console.ideas import parse_results
from all_tomorrow.web import Auth, create_app


def result(idea_id: str, sid: str, title: str, body: str, status: str = "완료") -> str:
    return (f"=== 자료봉 결과 ===\n아이디어 ID: {idea_id}\n하위과제 ID: {sid}\n하위과제: {title}\n상태: {status}\n---\n"
            f"## 결론\n{body}\n## 주장과 근거\n- [C1] 비슷한 서비스가 있다\n  - 출처: https://example.com/a\n"
            f"  - 인용: \"we make covers\"\n  - 구분: 확인\n- [C2] 시장이 크다\n  - 구분: 추정\n=== 끝 ===")


def test_parse_results_splits_blocks_and_keeps_unformatted_text() -> None:
    text = "잡담\n" + result("I-261025-00a1", "s1", "기존 서비스", "있다") + "\n\n" + result("I-261025-00a1", "S2", "수요", "있음")
    parsed = parse_results(text)
    assert [(p["idea_id"], p["subtask_id"], p["subtask_title"]) for p in parsed] == [
        ("I-261025-00a1", "S1", "기존 서비스"), ("I-261025-00a1", "S2", "수요")]
    assert parsed[0]["body"].startswith("## 결론") and parsed[0]["status"] == "완료"
    assert parsed[0]["claims"] == [
        {"id": "C1", "claim": "비슷한 서비스가 있다", "source": "https://example.com/a", "quote": '"we make covers"', "kind": "확인"},
        {"id": "C2", "claim": "시장이 크다", "source": "", "quote": "", "kind": "추정"}]
    assert parse_results(result("I-261025-00a1", "S3", "x", "y", status="불완전 | 실패"))[0]["status"] == "불완전"
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

        other = c.post(f"/api/ideas/{iid}/results", json={"text": result("I-000000-ffff", "S1", "x", "y")})
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
        current = brief.split("## 덮어쓴 이전 결과")[0]
        assert "새 결과" in current and "옛 결과" not in current
        assert brief.count("옛 결과") == 1  # replaced results stay, once
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


MESSY = [
    # Header (and body) squashed onto one line, as 자료봉 output arrived in real use.
    ("=== 자료봉 결과 === 아이디어 ID: I-261025-62d7 하위과제 ID: S1 하위과제: 경쟁 제품·대체재 분석 상태: 완료 "
     "기준 시점: 2026-10-25 --- ## 결론 (3줄 이내) 대체재가 많다 ## 주장과 근거 - [C1] 앱이 있다 === 끝 ===",
     ("I-261025-62d7", "S1", "경쟁 제품·대체재 분석", "완료")),
    # Markdown bold and inline code around labels and values.
    ("**=== 자료봉 결과 ===**\n**아이디어 ID:** `I-261025-62D7`\n**하위과제 ID:** **S2**\n**하위과제:** 수요·지불 의사\n"
     "**상태:** 불완전 (일부만)\n\n---\n\n## 결론\n수요는 있다\n## 주장과 근거\n- **[C1]** 커뮤니티 글이 많다\n"
     "- 출처: https://example.com/x\n- 구분: 확인\n**=== 끝 ===**",
     ("I-261025-62d7", "S2", "수요·지불 의사", "불완전")),
    # Wrapped in a code fence, task_id form, labels reordered, no end marker before the next block.
    ("```\n=== 자료봉 결과 ===\n상태: 실패\ntask_id: I-261025-62d7 / s3\n과제: 가격 모델\n---\n## 결론\n근거 없음\n```\n"
     "=== 자료봉 결과 ===\n하위과제 ID: S4\n아이디어 ID: I-261025-62d7\n하위과제: 법·정책\n상태: 완료\n---\n## 결론\n괜찮다\n=== 끝 ===",
     ("I-261025-62d7", "S3", "가격 모델", "실패")),
]


def test_parser_tolerates_messy_researcher_output() -> None:
    for text, expected in MESSY:
        first = parse_results(text)[0]
        assert (first["idea_id"], first["subtask_id"], first["subtask_title"], first["status"]) == expected, text[:60]
    bold = parse_results(MESSY[1][0])[0]
    assert bold["claims"] == [{"id": "C1", "claim": "커뮤니티 글이 많다", "source": "https://example.com/x",
                               "quote": "", "kind": "확인"}]
    two = parse_results(MESSY[2][0])
    assert [(p["subtask_id"], p["subtask_title"]) for p in two] == [("S3", "가격 모델"), ("S4", "법·정책")]


def test_messy_paste_is_accepted_for_its_own_idea(tmp_path) -> None:
    from all_tomorrow.console.ideas import IdeaStore

    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("t", "본문")
    paste = re.sub("(?i)I-261025-62d7", iid, MESSY[0][0] + "\n" + MESSY[1][0])
    added = store.add_results(iid, paste)
    assert [(a["subtask_id"], a["status"]) for a in added] == [("S1", "완료"), ("S2", "불완전")]


def test_prompt_asks_for_growth_cases_business_forms_and_language_markets(tmp_path) -> None:
    from all_tomorrow.console.ideas import IdeaStore

    store = IdeaStore(tmp_path / "ideas")
    prompt = store.get(store.create("t", "웹소설 집필 도구"))["prompt"]
    for phrase in ("성장 궤적", "처음 내놓은 형태", "초기 완성도", "관심이 붙은 경로", "확장 경로", "성공 / 정체 / 실패 / 미상",
                   "범주 대표성", "모듈", "완성된 하나의 프로그램", "각각", "뭉뚱그려", "언어권", "선점"):
        assert phrase in prompt, phrase


def test_brief_holds_each_result_once_and_plan_box_refuses_results(tmp_path) -> None:
    from all_tomorrow.console.ideas import META_PROMPT, IdeaStore, looks_like_results

    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("t", "본문")
    paste = "\\" + result(iid, "S1", "가", "첫본문") + "\n머리말 밖 메모\n" + result(iid, "S2", "나", "둘본문")
    store.add_results(iid, paste)
    store.add_results(iid, result(iid, "S1", "가", "새본문"))

    # Real incident: the whole result paste was saved as the decomposition, then "." over it because
    # an empty plan box could not be saved. Legacy rows like that are written directly here.
    with store.db() as db:
        db.execute("INSERT INTO plans (idea_id, text, created_at) VALUES (?,?,?)", (iid, paste, "2026-10-25T01:18:23+00:00"))
    store.set_plan(iid, ".")
    brief = store.brief(iid)
    for body in ("첫본문", "둘본문", "새본문"):
        assert brief.count(body) == 1, body
    assert "잘못 넣은 기록" in brief and "머리말 밖 메모" in brief and "하위과제 ID: S2" in brief

    assert looks_like_results(paste) and not looks_like_results(META_PROMPT)
    with pytest.raises(ValueError):
        store.set_plan(iid, paste)
    store.set_plan(iid, "## 과제 표\n" + META_PROMPT)  # a decomposition quoting the empty template is fine
    store.set_plan(iid, "")
    assert store.get(iid)["plan"] == "" and "아직 붙여넣지 않음" in store.brief(iid)


def test_plan_api_rejects_result_blocks(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": "owner", "password": "correct horse"})
        iid = c.post("/api/ideas", json={"text": "아이디어"}).json()["id"]
        r = c.put(f"/api/ideas/{iid}/plan", json={"text": result(iid, "S1", "a", "b")})
        assert r.status_code == 422 and "결과 붙여넣기" in r.json()["detail"]
        assert c.put(f"/api/ideas/{iid}/plan", json={"text": ""}).status_code == 200
