"""봉봉봉 입금: 소유자가 상점 주문의 입금(계좌 이체·Buy Me a Coffee)을 확인하고 명예의 전당에 올린다.

  GET    /api/shop-pay                  확인한 입금과 BMC 웹후크로 들어온 확인 대기 목록
  POST   /api/shop-pay                  입금 확인. innollia.github.io의 static/shop/supporters_manual.json에 한 줄 추가 → 커밋·push
  DELETE /api/shop-pay/{order_id}       잘못 넣은 확인을 되돌린다(같은 파일에서 그 줄을 빼고 커밋·push)
  POST   /internal/bmc/webhook          BMC 웹후크. x-signature-sha256(본문의 HMAC-SHA256, 16진수)을 검증하고 확인 대기에만 넣는다.

상점은 정적 사이트라 공개 목록은 저장소 파일이다. 커밋은 그 저장소의 다른 변경이 섞이지 않게 supporters 두 파일만
경로를 지정해 한다. supporters.json(페이지가 읽는 것)은 tools/bmc_supporters.py와 같은 규칙으로 기존 BMC 줄 +
직접 입금 줄을 합쳐 다시 쓴다. 이메일·계좌 정보는 받지도 저장하지도 않는다. 공개 이름이 비면 "익명"이다.
웹후크 비밀은 BMC_WEBHOOK_SECRET 또는 ~/.all-tomorrow/bmc-webhook.secret. 없으면 웹후크는 503이다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext

KST = timezone(timedelta(hours=9))
MANUAL = "static/shop/supporters_manual.json"
PUBLIC = "static/shop/supporters.json"


class Payment(BaseModel):
    order_id: str = Field(pattern=r"^BONG-\d{4}-[A-Z0-9]{4}$")
    nickname: str = Field(min_length=1, max_length=100)        # 디스코드 닉네임(주문 스레드 이름). 공개 목록에는 안 나간다.
    amount: int = Field(gt=0, le=10_000_000)                    # 원
    method: Literal["bank", "bmc"]
    public_name: str = Field(default="", max_length=40)         # 비면 익명
    note: str = Field(default="", max_length=80)
    dm_user_id: str = Field(default="", pattern=r"^([0-9]{1,32})?$")   # ss0 DM 해금 대상 디스코드 ID
    pending_id: str = Field(default="", max_length=100)         # BMC 확인 대기에서 온 것이면 그 id


def shop_repo() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_SHOP_REPO", r"C:\projects\innollia.github.io"))


def webhook_secret() -> str:
    env = os.environ.get("BMC_WEBHOOK_SECRET", "").strip()
    if env:
        return env
    f = Path.home() / ".all-tomorrow" / "bmc-webhook.secret"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature:
        return False
    want = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, signature.strip().lower())


class ShopRepo:
    """supporters 파일 두 개만 고치고 그 두 경로만 커밋·push한다."""

    def __init__(self, root: Path, run=subprocess.run) -> None:
        self.root, self.run, self.lock = root, run, threading.Lock()

    def git(self, *args: str) -> str:
        p = self.run(["git", *args], cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=120)
        if p.returncode:
            raise HTTPException(502, f"git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}")
        return p.stdout

    def read(self, rel: str) -> list[dict[str, Any]]:
        f = self.root / rel
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []

    def write(self, rel: str, rows: list[dict[str, Any]]) -> None:
        (self.root / rel).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    def change(self, edit, message: str) -> str:
        with self.lock:
            manual = edit(self.read(MANUAL))
            self.write(MANUAL, manual)
            # tools/bmc_supporters.py와 같은 합치기: BMC 줄은 두고 직접 입금 줄만 새것으로
            bmc = [r for r in self.read(PUBLIC) if r.get("source") == "bmc" and r not in manual]
            self.write(PUBLIC, sorted(manual + bmc, key=lambda r: r.get("date", ""), reverse=True))
            self.git("add", "--", MANUAL, PUBLIC)
            self.git("commit", "-m", message, "--", MANUAL, PUBLIC)
            self.git("push", "origin", "HEAD:main")
            return self.git("rev-parse", "--short", "HEAD").strip()


class Ledger:
    """콘솔만 보는 내부 기록(주문번호·닉네임·수단·해금 대상). 공개 저장소에는 안 올라간다."""

    def __init__(self, base: Path) -> None:
        self.path = base / "ledger.json"

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"paid": [], "pending": []}

    def save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def pending_from_bmc(event: dict[str, Any]) -> dict[str, Any] | None:
    """BMC 웹후크 본문에서 확인 대기 한 줄을 뽑는다. 이메일 등은 버린다."""
    data = event.get("data") or {}
    if not str(event.get("type", "")).startswith(("donation.", "coffee.")) or "refund" in str(event.get("type")):
        return None
    amount = data.get("amount") or data.get("total_amount_charged") or 0
    return {
        "id": f"bmc-{data.get('id') or data.get('support_id') or hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]}",
        "name": str(data.get("supporter_name") or "")[:40],
        "amount": amount, "currency": str(data.get("currency") or "USD"),
        "note": str(data.get("support_note") or data.get("message") or "")[:80],
        "live": bool(event.get("live_mode", True)),
        "received_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def build_router(ctx: ConsoleContext, repo: ShopRepo | None = None) -> APIRouter:
    ledger = Ledger(ctx.feature_dir("shop-pay"))
    shop = repo or ShopRepo(shop_repo())
    router = APIRouter()

    @router.get("/api/shop-pay")
    async def listing(_: str = Depends(ctx.current_user)) -> dict[str, Any]:
        return ledger.load()

    @router.post("/api/shop-pay")
    def confirm(p: Payment, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        data = ledger.load()
        if any(x["order_id"] == p.order_id for x in data["paid"]):
            raise HTTPException(409, "이미 확인한 주문")
        row = {"name": p.public_name.strip() or "익명", "amount": p.amount, "currency": "KRW", "note": p.note.strip(),
               "date": datetime.now(KST).date().isoformat(), "source": p.method}
        commit = shop.change(lambda rows: [*rows, row], f"상점: 입금 확인 {p.order_id}")
        data["paid"].append({**p.model_dump(exclude={"pending_id"}), "row": row, "commit": commit,
                             "at": datetime.now(UTC).isoformat(timespec="seconds")})
        data["pending"] = [x for x in data["pending"] if x["id"] != p.pending_id]
        ledger.save(data)
        return {"commit": commit, "row": row}

    @router.delete("/api/shop-pay/{order_id}")
    def undo(order_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        data = ledger.load()
        found = next((x for x in data["paid"] if x["order_id"] == order_id), None)
        if found is None:
            raise HTTPException(404, "확인 기록 없음")

        def drop(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            i = next((i for i, r in enumerate(rows) if r == found["row"]), None)
            return rows if i is None else rows[:i] + rows[i + 1:]
        commit = shop.change(drop, f"상점: 입금 확인 취소 {order_id}")
        data["paid"] = [x for x in data["paid"] if x["order_id"] != order_id]
        ledger.save(data)
        return {"commit": commit}

    @router.post("/internal/bmc/webhook")
    async def bmc_webhook(request: Request) -> dict[str, Any]:
        secret = webhook_secret()
        if not secret:
            raise HTTPException(503, "BMC webhook secret not configured")
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(413, "too large")
        if not verify_signature(secret, body, request.headers.get("x-signature-sha256")):
            raise HTTPException(401, "bad signature")
        try:
            item = pending_from_bmc(json.loads(body))
        except (ValueError, AttributeError):
            raise HTTPException(422, "bad payload") from None
        if item is None:
            return {"ok": True, "queued": False}
        data = ledger.load()
        if not any(x["id"] == item["id"] for x in data["pending"]):
            data["pending"].append(item)
            ledger.save(data)
        return {"ok": True, "queued": True}

    return router
