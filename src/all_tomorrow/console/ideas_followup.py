"""아이디어 '추가 조사': 사용자가 대충 쓴 짧은 요청을 그 아이디어의 맥락과 함께 완전한 조사 요청으로 만든다.

모델을 따로 부르지 않는다. 맥락(원문, 과제 현황, 종합본 — 없으면 압축본)을 붙이고,
"짧은 요청을 이 아이디어 맥락에서 풀고, 푼 조사 질문을 결과 맨 위에 적어라"를 조사하는 쪽(자료봉 GPT 또는 Codex)에게 맡긴다.

- mode "paste": 자료봉(GPT)에 붙일 글. 결과는 사용자가 '자료 넣기'로 되붙인다.
- mode "codex": 조사 목록의 Codex 실행기가 쓰는 글. 결과는 실행기가 자유 자료로 넣는다(overseer.idle_research).

압축(compress_prompt)과 종합(synth_prompt)도 여기서 만든다. 어느 쪽에도 결과·자료 원문은 압축할 그 하나 말고는 들어가지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

from all_tomorrow.console import ideas_jev

LABEL = "Codex 추가 조사"
MAX_CONTEXT = 14_000

RULES = {
    "codex": """- 사용자는 지금 자리에 없다. 되묻지 말고 가장 그럴듯한 해석으로 끝까지 조사한다.
- 파일을 만들거나 고치지 않는다. 명령으로 바꾸는 일(설치·커밋·삭제)도 하지 않는다. 읽기와 웹 검색만 한다.
- 이 작업 폴더는 이 아이디어와 무관할 수 있다. 필요하지 않으면 읽지 않는다.""",
    "paste": """- 되묻지 말고 가장 그럴듯한 해석으로 끝까지 조사한다. 이 대화에서 PC나 파일은 볼 수 없고 웹은 볼 수 있다.
- 답 전체가 그대로 복사되어 이 아이디어의 자료로 저장된다. 인사·맺음말 없이 아래 형식으로만 답한다.""",
}

TEMPLATE = """너는 사업 아이디어 조사 담당이다. 아래 [아이디어와 지금까지의 조사]를 알고 있는 사람이 쓴 짧은 [추가 조사 요청]을,
이 아이디어의 맥락에서 풀어 웹 검색으로 조사해 한국어 보고서 하나로 답한다.

## 규칙
{rules}
- 요청이 짧거나 모호해도 위 맥락으로 의미를 정한다. "더", "그쪽", "B안", "일본에서도"처럼 생략된 말은 맥락에서 무엇을 가리키는지 찾아 채운다.
  해석이 갈리면 가장 가능성 높은 것을 고르고, 고른 이유와 버린 해석을 해석 칸에 적는다.
- 이미 아는 것은 반복하지 않는다. 필요하면 "이미 아는 것과 이어지는 곳"에서 한 줄로만 가리킨다. 새로 알아내는 것에 분량을 쓴다.
- 주장마다 출처 링크를 붙이고, 날짜가 중요한 사실은 기준 시점을 적는다. 확인한 것과 추정을 구분한다. 모르면 모른다고 적는다.
- 찾은 사실만 쓴다. 네 평가·권고·우선순위·방향 판단("~가 유망하다", "~부터 해야 한다", "조사자 판단상")은 쓰지 않는다. 판단은 사용자가 한다.

## 답의 형식 (이 순서, 이 제목 그대로)
## 해석한 조사 질문
(사용자의 짧은 요청을 이 아이디어 맥락에서 풀어 쓴 질문 1~3문장. 하위 질문이 있으면 목록으로. 해석에 둔 가정은 가정이라고 표시)
## 한 줄 결론
## 찾은 것
(항목마다 출처 URL · 기준 시점 · 확인/추정)
## 이미 아는 것과 이어지는 곳
(기존 결과와 맞는 사실, 부딪치는 사실)
## 아직 모르는 것
(찾지 못한 사실만. 무엇을 하라는 권고는 쓰지 않는다)

[추가 조사 요청]
{request}

[아이디어와 지금까지의 조사]
{context}
"""


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def build_context(idea: dict[str, Any], synth: bool = True) -> str:
    """원문, 쪼개기 과제별 현황, 그리고 종합본. 종합본이 아직 없으면 압축본(결과·자유 자료).
    결과 본문·자료 원문은 넣지 않는다. 길면 끝을 줄인다. synth=False는 종합을 새로 만들 때(종합본은 따로 붙는다)."""
    latest: dict[str, dict[str, Any]] = {}
    for r in idea["results"]:                      # 최신이 앞이므로 처음 나온 것이 현재 결과
        latest.setdefault(r["subtask_id"], r)
    tasks = idea.get("tasks") or ideas_jev.plan_tasks(idea.get("plan", ""))
    status = []
    for sid in sorted({*tasks, *latest}, key=lambda s: (s == "?", int(s[1:]) if s[1:].isdigit() else 999)):
        title = (tasks.get(sid, {}).get("title") or (latest.get(sid) or {}).get("subtask_title") or "").strip()
        r = latest.get(sid)
        if r is None:
            status.append(f"- {sid} {title}: 아직 결과 없음")
        else:
            status.append(f"- {sid} {title} [R{r['id']} · {r['status'] or '상태 표시 없음'} · 주장 {len(r['claims'])}개]")
    parts = [f"제목: {idea['title']} ({idea['id']})", "", "### 원문", _clip(idea["text"], 3000)]
    if idea.get("plan") and not tasks:
        parts += ["", "### 과제 쪼개기 요지", _clip(idea["plan"], 1500)]
    parts += ["", "### 과제 현황", *(status or ["- 아직 과제·결과 없음"])]
    if synth and idea.get("synth"):
        parts += ["", "### 지금까지의 종합 (R=하위 과제 결과, M=자유 자료)", idea["synth"]]
    elif synth:
        # 종합 전: 압축본만, 아직이면 제목 한 줄만. 원문은 읽히지 않는다.
        answered = [f"- R{r['id']} {sid}: " + (_clip(r["summary"], 700) if r["summary"] else "(압축 대기)")
                    for sid, r in latest.items()]
        if answered:
            parts += ["", "### 하위 과제 결과 (압축본)", *answered]
        if idea["materials"]:
            parts += ["", "### 사용자가 직접 모은 자유 자료 (오래된 순, 압축본)"]
            for m in reversed(idea["materials"]):
                note = f" ({_clip(m['note'], 100)})" if m["note"] else ""
                parts.append(f"- M{m['id']} {m['title'][:60]} · {m['label'][:50]}{note}: "
                             + (_clip(m["summary"], 700) if m["summary"] else "(압축 대기)"))
    text = "\n".join(parts)
    return text if len(text) <= MAX_CONTEXT else text[:MAX_CONTEXT].rstrip() + "\n…(맥락이 길어 여기서 줄임)"


def build_prompt(idea: dict[str, Any], request: str, mode: str) -> str:
    if mode not in RULES:
        raise ValueError("mode는 codex 또는 paste")
    request = request.strip()
    if not request:
        raise ValueError("추가 조사 요청이 비어 있다")
    return TEMPLATE.format(rules=RULES[mode], request=request, context=build_context(idea))


def material_item(request: str, output: str, run_id: str) -> dict[str, Any]:
    """조사 결과를 아이디어 자유 자료로 넣을 항목(ideas_intake의 항목과 같은 모양)."""
    request = request.strip()
    return {"kind": "paste", "label": LABEL, "url": "", "title": "추가 조사: " + _clip(request, 40),
            "body": output.strip(), "note": f"요청 원문: {_clip(request, 300)} · 실행 {run_id}"}


COMPRESS = """너는 사업 아이디어 조사 자료를 압축하는 담당이다. 아래 [새 자료]는 이 아이디어에 대해 조사된 원문이다
(자료봉 하위 과제 결과이거나 사용자가 직접 모은 자료).
이 원문은 보관만 하고, 이후 관제와 다른 모델은 네가 쓴 압축본만 읽는다. 압축본이 틀리거나 부풀면 이후 판단이 전부 틀어진다.

## 규칙
- 웹 검색을 하지 않는다. 파일을 읽거나 고치지 않는다. 아래 글만 보고 답한다. 원문에 없는 것을 지어내지 않는다.
- 압축본만 답한다. 인사·설명 없이 아래 형식으로만 쓴다.
- 분량은 원문의 1/5 이하, 최대 {limit}자. 원문이 짧으면 그보다 더 짧게.
- 숫자·고유명사·날짜는 정확히 옮긴다. 출처(URL·글 이름)가 원문에 있으면 그 항목에 붙인다. 원문에 출처가 없으면 "출처 없음"이라고 적는다.
- [이미 아는 것]과 겹치는 내용은 "이미 앎" 한 줄로 줄이고, 새 항목으로 풀어 쓰지 않는다.

## 검열: 원문 작성자의 주관을 걸러 낸다
원문은 대개 조사 에이전트(자료봉 GPT, Codex 추가 조사 등)가 썼다. 이 에이전트들은 찾은 사실에 자기 평가·권고·우선순위를
근거 없이 섞는 버릇이 있다. 너는 그것을 걸러 내는 검열관이다. 사용자는 사실만 받고 판단은 직접 한다.
- 옮긴다: 출처가 있는 사실·숫자·날짜, 출처가 밝힌 사람·회사의 발언(누가 말했는지 붙여서), 출처가 있는 데이터에 기댄 추정(끝에 (추정)).
- 뺀다: 원문 작성자의 평가(유망하다·약하다·차별화가 어렵다·입증되지 않았다·타당하다), 권고(~해야 한다·먼저 ~한다·~를 추천),
  우선순위·방향 판단("조사자 판단상", "가장 중요한 것은"), 사업에 주는 뜻·시사점, 근거 없는 추정. 사실 문장 끝에 붙은 평가 꼬리도 잘라 낸다.
- 너도 같은 것을 새로 쓰지 않는다. 걸러 낸 자리에 네 말로 바꿔 넣지 않는다.
- 판단이 서지 않으면 뺀다. 빠진 사실은 원문에 남아 있지만, 섞인 의견은 이후 판단을 오염시킨다.

## 형식 (이 제목 그대로)
## 과제의 답
(하위 과제 결과일 때만: 그 과제 질문에 대해 원문이 찾은 사실 1~2줄. 원문의 결론이 사실이 아니라 의견이면 "원문 결론은 의견이라 뺌". 자유 자료면 "해당 없음")
## 새로 더해진 것
(이 아이디어에 새로 들어온 사실·숫자·주장. 불릿, 항목마다 출처)
## 이미 앎
(겹치는 것을 한 줄로)
## 어긋나는 주장
(이미 아는 것이나 자료 안의 다른 주장과 부딪치는 사실. 없으면 "없음")
## 뺀 의견
(걸러 낸 의견·권고·평가의 개수만. 예: "4건". 내용은 쓰지 않는다)

[아이디어]
{context}

[새 자료]
제목: {title}
출처: {label}{note}
원문 {size}자{cut}:
<material>
{body}
</material>
"""
COMPRESS_LIMIT = 1500
COMPRESS_INPUT = 100_000


def compress_prompt(idea: dict[str, Any], material: dict[str, Any]) -> str:
    """보관된 원문 하나(자유 자료 또는 하위 과제 결과, IdeaStore.item 모양)를 압축하라는 Codex 요청.
    그 아이디어의 지금 종합본(없으면 압축본들)을 '이미 아는 것'으로 붙인다. 자기 자신은 맥락에서 뺀다."""
    if material.get("kind") == "result":
        others = {**idea, "results": [r for r in idea["results"] if r["id"] != material["id"]]}
    else:
        others = {**idea, "materials": [m for m in idea["materials"] if m["id"] != material["id"]]}
    body = material["body"].strip()
    cut = ""
    if len(body) > COMPRESS_INPUT:
        body = body[:COMPRESS_INPUT * 3 // 4] + "\n…(중간 생략)…\n" + body[-COMPRESS_INPUT // 4:]
        cut = f" 중 앞뒤 {COMPRESS_INPUT}자만 넣음"
    limit = min(COMPRESS_LIMIT, max(300, len(material["body"].strip()) // 5))
    return COMPRESS.format(limit=limit, context=build_context(others), title=material["title"], label=material["label"],
                           note=f" ({material['note']})" if material["note"] else "", size=len(material["body"]), cut=cut, body=body)


SYNTH = """너는 사업 아이디어 조사를 정리하는 담당이다. 새로 조사하지 않는다. 이미 조사된 것을 아이디어 하나의 짧은 종합본으로 묶는다.
관제와 다른 모델은 이 종합본만 읽는다. 원문은 보관만 한다. 종합본이 틀리거나 부풀면 이후 판단이 전부 틀어진다.

## 규칙
- 웹 검색을 하지 않는다. 파일을 읽거나 고치지 않는다. 아래 글만 보고 답한다. 없는 것을 지어내지 않는다.
- 종합본만 답한다. 인사·설명 없이 아래 형식으로만 쓴다. 전체 {limit}자 이하. 넘치면 덜 중요한 주장부터 뺀다.
- 출처는 입력의 id로 적는다: R<번호>=하위 과제 결과, M<번호>=자유 자료. 예: [R3, M2]. URL은 꼭 필요한 한두 개만.
- 서로 다른 입력에서 같은 주장은 한 줄로 합치고 id를 모두 단다. 같은 말을 두 번 쓰지 않는다.
- 숫자·고유명사·날짜는 입력 그대로 옮긴다. 확인된 것과 추정을 구분한다.
- 네 의견을 넣지 않는다. 평가(유망하다·약하다·입증되지 않았다·타당하다), 권고(~해야 한다·먼저 ~한다), 우선순위·방향 판단, '우리에게' 어떤 뜻인지를 쓰지 않는다. 입력에 그런 말이 있어도 입력 작성자(조사한 모델 포함)의 의견이면 옮기지 않는다. 사실·숫자·출처가 있는 인용만 옮긴다.
{mode}

## 형식 (이 제목 그대로, 이 순서)
## 한 줄 결론
(입력이 알아낸 사실의 요약. 권고·평가 없이)
## 질문별 답
(과제마다 한 줄: "- S1 과제 제목: 입력이 낸 답 · [R…]". 입력이 확신도를 적었으면 붙인다. 결과가 없는 과제는 "아직 결과 없음")
## 주장
(합친 주장 목록. "- 주장 [R1, R4, M2]". 추정이면 끝에 (추정))
## 어긋나는 주장
(입력끼리 부딪치는 것과 각각의 id. 없으면 "없음")
## 빈 곳
(결과가 없는 과제, 입력이 모른다고 적은 것. 네가 중요도를 매기지 않는다)

[아이디어]
{context}
{previous}
[{new_label}]
{new}
"""
SYNTH_LIMIT = 3000


def synth_prompt(idea: dict[str, Any], job: dict[str, Any]) -> str:
    """종합본을 만들라는 Codex 요청(IdeaStore.synth_job). 이전 종합본이 있으면 그것과 새 압축본만, 없으면 압축본 전부.
    결과 본문·자료 원문은 넣지 않는다."""
    new = "\n\n".join(f"### {i['label']}\n{i['summary']}" for i in job["new"])
    if job["previous"]:
        mode = ("- [이전 종합본]을 바탕으로 [새 압축본]을 더해 고쳐 쓴다. 새 압축본이 이전 종합과 겹치면 id만 덧붙이고, "
                "부딪치면 어긋나는 주장에 올린다. 이전 종합본의 내용은 근거 없이 지우지 않는다.")
        previous = f"\n[이전 종합본]\n{job['previous']}\n"
        label = "새 압축본"
    else:
        mode = "- 아래 [압축본]이 이 아이디어에 대해 조사된 것 전부다."
        previous, label = "", "압축본"
    return SYNTH.format(limit=SYNTH_LIMIT, mode=mode, context=build_context(idea, synth=False),
                        previous=previous, new_label=label, new=new)
