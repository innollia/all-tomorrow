"""아이디어 '추가 조사': 사용자가 대충 쓴 짧은 요청을 그 아이디어의 맥락과 함께 완전한 조사 요청으로 만든다.

모델을 따로 부르지 않는다. 맥락(원문, 과제와 결과 요지, 자유 자료, 이미 답이 나온 것과 빈 곳)을 붙이고,
"짧은 요청을 이 아이디어 맥락에서 풀고, 푼 조사 질문을 결과 맨 위에 적어라"를 조사하는 쪽(자료봉 GPT 또는 Codex)에게 맡긴다.

- mode "paste": 자료봉(GPT)에 붙일 글. 결과는 사용자가 '자료 넣기'로 되붙인다.
- mode "codex": 조사 목록의 Codex 실행기가 쓰는 글. 결과는 실행기가 자유 자료로 넣는다(overseer.idle_research).
"""
from __future__ import annotations

import re
from typing import Any

from all_tomorrow.console import ideas_jev

LABEL = "Codex 추가 조사"
MAX_CONTEXT = 14_000
SECTION = re.compile(r"^#{1,6}\s*결론[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)", re.S | re.M)
MISSING = re.compile(r"^#{1,6}\s*빠진 것[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)", re.S | re.M)

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

## 답의 형식 (이 순서, 이 제목 그대로)
## 해석한 조사 질문
(사용자의 짧은 요청을 이 아이디어 맥락에서 풀어 쓴 질문 1~3문장. 하위 질문이 있으면 목록으로. 해석에 둔 가정은 가정이라고 표시)
## 한 줄 결론
## 찾은 것
(항목마다 출처 URL · 기준 시점 · 확인/추정)
## 이미 아는 것과 이어지는 곳
(기존 결과와 맞는 것, 부딪치는 것, 바뀌는 판단)
## 아직 모르는 것·다음에 볼 것

[추가 조사 요청]
{request}

[아이디어와 지금까지의 조사]
{context}
"""


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def conclusion(body: str, n: int = 320) -> str:
    m = SECTION.search(body)
    return _clip(m.group(1) if m else body, n)


def gaps(body: str, n: int = 200) -> str:
    m = MISSING.search(body)
    return _clip(m.group(1), n) if m else ""


def build_context(idea: dict[str, Any]) -> str:
    """원문, 쪼개기 과제별 현황(답이 나온 것/빈 곳), 자유 자료. 길면 끝을 줄인다."""
    latest: dict[str, dict[str, Any]] = {}
    for r in idea["results"]:                      # 최신이 앞이므로 처음 나온 것이 현재 결과
        latest.setdefault(r["subtask_id"], r)
    tasks = idea.get("tasks") or ideas_jev.plan_tasks(idea.get("plan", ""))
    answered, open_, extra = [], [], []
    for sid in sorted({*tasks, *latest}, key=lambda s: (s == "?", int(s[1:]) if s[1:].isdigit() else 999)):
        title = (tasks.get(sid, {}).get("title") or (latest.get(sid) or {}).get("subtask_title") or "").strip()
        r = latest.get(sid)
        if r is None:
            open_.append(f"- {sid} {title}: 아직 결과 없음")
        elif r["status"] == "완료":
            answered.append(f"- {sid} {title} [완료, 주장 {len(r['claims'])}개]: {conclusion(r['body'])}")
        else:
            why = gaps(r["body"])
            line = f"- {sid} {title} [{r['status'] or '상태 표시 없음'}]: {conclusion(r['body'], 200)}"
            (open_ if sid != "?" else extra).append(line + (f" / 빠진 것: {why}" if why else ""))
    parts = [f"제목: {idea['title']} ({idea['id']})", "", "### 원문", _clip(idea["text"], 3000)]
    if idea.get("plan") and not tasks:
        parts += ["", "### 과제 쪼개기 요지", _clip(idea["plan"], 1500)]
    parts += ["", "### 이미 답이 나온 것", *(answered or ["- 아직 없음"]),
              "", "### 빈 곳·불완전한 것", *(open_ or ["- (쪼개기 과제 중 비어 있는 것 없음)"]), *extra]
    mats = idea["materials"]
    if mats:
        parts += ["", "### 사용자가 직접 모은 자유 자료 (오래된 순)"]
        for m in reversed(mats):
            note = f" ({_clip(m['note'], 100)})" if m["note"] else ""
            # 원문은 읽히지 않는다. 압축본만, 아직이면 제목·출처 한 줄만.
            parts.append(f"- {m['title'][:60]} · {m['label'][:50]}{note}: " + (_clip(m["summary"], 700) if m["summary"] else "(압축 대기)"))
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


COMPRESS = """너는 사업 아이디어 조사 자료를 압축하는 담당이다. 아래 [새 자료]는 사용자가 직접 조사해 모은 원문이다.
이 원문은 보관만 하고, 이후 관제와 다른 모델은 네가 쓴 압축본만 읽는다. 압축본이 틀리거나 부풀면 이후 판단이 전부 틀어진다.

## 규칙
- 웹 검색을 하지 않는다. 파일을 읽거나 고치지 않는다. 아래 글만 보고 답한다. 원문에 없는 것을 지어내지 않는다.
- 압축본만 답한다. 인사·설명 없이 아래 형식으로만 쓴다.
- 분량은 원문의 1/5 이하, 최대 {limit}자. 원문이 짧으면 그보다 더 짧게.
- 숫자·고유명사·날짜는 정확히 옮긴다. 출처(URL·글 이름)가 원문에 있으면 그 항목에 붙인다. 원문에 출처가 없으면 "출처 없음"이라고 적는다.
- [이미 아는 것]과 겹치는 내용은 "이미 앎" 한 줄로 줄이고, 새 항목으로 풀어 쓰지 않는다.

## 형식 (이 제목 그대로)
## 새로 더해진 것
(이 아이디어에 새로 들어온 사실·숫자·주장. 불릿, 항목마다 출처)
## 이미 앎
(겹치는 것을 한 줄로)
## 어긋나는 주장
(이미 아는 것이나 자료 안의 다른 주장과 부딪치는 것. 없으면 "없음")
## 우리에게 주는 뜻
(1~3줄)

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
    """보관된 원문 하나를 압축하라는 Codex 요청. 그 아이디어의 지금 정리본(압축본들)을 '이미 아는 것'으로 붙인다.
    자기 자신은 맥락에서 뺀다."""
    others = {**idea, "materials": [m for m in idea["materials"] if m["id"] != material["id"]]}
    body = material["body"].strip()
    cut = ""
    if len(body) > COMPRESS_INPUT:
        body = body[:COMPRESS_INPUT * 3 // 4] + "\n…(중간 생략)…\n" + body[-COMPRESS_INPUT // 4:]
        cut = f" 중 앞뒤 {COMPRESS_INPUT}자만 넣음"
    limit = min(COMPRESS_LIMIT, max(300, len(material["body"].strip()) // 5))
    return COMPRESS.format(limit=limit, context=build_context(others), title=material["title"], label=material["label"],
                           note=f" ({material['note']})" if material["note"] else "", size=len(material["body"]), cut=cut, body=body)
