from all_tomorrow.console import ideas_followup, ideas_rounds
from all_tomorrow.console.ideas import IdeaStore

SYNTH = """## 한 줄 결론
도구 A가 있다. [M1]
## 정해진 것
- 정해짐: 완성된 프로그램 하나로 판다. [방향]
- 정해짐: 착수는 11월 15일 이후. [방향]
## 주장
- 도구 A는 월 $10이다. [M1]
- 오픈채팅 600명 중 10%가 산다. (추정)
## 어긋나는 주장
- M1은 무료라 하고 M2는 유료라 한다. [M1, M2]
## 빈 곳
- 경쟁 제품의 한국어 지원 여부. [M1]
- 지불 의향.
"""


def test_round_asks_gaps_folds_results_and_keeps_decided(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path / "ov"))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("게임 도구", "AI 게임 도구 아이디어")
    try:
        ideas_rounds.open_round(store, iid)
        raise AssertionError("no synthesis yet")
    except ValueError:
        pass
    store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "첫 자료", "body": "도구 A 월 $10", "note": ""})
    store.set_synthesis(iid, SYNTH, store.synth_job(iid)["sigs"])

    r = ideas_rounds.open_round(store, iid)
    kinds = [(q["qid"], q["kind"]) for q in r["asked"]]
    assert r["n"] == 1 and kinds == [("Q1", "모름"), ("Q2", "모름"), ("Q3", "충돌"), ("Q4", "근거 약함")]
    assert "바퀴 1 · Q1 · 모름" in r["asked"][0]["prompt"] and "착수는 11월 15일 이후" in r["asked"][0]["prompt"]
    try:   # a round waits for its paste before the next opens
        ideas_rounds.open_round(store, iid)
        raise AssertionError("second round opened before paste")
    except ValueError:
        pass
    assert ideas_rounds.view(store, store.get(iid))[0]["state"] == "붙여넣기 대기"

    [mid] = ideas_rounds.add_results(store, iid, 1, ["바퀴 1 · Q1 · 모름\n## 한 줄 결론\n" + "한국어 지원 없음. " * 50])
    idea = store.get(iid)
    assert idea["materials"][0]["title"] == "바퀴 1 · Q1" and ideas_rounds.view(store, idea)[0]["state"] == "압축 중"
    store.set_summary(mid, "## 새로 더해진 것\n- 경쟁 제품 B는 한국어를 지원하지 않는다. [URL]\n## 이미 앎\n없음")
    job = store.synth_job(iid)
    assert job["previous"] == SYNTH.strip() and [i["key"] for i in job["new"]] == [f"M{mid}"]
    assert "'정해진 것' 줄은 지우거나 바꾸지 않는다" in ideas_followup.synth_prompt(store.get(iid), job)
    assert ideas_rounds.view(store, store.get(iid))[0]["state"] == "통합 중"

    # The new synthesis drops one decided line and fills a gap: the decided line comes back.
    second = SYNTH.replace("- 정해짐: 착수는 11월 15일 이후. [방향]\n", "").replace(
        "- 경쟁 제품의 한국어 지원 여부. [M1]\n", "").replace("도구 A가 있다. [M1]", "도구 A가 있고 B는 한국어가 없다. [M1, M3]")
    store.set_synthesis(iid, second, job["sigs"])
    synth = store.get(iid)["synth"]
    assert "착수는 11월 15일 이후" in synth.split("## 주장")[0]
    [rnd] = ideas_rounds.view(store, store.get(iid))
    assert rnd["state"] == "통합됨" and rnd["new"] == 1 and rnd["low"]
    changed = {c["section"]: c for c in rnd["changed"]}
    assert "한 줄 결론" in changed and changed["빈 곳"]["gone"] == ["경쟁 제품의 한국어 지원 여부. [M1]"]
    assert "정해진 것" not in changed

    assert ideas_rounds.open_round(store, iid)["n"] == 2   # no cap on rounds
    store.delete_idea(iid)
    with store.db() as db:
        assert not db.execute("SELECT 1 FROM rounds").fetchone()


def test_direction_notes_match_title_ignoring_case_and_spaces(tmp_path, monkeypatch) -> None:
    ov = tmp_path / "ov"
    ov.mkdir()
    (ov / "direction-notes.md").write_text("## 2026-10-25 AI 게임개발 프로그램\n- 모듈이 아니라 완성된 프로그램\n\n## 다른 것\n- 무관\n", encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(ov))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("ai게임개발 프로그램.", "본문")
    decided = store.grounds(store.get(iid))["decided"]
    assert "완성된 프로그램" in decided and "무관" not in decided
