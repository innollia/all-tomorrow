"""아이디어 정리본 = 짧은 종합본: 결과도 압축하고, 종합은 이전 종합본 + 새 압축본으로만, 원문은 따로 보관."""
from all_tomorrow.console import ideas_followup
from all_tomorrow.console.ideas import BRIEF_MAX, IdeaStore
from all_tomorrow.overseer import control_brief

from test_idea_followup import NOW, env  # noqa: F401  (pytest fixture)

LONG = "## 결론\n결과원문표식QQ 시장이 작다\n## 주장과 근거\n" + "- [C1] 긴 근거 문단이 이어진다. " * 400


def block(iid: str, sid: str, body: str) -> str:
    return f"=== 자료봉 결과 ===\n아이디어 ID: {iid}\n하위과제 ID: {sid}\n하위과제: 과제{sid}\n상태: 완료\n---\n{body}\n=== 끝 ==="


def ok(output: str) -> dict:
    return {"status": "SUCCESS", "result": {"payload": {"output": output}}}


def test_long_results_wait_for_compression_and_replaced_ones_are_skipped(tmp_path) -> None:
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("t", "본문")
    store.add_results(iid, block(iid, "S1", LONG) + block(iid, "S2", "## 결론\n짧은 답"))
    store.add_results(iid, block(iid, "S1", LONG + " 새판"))
    keys = [p["key"] for p in store.pending_summaries()]
    current = next(r for r in store.get(iid)["results"] if r["latest"] and r["subtask_id"] == "S1")
    assert keys == [f"R{current['id']}"]                     # 짧은 S2는 그 자체가 압축본, 덮어쓴 S1은 건너뜀
    item = store.item(keys[0])
    prompt = ideas_followup.compress_prompt(store.get(iid), item)
    assert "결과원문표식QQ" in prompt and "과제의 답" in prompt and "자료봉 하위 과제 결과" in prompt
    assert store.set_summary(keys[0], "## 과제의 답\nS1은 작은 시장 · 확신도 중간")
    assert store.pending_summaries() == []
    brief = store.brief(iid)
    assert "결과원문표식QQ" not in brief and "S1은 작은 시장" in brief and "짧은 답" in brief
    assert "결과원문표식QQ" in store.raw(iid)


def test_synthesis_is_incremental_then_rebuilt_without_originals(tmp_path) -> None:
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("t", "본문")
    store.add_results(iid, block(iid, "S1", "## 결론\n답일"))
    job = store.synth_job(iid)
    assert job["previous"] == "" and [i["key"] for i in job["new"]] == [f"R{store.get(iid)['results'][0]['id']}"]
    assert store.set_synthesis(iid, "## 한 줄 결론\n첫 종합", job["sigs"]) and store.synth_job(iid) is None
    assert store.pending_syntheses() == []

    mid = store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "메모", "body": "메모 압축본", "note": ""})
    job = store.synth_job(iid)
    assert job["previous"].startswith("## 한 줄 결론") and [i["key"] for i in job["new"]] == [f"M{mid}"]
    prompt = ideas_followup.synth_prompt(store.get(iid), job)
    assert "[이전 종합본]" in prompt and "첫 종합" in prompt and "메모 압축본" in prompt
    assert "답일" not in prompt                               # 이미 접힌 결과는 다시 넣지 않는다
    store.set_synthesis(iid, "## 한 줄 결론\n둘째 종합", job["sigs"])

    store.delete_material(iid, mid)                           # 접힌 것이 빠지면 압축본 전부로 다시 만든다
    job = store.synth_job(iid)
    assert job["previous"] == "" and len(job["new"]) == 1
    rid = store.get(iid)["results"][0]["id"]
    store.delete_result(iid, rid)
    assert store.synth_job(iid) is None and store.get(iid)["synth"] == ""


def test_brief_stays_small_and_context_reads_only_the_synthesis(tmp_path) -> None:
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("큰 아이디어", "본문 " * 2000)
    store.add_results(iid, "".join(block(iid, f"S{n}", LONG) for n in range(1, 8)))
    for p in store.pending_summaries():
        store.set_summary(p["key"], "요약 " * 900)              # 압축본 상한 근처
    for n in range(20):
        store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": f"자료{n}", "body": "가" * 5000, "note": ""})
        store.set_summary(n + 1, "자료요약 " * 400)
    brief = store.brief(iid)
    assert len(brief.encode("utf-8")) <= BRIEF_MAX and "결과원문표식QQ" not in brief and "M20" in brief.split("## 자료 목록")[1]
    store.set_synthesis(iid, "## 한 줄 결론\n작게 시작한다\n" + "주장 " * 3000, store.synth_job(iid)["sigs"])
    brief = (tmp_path / "ideas" / "briefs" / f"{iid}.md").read_text(encoding="utf-8")
    assert len(brief.encode("utf-8")) <= BRIEF_MAX and "여기서 줄임" in brief and len(store.get(iid)["synth"]) < 4600
    context = ideas_followup.build_context(store.get(iid))
    assert "작게 시작한다" in context and "자료요약" not in context and "결과원문표식QQ" not in context
    assert "결론: 작게 시작한다" in store.recent_summary() and control_brief.recent_ideas


def test_tick_compresses_results_then_synthesizes_and_retries_failed_synthesis(env) -> None:  # noqa: F811
    base, folder, ideas_dir, calls, results, tick = env
    store = IdeaStore(ideas_dir)
    iid = store.create("a", "b")
    store.add_results(iid, block(iid, "S1", LONG))
    assert tick(idle=None) == "compress" and "결과원문표식QQ" in calls[0][0]
    results["run1"] = ok("## 과제의 답\n작음")
    assert tick(idle=None, now=NOW + 10) == "finished"
    assert tick(idle=None, now=NOW + 20) == "synth"
    assert "결과원문표식QQ" not in calls[1][0] and "작음" in calls[1][0]
    results["run2"] = ok("")                                   # 빈 답 = 실패, 30분 뒤 다시
    assert tick(idle=None, now=NOW + 30) == "finished"
    assert tick(idle=None, now=NOW + 40) == "idle"
    assert tick(idle=None, now=NOW + 40 + 1900) == "synth"
    results["run3"] = ok("## 한 줄 결론\n작은 시장 [R1]")
    assert tick(idle=None, now=NOW + 2000) == "finished"
    assert store.get(iid)["synth"].startswith("## 한 줄 결론") and tick(idle=None, now=NOW + 2010) == "idle"


def test_prompts_filter_the_researchers_opinions_and_never_ask_for_ours(tmp_path) -> None:
    """조사 에이전트는 사실에 자기 평가·권고를 섞는다. 압축이 그걸 걸러 내고, 어느 지시문도 의견 칸을 두지 않는다."""
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("t", "본문")
    store.add_results(iid, block(iid, "S1", LONG))
    item = store.item(store.pending_summaries()[0]["key"])
    compress = ideas_followup.compress_prompt(store.get(iid), item)
    assert "검열" in compress and "## 뺀 의견" in compress
    synth = ideas_followup.synth_prompt(store.get(iid), {"previous": "", "new": [], "sigs": []})
    followup = ideas_followup.build_prompt(store.get(iid), "경쟁사 더", "codex")
    for prompt in (compress, synth, followup):
        assert "우리에게 주는 뜻" not in prompt and "다음에 조사할 것" not in prompt and "바뀌는 판단" not in prompt


def test_appended_text_and_decided_direction_rebuild_the_synthesis(tmp_path, monkeypatch) -> None:
    """원문에 덧붙인 생각과 사용자가 정한 방향이 종합에 들어가고, 바뀌면 종합을 처음부터 다시 만든다."""
    overseer = tmp_path / "overseer"
    overseer.mkdir()
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(overseer))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("게임 도구.", "처음 생각")
    store.add_results(iid, block(iid, "S1", "## 결론\n짧은 답"))
    job = store.synth_job(iid)
    assert store.set_synthesis(iid, "## 한 줄 결론\n첫 종합", job["sigs"]) and store.synth_job(iid) is None

    (store.base / "chat-analysis").mkdir()
    (store.base / "chat-analysis" / "room.md").write_text("# 방 분석\n신규 질문 2,012건", encoding="utf-8")
    (store.base / "chat-analysis" / "other.md").write_text("# 무관한 분석", encoding="utf-8")
    (overseer / "direction-notes.md").write_text(
        f"# 방향\n\n## 10/25 게임 도구\n\n- {iid}: 완성 프로그램, 유통은 오픈채팅방 (분석: chat-analysis/room.md)\n\n## 10/26 다른 일\n\n- 무관\n",
        encoding="utf-8")
    job = store.synth_job(iid)
    assert job and job["previous"] == ""                                  # 방향이 생기면 처음부터 다시
    prompt = ideas_followup.synth_prompt(store.get(iid), job)
    assert "완성 프로그램" in prompt and "신규 질문 2,012건" in prompt and "## 정해진 것" in prompt
    assert "무관" not in prompt and "무관한 분석" not in prompt
    assert store.set_synthesis(iid, "## 한 줄 결론\n둘째 종합", job["sigs"]) and store.synth_job(iid) is None
    assert "새 자료 반영 대기" not in store.brief(iid)

    assert store.append_text(iid, "학교에서 생각한 것: 신탁 버튼")
    idea = store.get(iid)
    assert idea["text"].endswith("신탁 버튼") and "신탁 버튼" in idea["prompt"]
    assert "신탁 버튼" in store.brief(iid).split("## 아이디어")[1].split("## 과제")[0]
    job = store.synth_job(iid)
    assert job and job["previous"] == "" and "신탁 버튼" in ideas_followup.synth_prompt(idea, job)
