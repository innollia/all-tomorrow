"""User profile from Notion, split into access levels and scopes for staff.

Only business-relevant sources are listed in config (`profile_sources`). Diaries,
health/medication, sexual/gender, self-harm and relationship records are never
configured, so no staff level can reach them. A staff member sees a source when
source.level <= member.access_level and source.scope is in member.access_scopes.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

import httpx

NOTION_VERSION = "2025-09-03"
MAX_CHARS = 1500
# Second guard: even inside an allowed section, lines touching these never leave.
# Matching runs on normalised text (NFKC, lowercase, letters/digits only, no zero-width chars).
SENSITIVE = (
    # mental health / self-harm
    "자해", "자살", "죽음", "죽고", "우울", "조울", "양극성", "공황", "불안장애", "트라우마", "섭식", "폭식", "거식",
    "정신", "심리상담", "상담센터", "상담치료", "adhd", "depress", "bipolar", "suicid", "selfharm", "anxiety", "therap",
    # medical / medication
    "복약", "복용", "약을", "약값", "약국", "약물", "상비약", "처방", "진료", "진단", "병원", "치료", "증상", "진통제",
    "벤조", "수면제", "리튬", "호르몬", "hrt", "medic", "pharm", "clinic", "diagnos",
    # sexual / gender / body
    "성적", "성욕", "성관계", "섹스", "젠더", "트랜스", "여성으로", "남성으로", "생리", "체모", "성기", "브라", "sex", "gender",
    "trans", "lgbt",
    # relationships / identity
    "연애", "애인", "연인", "이별", "데이팅", "틴더", "dating", "tinder", "실명",
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


def _normalise(text: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).lower())


def _safe(text: str) -> bool:
    flat = _normalise(text)
    return not any(word in flat for word in SENSITIVE)


def _headers() -> dict[str, str]:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("NOTION_TOKEN is not set")
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}


def _text(prop: dict[str, Any]) -> str:
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in value or [])
    if kind == "select":
        return (value or {}).get("name", "")
    if kind == "multi_select":
        return ", ".join(x["name"] for x in value or [])
    if kind == "number":
        return "" if value is None else f"{value:g}"
    if kind == "checkbox":
        return "예" if value else "아니오"
    if kind == "date":
        return (value or {}).get("start", "")
    return ""


def _query(data_source: str) -> list[dict[str, Any]]:
    rows, cursor = [], None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = httpx.post(f"https://api.notion.com/v1/data_sources/{data_source}/query",
                              headers=_headers(), json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
        rows.extend(data["results"])
        if not data.get("has_more"):
            return rows
        cursor = data["next_cursor"]


def _rows_digest(source: dict[str, Any]) -> str:
    fields = source["fields"]
    lines: list[str] = []
    summary: dict[str, float] = {}
    for row in _query(source["data_source"]):
        props = row["properties"]
        if source.get("only_checked") and _text(props.get(source["only_checked"], {})) != "예":
            continue
        if any(_text(props.get(field, {})) not in allowed for field, allowed in source.get("only_values", {}).items()):
            continue
        values = [f"{f}={_text(props[f])}" for f in fields if f in props and _text(props[f])]
        line = "- " + "; ".join(values)
        if values and _safe(line):
            lines.append(line)
            totals = source.get("monthly_totals")
            if totals and _text(props.get(totals["period"], {})) == "월":
                # Only listed categories count; others (e.g. a hand-written net row) would double count.
                category = _text(props.get(totals["kind"], {}))
                kind = "income" if category in totals["income"] else "spend" if category in totals["spend"] else None
                if kind:
                    summary[kind] = summary.get(kind, 0) + (props.get(totals["amount"], {}).get("number") or 0)
    if source.get("monthly_totals") and lines:
        # Models misread raw rows as totals (a live run quoted three different deficits), so state them.
        income, spend = summary.get("income", 0), summary.get("spend", 0)
        lines.insert(0, f"[월 합계] 수입 {income:,.0f}원, 반복 지출 {spend:,.0f}원, 차액 {income - spend:+,.0f}원 "
                        "(일회성 항목 제외)")
    return "\n".join(lines)


def _workload_digest(source: dict[str, Any]) -> str:
    """Counts only: how loaded the user is, without exposing task contents."""
    today = date.today()
    soon = (today + timedelta(days=14)).isoformat()
    open_rows = [r for r in _query(source["data_source"])
                 if _text(r["properties"].get("상태", {})) not in ("완료", "취소", "보류")]
    due_soon = [r for r in open_rows if today.isoformat() <= _text(r["properties"].get("마감", {})) <= soon]
    return f"- 진행 중인 할 일 {len(open_rows)}개, 이 중 14일 안에 마감 {len(due_soon)}개"


def _blocks(block_id: str) -> list[dict[str, Any]]:
    blocks, cursor = [], None
    while True:
        response = httpx.get(f"https://api.notion.com/v1/blocks/{block_id}/children", headers=_headers(),
                             params={"page_size": 100, **({"start_cursor": cursor} if cursor else {})}, timeout=30)
        response.raise_for_status()
        data = response.json()
        blocks.extend(data["results"])
        if not data.get("has_more"):
            return blocks
        cursor = data["next_cursor"]


def _sections_digest(source: dict[str, Any]) -> str:
    """Text under the listed headings of a page (other sections are skipped)."""
    wanted = set(source["sections"])
    lines, current = [], None
    for block in _blocks(source["page"]):
        kind = block["type"]
        text = "".join(x.get("plain_text", "") for x in block.get(kind, {}).get("rich_text", []))
        if kind.startswith("heading"):
            current = text if text in wanted else None
            if current:
                lines.append(f"[{current}]")
        elif current and text and _safe(text):
            lines.append("- " + text)
    return "\n".join(lines)


def _deadlines_digest(source: dict[str, Any]) -> str:
    """Open tasks due within `days`, limited to the listed areas (title, area, due date)."""
    today = date.today()
    until = (today + timedelta(days=source.get("days", 14))).isoformat()
    areas = set(source.get("areas", []))
    lines = []
    for row in _query(source["data_source"]):
        props = row["properties"]
        due = _text(props.get("마감", {}))
        if (_text(props.get("상태", {})) in ("완료", "취소", "보류") or not due
                or not today.isoformat() <= due <= until or _text(props.get("영역", {})) not in areas):
            continue
        line = f"- {due} [{_text(props.get('영역', {}))}] {_text(props.get('할일', {}))}"
        if _safe(line):
            lines.append(line)
    return "\n".join(sorted(lines))


DIGESTERS = {"rows": _rows_digest, "workload": _workload_digest, "sections": _sections_digest,
             "deadlines": _deadlines_digest}


def validate(sources: list[dict[str, Any]], staff: list[dict[str, Any]]) -> None:
    """Fail at launch, not mid-topic: a typo here would silently widen or break access."""
    for source in sources:
        if source.get("kind") not in DIGESTERS or not isinstance(source.get("name"), str):
            raise ValueError(f"profile source needs a name and kind in {sorted(DIGESTERS)}: {source}")
        if not isinstance(source.get("level"), int) or not 1 <= source["level"] <= 3:
            raise ValueError(f"profile source level must be 1..3: {source['name']}")
        if not isinstance(source.get("scope"), str):
            raise ValueError(f"profile source scope must be a string: {source['name']}")
    for member in staff:
        level, scopes = member.get("access_level", 0), member.get("access_scopes", [])
        if not isinstance(level, int) or not 0 <= level <= 3:
            raise ValueError(f"staff access_level must be 0..3: {member.get('role')}")
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            # a YAML string would make `scope in scopes` a substring match
            raise ValueError(f"staff access_scopes must be a list of strings: {member.get('role')}")


def fetch_profile(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{source name: {level, scope, text}}. A failed source becomes empty text, never an error."""
    profile = {}
    for source in sources:
        try:
            text = DIGESTERS[source["kind"]](source)[:MAX_CHARS]
        except Exception as error:  # noqa: BLE001 - staff just get less context
            text = ""
            source = {**source, "error": type(error).__name__}
        profile[source["name"]] = {"level": source["level"], "scope": source["scope"], "text": text,
                                   **({"error": source["error"]} if "error" in source else {})}
    return profile


def visible(profile: dict[str, dict[str, Any]], level: int, scopes: list[str]) -> dict[str, str]:
    return {name: item["text"] for name, item in profile.items()
            if item["text"] and item["level"] <= level and item["scope"] in scopes}


def context_block(profile: dict[str, dict[str, Any]], member: dict[str, Any]) -> str:
    items = visible(profile, member["access_level"], member["access_scopes"])
    if not items:
        return ""
    body = "\n".join(f"<{name}>\n{text}" for name, text in items.items())
    return ("\n\n[의뢰인 정보 — 네 권한 범위에서만 제공됨. 이 아이디어를 실행할 사람이 이 의뢰인이다. "
            "판단의 척도로 쓰되 그대로 옮겨 적지 않는다]\n" + body)
