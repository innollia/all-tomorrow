import importlib
import subprocess
import sys
import time

import pytest

from all_tomorrow.idea_factory import evaluation
from all_tomorrow.idea_factory.config import REPO_ROOT, gateway_config, load_roster
from all_tomorrow.idea_factory.patents import PatentHit, UncheckedSource
from all_tomorrow.idea_factory.store import Store


@pytest.fixture(autouse=True)
def no_real_secrets(tmp_path, monkeypatch):
    # launch() exports secrets from the key pool; never read the developer's real one in tests.
    monkeypatch.setenv("IDEA_FACTORY_KEY_POOL", str(tmp_path / "no-key-pool.env"))
    monkeypatch.delenv("KIPRIS_API_KEY", raising=False)
    monkeypatch.delenv("IDEA_FACTORY_PATENTS", raising=False)


@pytest.fixture()
def pipeline():
    """The factory pipeline bound to the live DBOS registry.

    Its steps and workflow are registered at import time. A suite that tears down with
    DBOS.destroy(destroy_registry=True) (tests/test_dbos_runtime_probe.py) drops that process-wide
    registry, and steps imported before it then run against a dead instance. Re-importing binds a
    fresh copy (same module, so DBOS only warns about the re-registration)."""
    sys.modules.pop("all_tomorrow.idea_factory.pipeline", None)
    module = importlib.import_module("all_tomorrow.idea_factory.pipeline")
    yield module
    module.shutdown()


class FakePatents:
    name = "fake"

    def search(self, query, limit=8):
        return [PatentHit("KR1", "주사위 굴림 동기화 장치", "dice sync", "fake", "https://example.test/KR1")]


SENT_PROMPTS: list[str] = []


def fake_chat_json(group, system, user, **kwargs):
    SENT_PROMPTS.append(system + " " + user)
    if "아이디어 담당" in system:
        return {"ideas": [{"title": "주사위 동기화", "problem": "p", "approach": "a"},
                          {"title": "세션 요약 봇", "problem": "p", "approach": "a"}]}, "fake"
    if "검색어" in user:
        return {"queries": ["q1"]}, "fake"
    if "겹치는 특허가 하나라도" in system:
        overlaps = [{"number": "KR1", "element": "주사위 동기화"}] if user.startswith("아이디어: 주사위") else []
        return {"overlaps": overlaps, "reason": "r"}, "fake"
    if "회의" in system and "기획안" not in system:
        # worst case: the model echoes every private fact it was given into its reason
        echoed = [m for m in ("GOALMARK", "CAPACITYMARK", "BUDGETMARK", "INTERESTMARK") if m in user.split("[의뢰인 정보")[-1]]
        vote = {"stance": "support", "reason": "좋다 " + " ".join(echoed) if "[의뢰인 정보" in user else "좋다"}
        if "reason_public" in user:
            # the operator writes a clean summary; the skeptic's "summary" still leaks a fact
            vote["reason_public"] = ("의뢰인 사정상 자금 여유가 없다" if "오퍼레이터." in system
                                     else "의뢰인 사정상 어렵다 " + " ".join(echoed))
        return vote, "fake"
    return {"title": "세션 요약 봇", "problem": "p", "approach": "a", "dod": ["d"], "risks": ["r"],
            "market": "m", "effort": "S", "first_step": "f"}, "fake"


def wait_until_done(store, topic_id, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and store.topic(topic_id)["status"] == "RUNNING":
        time.sleep(0.1)
    return store.topic(topic_id)["status"]


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "f.sqlite")
    for m in load_roster().staff:
        s.hire(m["role"], m["name"], m["model_group"], access_level=m.get("access_level", 0), access_scopes=m.get("access_scopes", []))
    return s


def test_gateway_config_references_key_names_only() -> None:
    roster = load_roster()
    config = gateway_config(roster, ["OPENROUTER__A", "GROQ__B", "HUGGINGFACE__C", "OTHER__D"])
    keys = {d["litellm_params"]["api_key"] for d in config["model_list"]}
    assert keys == {"os.environ/OPENROUTER__A", "os.environ/GROQ__B", "os.environ/HUGGINGFACE__C"}
    assert all(d["litellm_params"]["model"].endswith(":free") for d in config["model_list"]
               if d["litellm_params"]["model"].startswith("openrouter/"))


def test_paid_openrouter_model_is_rejected(tmp_path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text((REPO_ROOT / "config" / "idea-factory.yaml").read_text(encoding="utf-8").replace(
        "nvidia/nemotron-3-ultra-550b-a55b:free", "openai/gpt-5"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_roster(path)


def test_key_pool_defaults_outside_the_repo(monkeypatch) -> None:
    from all_tomorrow.idea_factory.config import key_pool_path

    monkeypatch.delenv("IDEA_FACTORY_KEY_POOL")
    assert REPO_ROOT not in key_pool_path().resolve().parents


FAKE_PROFILE = {
    "진행 중인 목표·프로젝트": {"level": 1, "scope": "goals", "text": "- 목표/프로젝트=GOALMARK"},
    "일정 부하": {"level": 1, "scope": "capacity", "text": "- CAPACITYMARK"},
    "고정 지출·구독·수입": {"level": 2, "scope": "budget", "text": "- BUDGETMARK"},
    "취향·선호": {"level": 3, "scope": "interests", "text": "- INTERESTMARK"},
}


def test_workflow_kills_patented_idea_and_reports_the_other(tmp_path, monkeypatch, pipeline) -> None:
    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(pipeline.profile, "fetch_profile", lambda sources: FAKE_PROFILE)
    monkeypatch.setenv("NOTION_TOKEN", "test")
    SENT_PROMPTS.clear()
    s = Store(tmp_path / "f.sqlite")
    pipeline.launch(s, f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}", patents=FakePatents())
    try:
        topic_id = pipeline.start_topic("TRPG 유틸리티", actor="test")
        assert wait_until_done(s, topic_id) == "DONE"
        statuses = {i["title"]: i["status"] for i in s.ideas(topic_id=topic_id)}
        assert statuses == {"주사위 동기화": "KILLED", "세션 요약 봇": "PROPOSED"}
        killed = s.ideas(status="KILLED")[0]
        assert killed["evidence"][0]["number"] == "KR1"
        assert len(s.votes(f"{topic_id}-i2")) == 8
        assert s.proposals("PENDING")[0]["body"]["patent_check"].startswith("관련 특허 없음")
        # each member gets only the profile sources its level and scopes allow
        by_role = lambda word: [p for p in SENT_PROMPTS if word in p.split(" ", 1)[0] or word in p[:200]]
        advocate = by_role("애드보킷.")
        operator = [p for p in by_role("오퍼레이터.") if "회의" in p[:60]]
        ideator = by_role("아이디어 담당")
        assert advocate and not any("[의뢰인 정보" in p for p in advocate)
        # members echo private facts into reasons; the transcript must not carry them to lower access
        marks = ("GOALMARK", "CAPACITYMARK", "BUDGETMARK", "INTERESTMARK")
        assert not any(m in p for p in advocate for m in marks)
        visionary = by_role("비저너리.")
        assert visionary and not any(m in p for p in visionary for m in ("CAPACITYMARK", "BUDGETMARK"))
        assert any("(권한 밖 근거 생략)" in p for p in advocate)  # the skeptic's leaky summary is dropped
        assert any("(요약) 의뢰인 사정상 자금 여유가 없다" in p for p in advocate)  # the operator's clean one passes
        # the operator may read the skeptic's reasons: the skeptic saw nothing the operator can't
        assert any("[1라운드 스켑틱] support: 좋다 " in p and "CAPACITYMARK" in p.split("[1라운드 스켑틱]")[1][:80]
                   for p in by_role("오퍼레이터.") if "2라운드 발언" in p)
        assert operator and all("BUDGETMARK" in p and "CAPACITYMARK" in p and "INTERESTMARK" not in p for p in operator)
        assert ideator and all("INTERESTMARK" in p and "BUDGETMARK" not in p for p in ideator)
        assert not any("[의뢰인 정보" in p for p in SENT_PROMPTS if "특허 조사관" in p)
        grants = [a for a in s.audit_log() if a["action"] == "profile_access"][0]["detail"]["grants"]
        assert grants["애드보킷"] == [] and "고정 지출·구독·수입" in grants["오퍼레이터"]

        pipeline.kill_all("test")
        with pytest.raises(RuntimeError):
            pipeline.start_topic("다른 주제")
    finally:
        pipeline.shutdown()


def test_killed_topic_stays_killed_after_loop_reset(tmp_path, monkeypatch, pipeline) -> None:
    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    s = Store(tmp_path / "f.sqlite")
    pipeline.launch(s, f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}", patents=FakePatents())
    try:
        s.set_loop_state("PAUSED", "test")
        topic_id = pipeline.start_topic("주제", actor="test")
        time.sleep(1)
        s.set_topic_status(topic_id, "KILLED")  # kill applied to the topic, cancel never reached it
        s.set_loop_state("RUN", "test")
        time.sleep(7)
        assert s.topic(topic_id)["status"] == "KILLED"
        assert s.ideas(topic_id=topic_id) == []
    finally:
        pipeline.shutdown()


def test_final_round_turns_conditional_into_oppose(tmp_path, monkeypatch, pipeline) -> None:
    def undecided(group, system, user, **kwargs):
        if "아이디어 담당" in system:
            return {"ideas": [{"title": "세션 요약 봇", "problem": "p", "approach": "a"}]}, "fake"
        return {"stance": "conditional", "reason": "조건이 맞으면"}, "fake"

    monkeypatch.setattr(pipeline.llm, "chat_json", undecided)
    s = Store(tmp_path / "f.sqlite")
    pipeline.launch(s, f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}", patents=UncheckedSource())
    try:
        topic_id = pipeline.start_topic("주제", actor="test")
        assert wait_until_done(s, topic_id) == "DONE"
        idea = s.ideas(topic_id=topic_id)[0]
        assert idea["status"] == "REJECTED" and s.proposals() == []
        assert {(v["round"], v["stance"]) for v in s.votes(idea["id"])} == {(1, "conditional"), (2, "oppose")}
    finally:
        pipeline.shutdown()


CRASHING_CHILD = """
import os, sys, time
from all_tomorrow.idea_factory import pipeline
from all_tomorrow.idea_factory.patents import UncheckedSource
from all_tomorrow.idea_factory.store import Store
s = Store(sys.argv[1])
s.set_loop_state("PAUSED", "test")
pipeline.launch(s, sys.argv[2], patents=UncheckedSource())
print(pipeline.start_topic("크래시 주제", actor="test"), flush=True)
time.sleep(2)  # the workflow now sits in its durable pause sleep
os._exit(1)    # crash: no DBOS.destroy, the workflow stays PENDING in the system database
"""


def test_crashed_process_topic_is_recovered_by_the_next_launch(tmp_path, monkeypatch, pipeline) -> None:
    store_file, url = tmp_path / "f.sqlite", f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}"
    child = subprocess.run([sys.executable, "-c", CRASHING_CHILD, str(store_file), url],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert child.returncode == 1, child.stderr[-2000:]
    topic_id = child.stdout.strip().splitlines()[-1]
    s = Store(store_file)
    assert s.topic(topic_id)["status"] == "RUNNING" and s.ideas(topic_id=topic_id) == []

    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    s.set_loop_state("RUN", "test")
    pipeline.launch(s, url, patents=UncheckedSource())  # nobody calls start_topic here: recovery must run it
    try:
        assert wait_until_done(s, topic_id) == "DONE"
        assert {i["status"] for i in s.ideas(topic_id=topic_id)} == {"PROPOSED"}
        assert s.proposals()[0]["body"]["patent_check"].startswith("특허 미검사")
    finally:
        pipeline.shutdown()


def test_factory_refuses_a_dbos_runtime_it_does_not_own(tmp_path, pipeline) -> None:
    from dbos import DBOS

    other = DBOS(config={"name": "someone-else", "system_database_url": f"sqlite:///{(tmp_path / 'o.sqlite').as_posix()}"})
    try:
        with pytest.raises(pipeline.DBOSOwnershipError):
            pipeline.launch(Store(tmp_path / "f.sqlite"), f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}")
        pipeline.shutdown()  # must leave the other owner's runtime alone
        assert DBOS(config={"name": "probe", "system_database_url": "sqlite:///unused.sqlite"}) is other
    finally:
        DBOS.destroy()


def test_lowering_config_revokes_access_but_keeps_promotion_bonus(store) -> None:
    member = store.active_staff("operator")
    assert store.set_access(member["id"], 2, ["budget"], bonus=1) == 3
    assert store.set_access(member["id"], 0, []) == 1  # config lowered: base 0 + bonus 1
    assert store.active_staff("operator")["access_scopes"] == []


def test_bad_access_config_fails_at_launch() -> None:
    from all_tomorrow.idea_factory import profile

    source = {"name": "x", "kind": "rows", "level": 2, "scope": "budget"}
    profile.validate([source], [{"role": "r", "access_level": 3, "access_scopes": ["budget"]}])
    for bad_sources, bad_staff in (([{**source, "level": 4}], []), ([{**source, "kind": "?"}], []),
                                   ([source], [{"role": "r", "access_level": 4, "access_scopes": []}]),
                                   ([source], [{"role": "r", "access_level": 1, "access_scopes": "budget"}])):
        with pytest.raises(ValueError):
            profile.validate(bad_sources, bad_staff)


def test_sensitive_guard_normalises_spacing_case_and_zero_width() -> None:
    from all_tomorrow.idea_factory.profile import _safe

    for text in ("우 울", "자​해", "ADHD", "adhd", "self-harm", "약값 3만원", "틴더 플러스", "호르몬 요법"):
        assert not _safe(text), text
    for text in ("약속 잡기", "코덱스 구독", "Flesh Pit — 인디게임 개발"):
        assert _safe(text), text


def test_user_judgments_promote_and_retire_staff(store) -> None:
    roster = load_roster()
    roster.evaluation_min_samples = 2
    for n in range(2):
        store.add_topic(f"t{n}", "주제")
        store.put_idea({"id": f"t{n}-i1", "topic_id": f"t{n}", "idx": 1, "title": "x", "problem": "",
                        "approach": "", "ideator_id": "ideator-g1"})
        store.put_vote(f"t{n}-i1", roster.council_rounds, "skeptic-g1", "support", "")
        store.put_vote(f"t{n}-i1", roster.council_rounds, "visionary-g1", "oppose", "")
        store.put_proposal(f"t{n}-p", f"t{n}", f"t{n}-i1", {"title": "x"})
        store.decide_proposal(f"t{n}-p", "APPROVED", "", "owner")
    actions = {a["staff_id"]: a["action"] for a in evaluation.apply_policy(store, roster)}
    assert actions == {"ideator-g1": "promote", "skeptic-g1": "promote", "visionary-g1": "retire"}
    assert store.active_staff("visionary")["id"] == "visionary-g2"
    assert store.active_staff("ideator")["model_group"] == "g-gpt-oss-120b"
    assert store.active_staff("skeptic")["access_level"] == 3  # promotion widens access (base 2)
    assert store.active_staff("visionary")["access_level"] == 1  # replacement starts at the role's base
    # promoted members start over: the same samples do not promote them again
    assert evaluation.apply_policy(store, roster) == []


def test_sensitive_lines_never_leave_even_from_allowed_sections(monkeypatch) -> None:
    from all_tomorrow.idea_factory import profile

    blocks = [{"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "선호"}]}},
              {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "텍스트 매체를 선호한다."}]}},
              {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "벤조디아제핀 계열 약물을 싫어한다."}]}},
              {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "기본 정보"}]}},
              {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "기본 정보 줄"}]}}]
    monkeypatch.setattr(profile, "_blocks", lambda page: blocks)
    text = profile._sections_digest({"page": "p", "sections": ["선호"]})
    assert "텍스트 매체" in text and "약물" not in text and "기본 정보 줄" not in text


def test_configured_profile_sources_exclude_sensitive_owners() -> None:
    roster = load_roster()
    configured = {s.get("page") or s.get("data_source") for s in roster.profile_sources}
    sensitive = {"3d34b985-2216-81f0-a0ac-d16b9a94732d",  # 현재 복약
                 "8f2e8dbc-b611-4e35-a1b8-d36750f0900c",  # 일기 원장
                 "19636ee0-53d9-433d-a44c-43cd7ff0efb4",  # 생활 상태·증상
                 "3e14b985-2216-81ee-87c9-d96cca438da1",  # 성적 생활관리
                 "60139c09-143e-464a-9076-6adeb742df48"}  # 인물·관계
    assert not configured & sensitive
    sheet = [s for s in roster.profile_sources if s.get("page") == "3cf4b985-2216-81bf-81a8-e4eee4f4dae6"]
    assert all("기본 정보" not in s["sections"] for s in sheet)


def test_budget_digest_states_monthly_totals_without_double_counting(monkeypatch) -> None:
    from all_tomorrow.idea_factory import profile

    def row(item, kind, amount, period="월", active=True):
        return {"properties": {"항목": {"type": "title", "title": [{"plain_text": item}]},
                               "구분": {"type": "select", "select": {"name": kind}},
                               "금액": {"type": "number", "number": amount},
                               "주기": {"type": "select", "select": {"name": period}},
                               "활성": {"type": "checkbox", "checkbox": active}}}
    rows = [row("용돈", "수입", 50000), row("구독A", "구독", 30000), row("구독B", "구독", 27000),
            row("월 적자", "기타", -7000), row("일회 비용", "변동지출", 10000, period="일회"),
            row("해지됨", "구독", 99000, active=False)]
    monkeypatch.setattr(profile, "_query", lambda ds: rows)
    text = profile._rows_digest({"data_source": "x", "fields": ["항목", "구분", "금액", "주기"], "only_checked": "활성",
                                 "monthly_totals": {"period": "주기", "kind": "구분", "amount": "금액",
                                                    "income": ["수입"], "spend": ["구독", "고정지출", "변동지출"]}})
    assert text.splitlines()[0].startswith("[월 합계] 수입 50,000원, 반복 지출 57,000원, 차액 -7,000원")
    assert "해지됨" not in text


def test_summary_leak_check_rejects_digits_and_hidden_facts() -> None:
    from all_tomorrow.idea_factory.pipeline import _leaks

    hidden = ["- 항목=코덱스; 구분=구독; 금액=30000", "- 목표/프로젝트=Flesh Pit 인디게임"]
    assert _leaks("월 3만 원이라 어렵다", hidden)
    assert _leaks("코덱스 구독료 때문에 어렵다", hidden)
    assert not _leaks("의뢰인 사정상 자금 여유가 없다", hidden)
