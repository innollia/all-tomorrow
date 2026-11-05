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


ROBLOX = """## 정해진 것
- 정해짐: 로블록스로 만든다. [원문]
## 주장
- AI NPC 원가는 하루 $0.03이다. [R30] (추정)
## 어긋나는 주장
- 원문의 "AI여친"은 Roblox 일반 콘텐츠 금지와 부딪친다. [원문, R32]
## 빈 곳
- S1·S2는 불완전 상태다. 실제 Studio 실행·빌드·성능 측정 결과가 없다. [R31]
- 개발자 나이·국적·사업자 형태, 대상 국가·연령이 미확정이다. [R32]
- 한국어권 반야생 게임의 수요·이용자 수가 없다. [R33]
"""


def test_round_asks_only_the_web_what_the_web_can_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path / "ov"))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("로블록스", "로블록스 AI NPC 생존 게임")
    store.add_material(iid, {"kind": "paste", "label": "붙여넣기", "url": "", "title": "첫 자료", "body": "자료", "note": ""})
    store.set_synthesis(iid, ROBLOX, store.synth_job(iid)["sigs"])

    r = ideas_rounds.open_round(store, iid)
    got = [(q["qid"], q["kind"], q["to"], "prompt" in q) for q in r["asked"]]
    assert got == [("Q1", "모름", "local", False), ("Q2", "모름", "user", False), ("Q3", "모름", "web", True),
                   ("Q4", "충돌", "web", True), ("Q5", "근거 약함", "web", True)]
    assert not any("나이" in q.get("prompt", "").split("[정해진 것]")[0] for q in r["asked"])
    ideas_rounds.add_results(store, iid, 1, ["바퀴 1 · Q3 · 모름\n## 한 줄 결론\n한국 이용자 수 공개됨"])
    assert "물음: 한국어권 반야생" in store.get(iid)["materials"][0]["note"]   # the compression knows what was asked

    # The user's answer to what was put to them becomes something decided for the next synthesis.
    sig = store.grounds(store.get(iid))["sig"]
    ideas_rounds.set_answer(store, iid, 1, "Q2", "한국 개인, 대상은 13세 이상 한국")
    try:
        ideas_rounds.set_answer(store, iid, 1, "Q3", "웹 질문에는 답 칸이 없다")
        raise AssertionError("answered a web question")
    except LookupError:
        pass
    assert ideas_rounds.view(store, store.get(iid))[0]["asked"][1]["answer"] == "한국 개인, 대상은 13세 이상 한국"
    g = store.grounds(store.get(iid))
    assert g["sig"] != sig and "13세 이상" in g["answers"]
    store.set_summary(store.get(iid)["materials"][0]["id"], "## 새로 더해진 것\n- 일본 이용자 많다")
    job = store.synth_job(iid)
    assert job["previous"] == ""   # a new answer rebuilds like a changed direction
    assert "바퀴 물음에 직접 답한 것" in ideas_followup.synth_prompt(store.get(iid), job)

    # Answered: the same item is not put to the user again.
    store.set_synthesis(iid, ROBLOX, job["sigs"])
    second = ideas_rounds.open_round(store, iid)["asked"]
    assert not any("나이" in q["topic"] for q in second)
    store.delete_idea(iid)
    with store.db() as db:
        assert not db.execute("SELECT 1 FROM round_answers").fetchone()


def test_route_uses_jev_but_never_sends_the_founder_to_the_web(tmp_path, monkeypatch) -> None:
    store = IdeaStore(tmp_path / "ideas", use_jev=True)
    found = [{"kind": "모름", "topic": "개발자 국적이 없다"}, {"kind": "충돌", "topic": "R11 집계 10/12와 목록 11개가 다르다"},
             {"kind": "모름", "topic": "경쟁작 가격"}, {"kind": "모름", "topic": "애매한 것"}]
    answers = {"g0": {"probabilities": {"웹 조사": 0.9, "사용자에게 묻기": 0.05, "직접 확인": 0.05}},
               "g1": {"probabilities": {"웹 조사": 0.2, "사용자에게 묻기": 0.1, "직접 확인": 0.7}},
               "g2": {"probabilities": {"웹 조사": 0.8, "사용자에게 묻기": 0.1, "직접 확인": 0.1}},
               "g3": {"probabilities": {"웹 조사": 0.3, "사용자에게 묻기": 0.4, "직접 확인": 0.3}}}
    monkeypatch.setattr(ideas_rounds.jev, "ask", lambda state, questions: answers)
    assert ideas_rounds.route(store, {"title": "t", "text": "x"}, found) == ["user", "local", "web", "web"]

    def down(state, questions):
        raise ideas_rounds.jev.JevError("down")
    monkeypatch.setattr(ideas_rounds.jev, "ask", down)
    assert ideas_rounds.route(store, {"title": "t", "text": "x"}, found) == ["user", "web", "web", "web"]


SPLIT_ANSWER = """1. 질문 풀기: 갈래 둘.
| ID | 제목 | 분류 |
| S3 | 복제 게임 수익 | 독립 |
| S4 | 최신 유행 | 독립 |

### S3 · 복제 게임 수익 · 독립
```
idea_brief ...
=== 자료봉 결과 ===
상태: 완료 | 불완전 | 실패
=== 끝 ===
```

### S4 · 최신 유행 · 독립
```
idea_brief ...
```
"""


def block(iid, sid, title, body):
    return f"=== 자료봉 결과 ===\n아이디어 ID: {iid}\n하위과제 ID: {sid}\n하위과제: {title}\n상태: 완료\n---\n## 결론\n{body}\n=== 끝 ==="


def test_extra_research_splits_into_tasks_and_every_question_reaches_the_synthesis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path / "ov"))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("로블록스", "로블록스 AI NPC 생존 게임")
    store.set_plan(iid, "### S1 · 시장 · 독립\n설명\n### S2 · 기술 · 독립\n설명")
    store.add_results(iid, block(iid, "S1", "시장", "시장 큼"))
    store.add_results(iid, block(iid, "S2", "기술", "됨"))
    for r in store.get(iid)["results"]:
        store.set_summary(f"R{r['id']}", "## 새로 더해진 것\n- 사실")
    store.set_synthesis(iid, ROBLOX, store.synth_job(iid)["sigs"])

    ideas_rounds.set_asks(store, iid, "마크 복제 맵 수익화 되나\n- 최신 유행은\n\n")
    try:
        ideas_rounds.open_extra(store, iid, "  \n")
        raise AssertionError("nothing to split")
    except ValueError:
        pass
    x = ideas_rounds.open_extra(store, iid, "마크 복제 맵 수익화 되나\n- 최신 유행은\n\n")
    assert x["n"] == 1 and x["start"] == 3 and x["questions"] == ["마크 복제 맵 수익화 되나", "최신 유행은"]
    assert "S3부터" in x["prompt"] and f"`{iid}`" in x["prompt"] and "- 마크 복제 맵 수익화 되나" in x["prompt"]
    assert "=== 자료봉 결과 ===" in x["prompt"] and "completion_rule" in x["prompt"] and "정해짐: 로블록스로 만든다" in x["prompt"]
    assert store.get(iid)["asks"] == "" and ideas_rounds.extras(store, store.get(iid))[0]["state"] == "쪼개기 답 대기"

    # Another question before the answer came joins the same split, same numbers.
    x = ideas_rounds.open_extra(store, iid, "일본도")
    assert x["n"] == 1 and x["start"] == 3 and len(x["questions"]) == 3

    # One box takes both kinds of answer. The decomposition quotes the empty result template and is still a decomposition.
    assert store.add_extra(iid, SPLIT_ANSWER) == {"tasks": ["S3", "S4"], "results": []}
    assert store.add_extra(iid, SPLIT_ANSWER)["tasks"] == ["S3", "S4"]    # pasted twice: no harm
    idea = store.get(iid)
    assert set(idea["tasks"]) == {"S1", "S2", "S3", "S4"} and idea["plan"].count("### S3") == 1
    [e] = ideas_rounds.extras(store, idea)
    assert e["state"] == "결과 대기" and [t["id"] for t in e["tasks"]] == ["S3", "S4"]
    try:   # 자료봉 renumbered from S1: refused rather than overwriting the old tasks
        store.add_extra(iid, "### S1 · 다른 것 · 독립\n설명")
        raise AssertionError("task number reused")
    except ValueError as error:
        assert "S1" in str(error)

    assert store.add_extra(iid, block(iid, "S3", "복제 게임 수익", "수익 있음. " * 80) + "\n" + block(iid, "S4", "최신 유행", "시뮬레이터. " * 80))["results"] == ["S3", "S4"]
    idea = store.get(iid)
    assert ideas_rounds.extras(store, idea)[0]["state"] == "압축 중"
    for r in idea["results"][:2]:
        store.set_summary(f"R{r['id']}", "## 새로 더해진 것\n- " + r["subtask_title"])
    job = store.synth_job(iid)
    assert job["previous"] and len(job["new"]) == 2 and "과제 S3 복제 게임 수익" in job["new"][-1]["label"] + job["new"][0]["label"]
    prompt = ideas_followup.synth_prompt(store.get(iid), job)
    assert "S4 최신 유행" in prompt and "- 마크 복제 맵 수익화 되나 [과제 S3부터]" in prompt and "물음마다 답한다" in prompt
    assert ideas_rounds.extras(store, store.get(iid))[0]["state"] == "통합 중"
    store.set_synthesis(iid, ROBLOX + "- 추가\n", job["sigs"])
    assert ideas_rounds.extras(store, store.get(iid))[0]["state"] == "통합됨"
    assert ideas_rounds.open_extra(store, iid, "또 하나")["start"] == 5

    store.delete_idea(iid)
    with store.db() as db:
        assert not db.execute("SELECT 1 FROM extras").fetchone()


def test_every_past_question_is_listed_for_the_synthesis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path / "ov"))
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("로블록스", "본문")
    # A question that went through an old round and one that Codex researched.
    with store.db() as db:
        db.execute("INSERT INTO rounds (idea_id, n, topics, synth_before, created_at) VALUES (?,1,?,'','2026-11-04')",
                   (iid, '[{"qid": "Q26", "kind": "내 질문", "topic": "마크 복제 맵은 뭐하는 놈들", "to": "web"}, {"qid": "Q1", "kind": "모름", "topic": "빈 곳", "to": "web"}]'))
    m = ideas_rounds.add_results(store, iid, 1, ["바퀴 1 · Q26 · 내 질문\n" + "답. " * 200])[0]
    c = store.add_material(iid, ideas_followup.material_item("경쟁사 가격 더", "x" * 400, "run1"))
    assert store.get(iid)["asked"] == [f"- 마크 복제 맵은 뭐하는 놈들 [M{m}]", f"- 경쟁사 가격 더 [M{c}]"]
    context = ideas_followup.build_context(store.get(iid))
    assert "사용자가 더 물은 것" in context and "경쟁사 가격 더" in context
    assert "물음: 마크 복제 맵" in store.item(m)["note"]
    assert "물음: 마크 복제 맵" in ideas_followup.compress_prompt(store.get(iid), store.item(m))
