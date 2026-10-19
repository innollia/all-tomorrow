"""Idea factory workflow on DBOS: topic → ideas → patent filter → council → proposal.

Each LLM/search call is a DBOS step, so a crashed process resumes from the last
finished step. Pause/KILL are read from the store at checkpoints between steps.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

from dbos import DBOS, SetWorkflowID

from all_tomorrow.idea_factory import llm, profile
from all_tomorrow.idea_factory.config import Roster, dbos_url, export_secrets_to_env, load_roster
from all_tomorrow.idea_factory.patents import PatentSource, default_source
from all_tomorrow.idea_factory.store import Store

COUNCIL = ("visionary", "operator", "advocate", "skeptic")
STANCES = ("support", "oppose", "conditional")
APP_VERSION = "idea-factory-2"  # step signatures changed (profile access)

ROLE_BRIEF = {
    "visionary": "비저너리. 이 아이디어가 크게 보면 무엇이 될 수 있는지, 확장성과 장기 가치를 본다.",
    # Briefs stay generic. User facts reach a member only through profile access (level + scopes).
    "operator": "오퍼레이터. 실제로 만들고 운영하는 데 필요한 인력·비용·기간과 운영 난이도, 공수를 본다.",
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
    profile.validate(_state["roster"].profile_sources, _state["roster"].staff)
    if _state["roster"].council_share not in SHARE_MODES:
        raise ValueError(f"council_share must be one of {SHARE_MODES}")
    for member in _state["roster"].staff:
        store_obj.hire(member["role"], member["name"], member["model_group"],
                       access_level=member.get("access_level", 0), access_scopes=member.get("access_scopes", []))
        # Config owns base level and scopes (the role's function); promotions add a bonus on top.
        active = store_obj.active_staff(member["role"])
        store_obj.set_access(active["id"], member.get("access_level", 0), member.get("access_scopes", []))


class DBOSOwnershipError(RuntimeError):
    """DBOS in this process was configured by another component."""


def launch(store_obj: Store, system_database_url: str | None = None, **kwargs: Any) -> None:
    """Configure the factory and launch DBOS, which recovers this version's unfinished topics.

    DBOS is a process-global singleton and DBOS(config=...) silently returns an existing
    instance with *its* config. The factory owns DBOS only in a process where nothing else
    configured it (the web process and the CLI today); if another component got there first,
    launching would run the factory on someone else's system database and app version, and
    shutdown() would destroy their runtime, so it refuses instead.
    """
    export_secrets_to_env()
    configure(store_obj, **kwargs)
    DBOS(config={"name": "all-tomorrow-idea-factory", "system_database_url": system_database_url or dbos_url(),
                 "application_version": APP_VERSION})
    if DBOS.application_version != APP_VERSION:
        raise DBOSOwnershipError(
            f"DBOS is already configured in this process (application_version={DBOS.application_version!r}); "
            "the idea factory will not reuse or destroy another component's DBOS runtime")
    try:
        DBOS.launch()
    except BaseException:
        DBOS.destroy()  # ours (version matched): do not leave a half-launched singleton behind
        raise
    _state["owns_dbos"] = True


def shutdown() -> None:
    """Destroy DBOS only if launch() created it. The workflow registry stays for a later launch."""
    if _state.pop("owns_dbos", False):
        DBOS.destroy()


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


@DBOS.step()
def load_profile(topic_id: str) -> dict[str, Any]:
    """One profile snapshot per topic, recorded by DBOS so a resumed run sees the same facts."""
    sources = roster().profile_sources
    snapshot = profile.fetch_profile(sources) if sources and os.environ.get("NOTION_TOKEN") else {}
    grants = {m["name"]: sorted(profile.visible(snapshot, m["access_level"], m["access_scopes"]))
              for m in store().staff(include_retired=False)}
    store().audit("factory", "profile_access", {"topic_id": topic_id, "grants": grants,
                                                "errors": {k: v["error"] for k, v in snapshot.items() if "error" in v}})
    shared = ", ".join(f"{name} {len(items)}" for name, items in grants.items() if items) or "없음"
    store().event("access", f"의뢰인 정보 제공: {shared}", topic_id=topic_id, dedupe=f"access:{topic_id}")
    return snapshot


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def generate_ideas(topic_id: str, topic: str, count: int, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    member = store().active_staff("ideator")
    data, served = llm.chat_json(
        member["model_group"],
        "너는 사업 아이디어 공장의 아이디어 담당이다. 주제에 맞는, 서로 확실히 다른 사업/제품 아이디어를 낸다. "
        "흔한 아이디어보다 구체적인 틈새를 노린다. 모든 문장은 한국어로 쓴다.",
        f"주제: {topic}\n아이디어 {count}개를 "
        '{"ideas":[{"title":"짧은 이름","problem":"해결하는 문제 한두 문장","approach":"어떻게 푸는지 한두 문장"}]} 형식으로.'
        + profile.context_block(snapshot, member),
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


def _sources_of(member: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    return sorted(profile.visible(snapshot, member["access_level"], member["access_scopes"]))


OMITTED = "(권한 밖 근거 생략)"
SHARE_MODES = ("summary", "full", "filtered")


def _leaks(text: str, hidden_texts: list[str]) -> bool:
    """True if a summary still carries specifics: any digit, or a word that only appears in
    sources the listener may not see."""
    if re.search(r"\d", text):
        return True
    words = {w for t in hidden_texts for w in re.findall(r"[\w가-힣]{3,}", t)}
    return any(w in text for w in words)


def _transcript_for(listener_sources: list[str], transcript: list[dict[str, Any]],
                    snapshot: dict[str, Any], tag: str = "라운드") -> str:
    """A reason may carry the speaker's profile facts. It reaches a listener in full only if the
    listener could see every source the speaker saw (or council_share is "full"). Otherwise,
    in "summary" mode the speaker's own fact-free summary is passed if it passes the leak check;
    else only the stance."""
    mode = roster().council_share
    allowed = set(listener_sources)
    visible_texts = [snapshot[s]["text"] for s in allowed if s in snapshot]
    lines = []
    for v in transcript:
        # Votes recorded before this filter existed have no "sources": unknown counts as not allowed.
        known = v.get("sources")
        if mode == "full" or (known is not None and set(known) <= allowed):
            reason = v["reason"]
        elif mode == "summary" and known is not None and v.get("reason_public"):
            hidden = [snapshot[s]["text"] for s in set(known) - allowed if s in snapshot]
            hidden = [t for t in hidden if t not in visible_texts]
            reason = OMITTED if _leaks(v["reason_public"], hidden) else "(요약) " + v["reason_public"]
        else:
            reason = OMITTED
        lines.append(f"[{v['round']}{tag} {v['name']}] {v['stance']}: {reason}")
    return "\n".join(lines)


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def council_vote(idea: dict[str, Any], round_no: int, role: str, transcript: list[dict[str, Any]],
                 snapshot: dict[str, Any]) -> dict[str, Any]:
    member = store().active_staff(role)
    final_round = round_no == roster().council_rounds
    patent_note = "미검사" if getattr(patent_source(), "unchecked", False) else "겹치는 특허 없음"
    ask = ('최종 라운드다. 조건부는 없다. 조건이 충족 가능하다고 보면 support, 아니면 oppose. '
           '{"stance":"support|oppose","reason":"근거 두세 문장"}' if final_round
           else '{"stance":"support|oppose|conditional","reason":"근거 두세 문장"}')
    sources = _sources_of(member, snapshot)
    earlier = _transcript_for(sources, transcript, snapshot) or "(첫 발언)"
    if sources and roster().council_share == "summary":
        # A second, fact-free version of the reason for colleagues with less access.
        ask = ask[:-1] + (',"reason_public":"같은 판단을 의뢰인 정보의 구체 내용(숫자·금액·프로젝트명·일정) 없이 '
                          '\'의뢰인 사정상 ~\' 수준으로만 쓴 한두 문장"}')
    data, _ = llm.chat_json(
        member["model_group"],
        f"너는 사업 아이디어 회의의 {ROLE_BRIEF[role]} 다른 사람 의견에 휩쓸리지 말고 네 관점으로 판단한다. 한국어로 쓴다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n"
        f"특허 조사: {patent_note}\n\n지금까지 회의:\n{earlier}\n\n{round_no}라운드 발언. {ask}"
        + profile.context_block(snapshot, member),
        temperature=0.7,
    )
    stance = str(data.get("stance", "")).lower() if isinstance(data, dict) else ""
    if stance not in STANCES or (final_round and stance == "conditional"):
        # The final round must decide; no decision counts as no support.
        stance = "oppose" if final_round else "conditional"
    vote = {"round": round_no, "role": role, "staff_id": member["id"], "name": member["name"],
            "stance": stance, "reason": str(data.get("reason", ""))[:1200], "sources": sources}
    if sources and isinstance(data, dict) and data.get("reason_public"):
        vote["reason_public"] = str(data["reason_public"])[:600]
    store().put_vote(idea["id"], round_no, member["id"], stance, vote["reason"])
    store().event("council", f"{member['name']} {stance}: {vote['reason'][:120]}", topic_id=idea["topic_id"],
                  staff_id=member["id"], dedupe=f"vote:{idea['id']}:{round_no}:{role}")
    return vote


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
def write_proposal(idea: dict[str, Any], transcript: list[dict[str, Any]], checked: int,
                   snapshot: dict[str, Any]) -> dict[str, Any]:
    member = store().active_staff("operator")
    talk = _transcript_for(_sources_of(member, snapshot), transcript, snapshot, tag="R")
    data, _ = llm.chat_json(
        member["model_group"],
        "너는 회의 결과를 사용자에게 보고할 기획안으로 정리한다. 회의에서 나온 리스크를 숨기지 않는다. 한국어로 쓴다.",
        f"아이디어: {idea['title']}\n문제: {idea['problem']}\n접근: {idea['approach']}\n회의:\n{talk}\n\n"
        '{"title":"","problem":"","approach":"","dod":["완료 조건"],"risks":["리스크"],'
        '"market":"시장·경쟁 상황","effort":"S|M|L","first_step":"가장 먼저 할 일"}'
        + profile.context_block(snapshot, member),
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
    snapshot = load_profile(topic_id)
    ideas = generate_ideas(topic_id, topic, settings.ideas_per_topic, snapshot)
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
                transcript.append(council_vote(idea, round_no, role, transcript, snapshot))
        final = [v for v in transcript if v["round"] == settings.council_rounds]
        supports = sum(1 for v in final if v["stance"] == "support")
        if supports >= settings.council_pass_votes:
            write_proposal(idea, transcript, verdict.get("checked", 0), snapshot)
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
