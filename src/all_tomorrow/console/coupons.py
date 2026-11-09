"""olmuse 크레딧 쿠폰 만들기: rainbowloadsilsep의 tools/coupon.py를 돌려 공개 사이트 장부에 쿠폰을 넣는다.

  POST /api/coupons {code, credits, uses}  → 200 {code} | 400 잘못된 값 | 409 이미 있음 | 503 공개 장부가 아님

장부 주소와 관리자 토큰은 그 도구가 읽는다. 콘솔은 토큰을 읽지도 남기지도 않는다.
도구가 공개 장부를 못 찾으면 로컬 장부에 만드는데, 그건 사이트에서 못 쓰는 쿠폰이라 실패로 본다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext


class Coupon(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^\w[\w-]*$")   # '-'로 시작하면 도구가 옵션으로 읽는다
    credits: int = Field(ge=1, le=1_000_000)
    uses: int = Field(default=1, ge=1, le=100_000)


def olmuse_repo() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_OLMUSE_REPO", r"C:\projects\rainbowloadsilsep"))


def make(coupon: Coupon) -> tuple[int, dict[str, str]]:
    repo = olmuse_repo()
    try:
        done = subprocess.run([sys.executable, "tools/coupon.py", coupon.code, str(coupon.credits), "--uses", str(coupon.uses)],
                              cwd=repo, capture_output=True, encoding="utf-8", errors="replace", timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 502, {"error": f"쿠폰 도구를 돌리지 못했다: {type(error).__name__}"}
    made = re.search(r"coupon (\w+): .*\b(\w+) ledger", done.stdout)
    if done.returncode == 0 and made:
        if made.group(2) != "remote":
            return 503, {"error": f"공개 장부가 아니라 {made.group(2)} 장부에 만들어졌다", "code": made.group(1)}
        return 200, {"code": made.group(1)}
    reason = (done.stderr.strip().splitlines() or ["실패"])[-1].removeprefix("not made: ")
    return (409 if reason == "exists" else 400 if done.returncode == 1 and "not made" in done.stderr else 502), {"error": reason[:300]}


def build_router(ctx: ConsoleContext) -> APIRouter:
    router = APIRouter()

    @router.post("/api/coupons")
    def create(coupon: Coupon, _user: str = Depends(ctx.current_user)) -> JSONResponse:
        status, answer = make(coupon)
        return JSONResponse(answer, status_code=status)

    return router
