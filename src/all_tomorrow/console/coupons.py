"""olmuse 크레딧 쿠폰 만들기: 공개 사이트가 쓰는 장부(Lambda strudel-credits)에 쿠폰을 넣는다.

  POST /api/coupons {code, credits, uses}  → 장부의 /api/coupon_make 응답을 그대로: 200 {code} | 400 | 409 이미 있음

rainbowloadsilsep의 tools/coupon.py와 같은 호출이다. 주소는 그 저장소 run_public.ps1의 STRUDEL_CREDITS_URL,
토큰은 ~/.all-tomorrow/strudel-credits.token. 토큰은 응답·기록에 남기지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext


class Coupon(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    credits: int = Field(ge=1, le=1_000_000)
    uses: int = Field(default=1, ge=1, le=100_000)


def ledger() -> tuple[str, str]:
    url = os.environ.get("STRUDEL_CREDITS_URL", "")
    if not url:
        repo = Path(os.environ.get("ALL_TOMORROW_OLMUSE_REPO", r"C:\projects\rainbowloadsilsep"))
        try:
            m = re.search(r"""\$env:STRUDEL_CREDITS_URL\s*=\s*["']([^"']+)["']""", (repo / "run_public.ps1").read_text(encoding="utf-8"))
            url = m.group(1) if m else ""
        except OSError:
            pass
    token = os.environ.get("STRUDEL_CREDITS_TOKEN", "")
    if not token:
        try:
            token = (Path.home() / ".all-tomorrow" / "strudel-credits.token").read_text(encoding="ascii").strip()
        except OSError:
            pass
    if not url or not token:
        raise HTTPException(503, "크레딧 장부 주소나 토큰이 없다")
    return url.rstrip("/"), token


def make(coupon: Coupon) -> tuple[int, dict[str, Any]]:
    url, token = ledger()
    body = {"email": "operator@olmuse.app", "code": coupon.code, "credits": coupon.credits, "uses": coupon.uses}
    req = urllib.request.Request(url + "/api/coupon_make", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            answer = json.loads(error.read() or b"{}")
        except ValueError:
            answer = {}
        return error.code, answer if isinstance(answer, dict) else {}
    except (OSError, ValueError) as error:
        raise HTTPException(502, f"크레딧 장부에 연결하지 못했다: {type(error).__name__}") from error


def build_router(ctx: ConsoleContext) -> APIRouter:
    router = APIRouter()

    @router.post("/api/coupons")
    def create(coupon: Coupon, _user: str = Depends(ctx.current_user)) -> JSONResponse:
        status, answer = make(coupon)
        return JSONResponse({"code": answer.get("code"), "error": answer.get("error")}, status_code=status)

    return router
