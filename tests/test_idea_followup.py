"""아이디어 추가 조사(대충 쓴 요청 → 맥락 붙인 조사), 자료 원문 보관·압축본만 읽기, 입력 제한 없음."""
import base64

import pytest
from fastapi.testclient import TestClient

from all_tomorrow import mcp_server
from all_tomorrow.console import ideas_followup
from all_tomorrow.console.ideas import IdeaStore
from all_tomorrow.console.research import load_runs
from all_tomorrow.overseer import control_brief
from all_tomorrow.overseer import idle_research as ir
from all_tomorrow.web import Auth, create_app

NOW = 1_800_000_000.0
RAW = "원문표식ZZ " + "경쟁사 가격은 월 9달러에서 시작한다. " * 300     # 긴 자료(수천 자)


def login(tmp_path) -> TestClient:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    client = TestClient(app, base_url="https://testserver")
    client.__enter__()
    client.post("/api/login", json={"username": "owner", "password": "correct horse"})
    return client


def make_idea(c) -> str:
    return c.post("/api/ideas", json={"title": "도서 구독 앱", "text": "책을 월 구독으로 빌려 주는 앱 아이디어"}).json()["id"]


def test_prompt_has_context_but_only_summaries(tmp_path) -> None:
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("도서 구독 앱", "책을 월 구독으로 빌려 주는 앱")
    store.set_plan(iid, "### S1 · 시장 규모 · 시장\n설명\n### S2 · 경쟁사 가격 · 경쟁\n설명")
    store.add_slots(iid, ["=== 자료봉 결과 ===\n아이디어 ID: " + iid + "\n하위과제 ID: S1\n상태: 완료\n---\n## 결론\n시장은 연 3조원이다\n=== 끝 ==="])
    mid = store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "내 조사", "body": RAW, "note": ""})
    prompt = ideas_followup.build_prompt(store.get(iid), "경쟁사 가격 더", "paste")
    assert "경쟁사 가격 더" in prompt and "해석한 조사 질문" in prompt and "책을 월 구독으로" in prompt
    assert "시장은 연 3조원" in prompt                       # 이미 답이 나온 것
    assert "S2 경쟁사 가격: 아직 결과 없음" in prompt          # 빈 곳
    assert "(압축 대기)" in prompt and "원문표식ZZ" not in prompt
    store.set_summary(mid, "## 새로 더해진 것\n- 월 9달러")
    prompt = ideas_followup.build_prompt(store.get(iid), "x", "codex")
    assert "월 9달러" in prompt and "원문표식ZZ" not in prompt and "읽기와 웹 검색만" in prompt
    with pytest.raises(ValueError):
        ideas_followup.build_prompt(store.get(iid), "  ", "codex")


def test_followup_api_and_history(tmp_path) -> None:
    c = login(tmp_path)
    iid = make_idea(c)
    p = c.post(f"/api/ideas/{iid}/followup/prompt", json={"request": "일본에서도 되나"}).json()["prompt"]
    assert "일본에서도 되나" in p and "도서 구독 앱" in p
    assert c.get(f"/api/ideas/{iid}").json()["followups"] == []     # 복사는 아무것도 저장하지 않는다
    t = c.post(f"/api/ideas/{iid}/followups", json={"request": "일본에서도 되나"}).json()
    assert t["idea_id"] == iid and t["run_now_at"] and t["repeat_days"] == 0 and t["ask"] == "일본에서도 되나"
    got = c.get(f"/api/ideas/{iid}").json()["followups"]
    assert [x["id"] for x in got] == [t["id"]] and got[0]["runs"] == []
    assert c.post("/api/ideas/I-000000-0000/followups", json={"request": "x"}).status_code == 404
    assert c.post(f"/api/ideas/{iid}/followups", json={"request": ""}).status_code == 422
    assert c.get("/api/research").json()[0]["idea_id"] == iid


@pytest.fixture()
def env(tmp_path, monkeypatch):
    base, folder = tmp_path / "base", tmp_path / "research"
    base.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(mcp_server, "load_projects", lambda: {"all-tomorrow": {"path": proj.as_posix()}})
    (base / "subscription-usage.json").write_text(
        '{"providers":[{"id":"codex","status":"connected","windows":[{"label":"5h","percent":10,"resets_at":null}]}]}', encoding="utf-8")
    calls, results = [], {}

    def start(project_id, worker, task, **kw):
        calls.append((task, kw))
        return {"run_id": f"run{len(calls)}"}

    def tick(idle=3600.0, now=NOW):
        return ir.tick(base, idle, now=now, start=start, read=lambda r: results.get(r, {"status": "RUNNING"}), folder=folder)

    return base, folder, tmp_path / "ideas", calls, results, tick


def test_followup_runs_in_codex_then_material_is_compressed(env) -> None:
    from all_tomorrow.console.research import ResearchStore
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("도서 구독 앱", "책을 월 구독으로 빌려 주는 앱")
    ResearchStore(folder).create_followup(iid, "경쟁사 가격 더")
    assert tick(idle=None) == "started"                                  # 지금 돌리기처럼 PC 사용 중이어도
    task, kw = calls[0]
    assert "경쟁사 가격 더" in task and "책을 월 구독으로" in task and "해석한 조사 질문" in task
    assert kw["argv_suffix"][:2] == ["-c", 'web_search="live"'] and "sandbox" not in kw["worker_options"]
    assert "mcp_servers.chrome_pages.command=" in " ".join(kw["argv_suffix"]) and "read_logged_in_page" in task
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 해석한 조사 질문\n" + RAW}}}
    assert tick(idle=None) == "finished"
    run = load_runs(folder)[0]
    assert run["idea_id"] == iid and run["material_id"] and run["request"] == "경쟁사 가격 더"
    m = store.get(iid)["materials"][0]
    assert m["label"] == "Codex 추가 조사" and "경쟁사 가격 더" in m["note"] and "원문표식ZZ" in m["body"] and m["summary"] == ""
    # 정리본·관제 요약에는 원문이 없고 '압축 대기'만 있다
    brief = store.brief(iid)
    assert "원문표식ZZ" not in brief and "압축 대기" in brief and "Codex 추가 조사" in brief
    assert "압축 대기 1건" in store.recent_summary()
    # 압축: PC 사용 중이어도, 웹 검색 없이, 원문을 보고 바로 시작
    assert tick(idle=None, now=NOW + 60) == "compress"
    ctask, ckw = calls[1]
    assert "원문표식ZZ" in ctask and "웹 검색을 하지 않는다" in ctask and 'web_search="live"' not in ckw.get("argv_suffix", [])
    assert "sandbox" not in ckw["worker_options"]
    assert tick(idle=None, now=NOW + 70) == "running"
    results["run2"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 새로 더해진 것\n- 월 9달러부터\n## 이미 앎\n없음"}}}
    assert tick(idle=None, now=NOW + 80) == "finished"
    assert store.get(iid)["materials"][0]["summary"].startswith("## 새로 더해진 것")
    brief = store.brief(iid)
    assert "월 9달러부터" in brief and "원문표식ZZ" not in brief and "압축 대기" not in brief
    assert "압축 대기" not in store.recent_summary() and "원문표식ZZ" not in store.recent_summary()
    # 압축이 끝나면 종합: 압축본만 넣는다
    assert tick(idle=None, now=NOW + 90) == "synth"
    stask, skw = calls[2]
    assert "월 9달러부터" in stask and "원문표식ZZ" not in stask and "sandbox" not in skw["worker_options"]
    results["run3"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 한 줄 결론\n가격 9달러대가 기준이다 [M1]"}}}
    assert tick(idle=None, now=NOW + 100) == "finished"
    assert "가격 9달러대가 기준이다" in store.brief(iid) and "결론: 가격 9달러대" in store.recent_summary()
    assert tick(idle=None, now=NOW + 110) == "idle"                     # 더 할 일 없음


def test_compress_failure_retries_then_gives_up(env) -> None:
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("a", "b")
    store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "t", "body": RAW, "note": ""})
    t = NOW
    for n in range(ir.COMPRESS_TRIES):
        assert tick(idle=None, now=t) == "compress"
        results[f"run{n + 1}"] = {"status": "SUCCESS", "result": {"payload": {"output": None}}}
        assert tick(idle=None, now=t + 5) == "finished"
        assert tick(idle=None, now=t + 60) == "idle"                    # 30분 안에는 다시 하지 않는다
        t += ir.COMPRESS_RETRY + 100
    assert tick(idle=None, now=t) == "idle" and len(calls) == ir.COMPRESS_TRIES
    assert "원문표식ZZ" not in store.brief(iid)


def test_short_material_is_its_own_summary_and_brief_never_has_long_original(tmp_path) -> None:
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("a", "b")
    store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "짧은 메모", "body": "한 줄 메모", "note": ""})
    assert store.pending_summaries() == [] and "한 줄 메모" in store.brief(iid)
    store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "긴", "body": RAW, "note": ""})
    assert [p["title"] for p in store.pending_summaries()] == ["긴"]
    control = control_brief.recent_ideas.__module__   # 관제 요약도 같은 recent_summary를 쓴다
    assert control and "원문표식ZZ" not in store.recent_summary()


def test_intake_accepts_huge_and_odd_input_without_refusal(tmp_path) -> None:
    c = login(tmp_path)
    iid = make_idea(c)
    big = "# 대화 1\n| 표 | 값 |\n|---|---|\n| a | 1 |\nhttps://example.com/x 링크 섞음\n" + "가" * 1_300_000
    r = c.post("/api/ideas/intake", json={"text": big, "idea_id": iid})
    assert r.status_code == 200 and r.json()["added"][0]["idea_id"] == iid
    assert len(c.get(f"/api/ideas/{iid}").json()["materials"][0]["body"]) > 1_000_000
    zipish = base64.b64encode(b"\x00\x01\x02binary\xff\xfe").decode()
    r = c.post("/api/ideas/intake", json={"files": [{"name": "a.zip", "data": zipish}], "idea_id": iid})
    assert r.status_code == 200 and r.json()["added"][0]["kind"] == "file"
    r = c.post("/api/ideas/intake", json={"text": "   ", "idea_id": iid})
    assert r.status_code == 200 and r.json()["added"] == []
    # 다른 아이디어 ID가 적힌 결과 블록이나, 쪼개기 칸에 붙인 결과 블록도 거절하지 않는다
    block = "=== 자료봉 결과 ===\n아이디어 ID: I-000101-aaaa\n하위과제 ID: S1\n상태: 완료\n---\n## 결론\n끝\n=== 끝 ==="
    assert c.post(f"/api/ideas/{iid}/results", json={"text": block}).status_code == 200
    assert c.put(f"/api/ideas/{iid}/plan", json={"text": block}).status_code == 200


def test_move_material_between_ideas_and_drops_emptied_candidate(tmp_path) -> None:
    c = login(tmp_path)
    keep = make_idea(c)
    r = c.post("/api/ideas/intake", json={"text": "완전히 다른 주제의 메모"}).json()["added"][0]
    assert r["candidate"] is True and r["placed_by"] == "new"
    cand = r["idea_id"]
    assert c.put(f"/api/ideas/{cand}/materials/{r['material_id']}/move", json={"idea_id": keep}).status_code == 200
    assert c.get(f"/api/ideas/{cand}").status_code == 404                # 비어 버린 후보는 사라진다
    assert [m["title"] for m in c.get(f"/api/ideas/{keep}").json()["materials"]] == [r["title"]]
    assert c.put(f"/api/ideas/{keep}/materials/{r['material_id']}/move", json={"idea_id": "I-1-x"}).status_code == 404


def test_console_shell_scripts_carry_a_version(tmp_path) -> None:
    html = login(tmp_path).get("/").text
    assert "/static/console/pages/ideas.js?v=" in html and "__V__" not in html


def test_followup_files_pages_read_in_chrome_as_raw_materials(env) -> None:
    from all_tomorrow.adapters import chrome_pages
    from all_tomorrow.console.research import ResearchStore
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("게임 툴", "게임 개발 도구")
    ResearchStore(folder).create_followup(iid, "https://chatgpt.com/g/g-p-x/project 대화 전부 가져와")
    assert tick(idle=None) == "started"
    run_id = load_runs(folder)[0]["id"]
    assert f"AT_PAGES_DIR = " in " ".join(calls[0][1]["argv_suffix"]) and run_id in " ".join(calls[0][1]["argv_suffix"])
    pages = folder / "pages" / run_id                                   # Codex가 도구로 읽은 페이지(MCP 쪽이 남김)
    chrome_pages.archive(pages, {"url": "https://chatgpt.com/g/g-p-x/project", "title": "프로젝트", "text": "대화 목록"})
    chrome_pages.archive(pages, {"url": "https://chatgpt.com/g/g-p-x/c/1", "title": "가격 조사", "text": "대화원문표식" * 300})
    chrome_pages.archive(pages, {"url": "https://chatgpt.com/g/g-p-x/c/1", "title": "가격 조사", "text": "대화원문표식" * 300})
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 한 줄 결론\n대화 2건 정리"}}}
    assert tick(idle=None) == "finished"
    mats = store.get(iid)["materials"]
    assert load_runs(folder)[0]["pages_filed"] == 2 and len(mats) == 3        # 보고서 + 페이지 2건(같은 주소는 한 번)
    page = next(m for m in mats if m["url"].endswith("/c/1"))
    assert page["title"] == "가격 조사" and page["body"].startswith("대화원문표식") and page["summary"] == ""   # 긴 원문은 압축 대기
    assert "대화원문표식" not in store.brief(iid)


def test_failed_collection_report_is_not_filed_as_material(env) -> None:
    from all_tomorrow.console.research import ResearchStore
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("게임 툴", "게임 개발 도구")
    ResearchStore(folder).create_followup(iid, "https://chatgpt.com/g/g-p-x/project 전부 가져와")
    assert tick(idle=None) == "started" and "[수집 실패]" in calls[0][0]
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": "[수집 실패]\n## 한 줄 결론\n접근 못 함"}}}
    assert tick(idle=None) == "finished"
    run = load_runs(folder)[0]
    assert run["status"] == "SUCCESS" and run["material_skipped"] == "collection_failed" and "material_id" not in run
    assert store.get(iid)["materials"] == []


def test_compress_now_jumps_the_queue_even_while_research_runs(env) -> None:
    """'지금 압축'을 누른 자료는 오래된 것보다 먼저, 긴 조사가 도는 중에도 바로 압축한다."""
    from all_tomorrow.console.research import ResearchStore
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("a", "b")
    ResearchStore(folder).create_followup(iid, "경쟁사 더")
    assert tick(idle=None) == "started"                                  # 긴 조사가 돈다
    old = store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "옛 자료", "body": "옛것 " + RAW, "note": ""})
    new = store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "새 자료", "body": "새것표식 " + RAW, "note": ""})
    assert tick(idle=None, now=NOW + 10) == "running"                    # 누르기 전에는 조사가 끝나기를 기다린다
    keys = [p["key"] for p in store.pending_summaries()]
    assert store.rush(keys[-1]) and not store.rush("M999")
    assert tick(idle=None, now=NOW + 20) == "compress" and "새것표식" in calls[-1][0]
    assert tick(idle=None, now=NOW + 30) == "running"                    # 압축 하나가 돌면 더 끼우지 않는다
    results["run2"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 새로 더해진 것\n- 새것"}}}
    assert tick(idle=None, now=NOW + 40) == "finished"
    assert store.item(keys[-1]) and [p["key"] for p in store.pending_summaries()] == keys[:-1]
    assert tick(idle=None, now=NOW + 50) == "running"                    # 누르지 않은 옛 자료는 조사 뒤 차례
    assert old and new


def test_compress_now_api_shows_requested_then_running(tmp_path) -> None:
    c = login(tmp_path)
    iid = make_idea(c)
    c.post("/api/ideas/intake", json={"text": "원문표식ZZ " + RAW, "idea_id": iid})
    m = c.get(f"/api/ideas/{iid}").json()["materials"][0]
    assert c.get(f"/api/ideas/{iid}").json()["compressing"] == {}
    assert c.post(f"/api/ideas/{iid}/compress/M{m['id']}", json={}).json() == {"queued": f"M{m['id']}"}
    assert c.get(f"/api/ideas/{iid}").json()["compressing"] == {f"M{m['id']}": "queued"}
    assert c.post(f"/api/ideas/{iid}/compress/M99999", json={}).status_code == 404
    assert c.post(f"/api/ideas/{iid}/compress/x", json={}).status_code == 404
