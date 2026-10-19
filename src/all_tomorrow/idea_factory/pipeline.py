"""Idea factory workflow on DBOS: topic → ideas → patent filter → council → proposal.

Each LLM/search call is a DBOS step, so a crashed process resumes from the last
finished step. Pause/KILL are read from the store at checkpoints between steps.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from dbos import DBOS, SetWorkflowID

from all_tomorrow.idea_factory import llm
from all_tomorrow.idea_factory.config import REPO_ROOT, Roster, load_roster
from all_tomorrow.idea_factory.patents import PatentSource, default_source
from all_tomorrow.idea_factory.store import Store

COUNCIL = ("visionary", "operator", "advocate", "skeptic")
STANCES = ("support", "oppose", "conditional")
APP_VERSION = "idea-factory-1"

ROLE_BRIEF = {
    "visionary": "비저너리. 이 아이디어가 크게 보면 무엇이 될 수 있는지, 확장성과 장기 가치를 본다.",
    "operator": "오퍼레이터. 1인 개발자, 무료 API 키, AWS 프리티어라는 실제 자원으로 만들고 운영할 수 있는지, 공수를 본다.",
    "advocate": "애드보킷. 실제 사용자/고객 입장에서 왜 쓰는지, 돈을 낼 의사가 있는지를 본다.",
    "skeptic": "스켑틱. 왜 실패하는지, 숨은 전제와 리스크를 찾는다. 쉽게 지지하지 않는다.",
}

_state: dict[str, Any] = {}


def store() -> Store:
    return _state["store"]


def roster() -> Roster:
    return _state["roster"]


def patent_source() -> PatentSource:
    return _state["patents"]


def configure(store_obj: Store, roster_obj: Roster | None = None, patents: PatentSource | None = None) -> None:
    _state["store"] = store_obj
    _state["roster"] = roster_obj or load_roster()
    _state["patents"] = patents or default_source()
    for member in _state["roster"].staff:
        store_obj.hire(member["role"], member["name"], member["model_group"])


def launch(store_obj: Store, system_database_url: str | None = None, **kwargs: Any) -> None:
    configure(store_obj, **kwargs)
    url = system_database_url or os.environ.get(
        "IDEA_FACTORY_DBOS_URL", f"sqlite:///{(REPO_ROOT / '.artifacts' / 'idea-factory-dbos.sqlite').as_posix()}")
    DBOS(config={"name": "all-tomorrow-idea-factory", "system_database_url": url,
                 "application_version": APP_VERSION})
    DBOS.launch()


# --------------------------------------------------------------------------- steps

@DBOS.step()
def read_loop_state(topic_id: str) -> str:
    # A killed topic stays killed even after the loop is reset (e.g. recovered after a crash).
    topic = store().topic(topic_id)
    if topic and topic["status"] == "KILLED":
        return "KILLED"
    return store().loop_state()


def checkpoint(topic_id: str) -> bool:
    """Blocks while paused (durable sleep). False means KILLED."""
    state = read_loop_state(topic_id)
    while state == "PAUSED":
        DBOS.sleep(5)
        state = read_loop_state(topic_id)
    return state != "KILLED"


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def generate_ideas(topic_id: str, topic: str, count: int) -> list[dict[str, Any]]:
    member = store().active_staff("ideator")
    data, served = llm.chat_json(
        member["model_group"],
        "너는 사업 아이디어 공장의 아이디어 담당이다. 주제에 맞는, 서로 확실히 다른 사업/제품 아이디어를 낸다. "
        "흔한 아이디어보다 구체적인 틈새를 노린다. 모든 문장은 한국어로 쓴다.",
        f"주제: {topic}\n아이디어 {count}개를 "
        '{"ideas":[{"title":"짧은 이름","problem":"해결하는 문제 한두 문장","approach":"어떻게 푸는지 한두 문장"}]} 형식으로.',
    )
    ideas = []
    for index, raw in enumerate((data.get("ideas") if isinstance(data, dict) else data) or []):
        if not isinstance(raw, dict) or not raw.get("title"):
            continue
        idea = {"id": f"{topic_id}-i{index + 1}", "topic_id": topic_id, "idx": index + 1,
                "title": str(raw["title"])[:200], "problem": str(raw.get("problem", ""))[:1000],
                "approach": str(raw.get("approach", ""))[:1000], "ideator_id": member["id"]}
        store().put_idea(idea)
        ideas.append(idea)
        if len(ideas) >= count:
            break
    if not ideas:
        raise llm.LLMError("ideator returned no ideas")
    store().event("generate", f"아이디어 {len(ideas)}개 생성", topic_id=topic_id, staff_id=member["id"],
                  dedupe=f"gen:{topic_id}")
    return ideas


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def synthesize(idea: dict[str, Any]) -> dict[str, Any]:
    member = store().active_staff("synthesizer")
    if getattr(patent_source(), "unchecked", False):
        store().set_idea_verdict(idea["id"], "IN_COUNCIL", synth_id=member["id"], evidence=[],
                                 reason="특허 미검사 (IDEA_FACTORY_PATENTS=unchecked)")
        store().event("synth", f"특허 미검사 → 회의: {idea['title']}", topic_id=idea["topic_id"],
                      staff_id=member["id"], dedupe=f"synth:{idea['id']}")
        return {"status": "PASSED", "evidence": [], "checked": 0}
    queries_data, _ = llm.chat_json(
        member["model_group"],
        "너는 특허 조사관 신서사이저다. 아이디어의 핵심 기술 요소로 특허 검색어를 만든다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n"
        '검색어 3개: 한국어 1개, 영어 2개. 각 검색어는 핵심 요소 2~4개 단어. {"queries":["...","...","..."]}',
        temperature=0.2,
    )
    queries = [str(q) for q in (queries_data.get("queries") or [])][:3] if isinstance(queries_data, dict) else []
    hits: dict[str, dict[str, str]] = {}
    failures = 0
    for query in queries:
        try:
            for hit in patent_source().search(query, limit=6):
                hits.setdefault(hit.number, hit.as_dict())
        except Exception:  # noqa: BLE001 - counted; all-failed means "조사 불가"
            failures += 1
    if not queries or failures == len(queries):
        store().set_idea_verdict(idea["id"], "HELD", synth_id=member["id"], reason="특허 조사 불가 (검색 실패)")
        store().event("synth", f"조사 불가 → 보류: {idea['title']}", topic_id=idea["topic_id"],
                      staff_id=member["id"], dedupe=f"synth:{idea['id']}")
        return {"status": "HELD", "evidence": []}
    listing = "\n".join(f"- [{n}] {h['title']} :: {h['snippet'][:250]}" for n, h in list(hits.items())[:15])
    judgment, _ = llm.chat_json(
        member["model_group"],
        "너는 특허 조사관 신서사이저다. 아이디어의 핵심 요소와 실질적으로 겹치는 특허가 하나라도 있으면 그 아이디어는 폐기다. "
        "단어가 비슷한 것만으로는 겹침이 아니다. 아이디어를 성립시키는 핵심 요소(무엇을, 어떤 방식으로)가 특허에 이미 있어야 겹침이다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n\n검색된 특허:\n{listing or '(없음)'}\n\n"
        '{"overlaps":[{"number":"특허번호","element":"겹치는 핵심 요소"}],"reason":"판단 이유 한 문장"} '
        "겹침이 없으면 overlaps는 빈 배열.",
        temperature=0.1,
    )
    overlaps = [o for o in (judgment.get("overlaps") or []) if isinstance(o, dict) and o.get("number") in hits]
    reason = str(judgment.get("reason", ""))[:500]
    evidence = [{**hits[o["number"]], "element": str(o.get("element", ""))[:300]} for o in overlaps]
    if evidence:
        store().set_idea_verdict(idea["id"], "KILLED", synth_id=member["id"], evidence=evidence, reason=reason)
        store().event("synth", f"이미 존재 → 폐기: {idea['title']} ({evidence[0]['number']})",
                      topic_id=idea["topic_id"], staff_id=member["id"], dedupe=f"synth:{idea['id']}")
        return {"status": "KILLED", "evidence": evidence}
    store().set_idea_verdict(idea["id"], "IN_COUNCIL", synth_id=member["id"], evidence=[], reason=reason)
    store().event("synth", f"특허 통과 → 회의: {idea['title']} (검색 {len(hits)}건)",
                  topic_id=idea["topic_id"], staff_id=member["id"], dedupe=f"synth:{idea['id']}")
    return {"status": "PASSED", "evidence": [], "checked": len(hits)}


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def council_vote(idea: dict[str, Any], round_no: int, role: str, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    member = store().active_staff(role)
    final_round = round_no == roster().council_rounds
    patent_note = "미검사" if getattr(patent_source(), "unchecked", False) else "겹치는 특허 없음"
    ask = ('최종 라운드다. 조건부는 없다. 조건이 충족 가능하다고 보면 support, 아니면 oppose. '
           '{"stance":"support|oppose","reason":"근거 두세 문장"}' if final_round
           else '{"stance":"support|oppose|conditional","reason":"근거 두세 문장"}')
    earlier ="\n".join(f"[{v['round']}라운드 {v['name']}] {v['stance']}: {v['reason']}" for v in transcript) or "(첫 발언)"
    data, _ = llm.chat_json(
        member["model_group"],
        f"너는 사업 아이디어 회의의 {ROLE_BRIEF[role]} 다른 사람 의견에 휩쓸리지 말고 네 관점으로 판단한다. 한국어로 쓴다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n"
        f"특허 조사: {patent_note}\n\n지금까지 회의:\n{earlier}\n\n{round_no}라운드 발언. {ask}",
        temperature=0.7,
    )
    stance = str(data.get("stance", "")).lower() if isinstance(data, dict) else ""
    if stance not in STANCES or (final_round and stance == "conditional"):
        # The final round must decide; no decision counts as no support.
        stance = "oppose" if final_round else "conditional"
    vote = {"round": round_no, "role": role, "staff_id": member["id"], "name": member["name"],
            "stance": stance, "reason": str(data.get("reason", ""))[:1200]}
    store().put_vote(idea["id"], round_no, member["id"], stance, vote["reason"])
    store().event("council", f"{member['name']} {stance}: {vote['reason'][:120]}", topic_id=idea["topic_id"],
                  staff_id=member["id"], dedupe=f"vote:{idea['id']}:{round_no}:{role}")
    return vote


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def write_proposal(idea: dict[str, Any], transcript: list[dict[str, Any]], checked: int) -> dict[str, Any]:
    member = store().active_staff("operator")
    talk = "\n".join(f"[{v['round']}R {v['name']}] {v['stance']}: {v['reason']}" for v in transcript)
    data, _ = llm.chat_json(
        member["model_group"],
        "너는 회의 결과를 사용자에게 보고할 기획안으로 정리한다. 회의에서 나온 리스크를 숨기지 않는다. 한국어로 쓴다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n회의:\n{talk}\n\n"
        '{"title":"","problem":"","approach":"","dod":["완료 조건"],"risks":["리스크"],'
        '"market":"시장·경쟁 상황","effort":"S|M|L","first_step":"가장 먼저 할 일"}',
        temperature=0.3,
    )
    body = {k: data.get(k) for k in ("title", "problem", "approach", "dod", "risks", "market", "effort", "first_step")}
    body["title"] = body["title"] or idea["title"]
    body["patent_check"] = ("특허 미검사 — KIPRIS 키 설정 후 재검사 필요" if getattr(patent_source(), "unchecked", False)
                            else f"관련 특허 없음 (검색 {checked}건, {patent_source().name})")
    body["votes"] = [{k: v[k] for k in ("round", "name", "stance", "reason")} for v in transcript]
    proposal_id = f"{idea['id']}-p"
    store().put_proposal(proposal_id, idea["topic_id"], idea["id"], body)
    store().set_idea_verdict(idea["id"], "PROPOSED")
    store().event("proposal", f"기획안 보고: {body['title']}", topic_id=idea["topic_id"],
                  staff_id=member["id"], dedupe=f"proposal:{idea['id']}")
    return {"proposal_id": proposal_id}


@DBOS.step()
def reject_in_council(idea: dict[str, Any], supports: int) -> None:
    store().set_idea_verdict(idea["id"], "REJECTED", reason=f"회의 최종 지지 {supports}/4")
    store().event("council", f"회의 탈락: {idea['title']} (지지 {supports}/4)", topic_id=idea["topic_id"],
                  dedupe=f"reject:{idea['id']}")


@DBOS.step()
def finish_topic(topic_id: str, status: str) -> None:
    store().set_topic_status(topic_id, status)
    store().event("topic", f"주제 종료: {status}", topic_id=topic_id, dedupe=f"finish:{topic_id}")


# ------------------------------------------------------------------------ workflow

@DBOS.workflow()
def factory_run(topic_id: str, topic: str) -> str:
    settings = roster()
    if not checkpoint(topic_id):
        finish_topic(topic_id, "KILLED")
        return "KILLED"
    ideas = generate_ideas(topic_id, topic, settings.ideas_per_topic)
    for idea in ideas:
        if not checkpoint(topic_id):
            finish_topic(topic_id, "KILLED")
            return "KILLED"
        verdict = synthesize(idea)
        if verdict["status"] != "PASSED":
            continue
        transcript: list[dict[str, Any]] = []
        for round_no in range(1, settings.council_rounds + 1):
            for role in COUNCIL:
                if not checkpoint(topic_id):
                    finish_topic(topic_id, "KILLED")
                    return "KILLED"
                transcript.append(council_vote(idea, round_no, role, transcript))
        final = [v for v in transcript if v["round"] == settings.council_rounds]
        supports = sum(1 for v in final if v["stance"] == "support")
        if supports >= settings.council_pass_votes:
            write_proposal(idea, transcript, verdict.get("checked", 0))
        else:
            reject_in_council(idea, supports)
    finish_topic(topic_id, "DONE")
    return "DONE"


def start_topic(text: str, actor: str = "user") -> str:
    text = text.strip()
    if not text:
        raise ValueError("topic must not be empty")
    if store().loop_state() == "KILLED":
        raise RuntimeError("loop is KILLED; reset it before starting a topic")
    topic_id = "t" + uuid.uuid4().hex[:10]
    store().add_topic(topic_id, text)
    store().audit(actor, "topic_start", {"topic_id": topic_id, "text": text})
    with SetWorkflowID(topic_id):
        DBOS.start_workflow(factory_run, topic_id, text)
    return topic_id


def kill_all(actor: str = "user") -> int:
    store().set_loop_state("KILLED", actor)
    cancelled = 0
    for topic in store().topics(limit=1000):
        if topic["status"] == "RUNNING":
            store().set_topic_status(topic["id"], "KILLED")  # before cancel, so a failed cancel still stops it
            DBOS.cancel_workflow(topic["id"])
            cancelled += 1
    return cancelled
