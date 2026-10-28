"""봉봉봉 입금: 소유자가 상점 주문의 입금(계좌 이체·Buy Me a Coffee)을 확인하고 명예의 전당에 올린다.

  GET    /api/shop-pay                  확인한 입금과 BMC 웹후크로 들어온 확인 대기 목록
  POST   /api/shop-pay                  입금 확인. innollia.github.io의 static/shop/supporters_manual.json에 한 줄 추가 → 커밋·push
  DELETE /api/shop-pay/{order_id}       잘못 넣은 확인을 되돌린다(같은 파일에서 그 줄을 빼고 커밋·push)

상점은 정적 사이트라 공개 목록은 저장소 파일이다. 커밋은 그 저장소의 다른 변경이 섞이지 않게 supporters 두 파일만
경로를 지정해 한다. supporters.json(페이지가 읽는 것)은 tools/bmc_supporters.py와 같은 규칙으로 기존 BMC 줄 +
직접 입금 줄을 합쳐 다시 쓴다. 이메일·계좌 정보는 받지도 저장하지도 않는다. 공개 이름이 비면 "익명"이다.
웹후크 비밀은 BMC_WEBHOOK_SECRET 또는 ~/.all-tomorrow/bmc-webhook.secret. 없으면 웹후크는 503이다.
"""
from __future__ import annotations

import json
import os
import secrets
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
    order_id: str = Field(pattern=r"^[0-9A-Za-z가-힣-]{2,40}$")   # BONG-MMDD-XXXX 또는 한글 단어 주문번호
    nickname: str = Field(min_length=1, max_length=100)        # 디스코드 닉네임(주문 스레드 이름). 공개 목록에는 안 나간다.
    amount: int = Field(gt=0, le=10_000_000)                    # 원
    method: Literal["bank", "bmc"]
    public_name: str = Field(default="", max_length=40)         # 비면 익명
    note: str = Field(default="", max_length=80)
    dm_user_id: str = Field(default="", pattern=r"^([0-9]{1,32})?$")   # ss0 DM 해금 대상 디스코드 ID
    pending_id: str = Field(default="", max_length=100)         # BMC 확인 대기에서 온 것이면 그 id


class AccessAck(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    ok: bool
    state: Literal["unlocked", "revoked"] | None = None
    error: str = Field(default="", max_length=500)


def _setting(env: str, name: str) -> str:
    v = os.environ.get(env, "").strip()
    f = Path.home() / ".all-tomorrow" / name
    return v or (f.read_text(encoding="utf-8").strip() if f.exists() else "")


def bmc_base() -> str:
    """BMC 웹후크를 받아 쌓는 AWS Lambda(Function URL, ap-northeast-2 bmc-webhook). 콘솔은
    GET /internal/edge/bmc/pending으로 가져가고 POST .../ack로 지운다. 이 콘솔 전용 토큰으로만 열린다."""
    return _setting("ALL_TOMORROW_BMC_URL", "bmc-pull-url").rstrip("/")


class EveBmc:
    """AWS에 쌓인 BMC 후원 확인 대기를 가져오고, 처리한 것을 ack한다."""

    def __init__(self, base=bmc_base, token=lambda: _setting("ALL_TOMORROW_BMC_TOKEN", "bmc-pull.token"), client=None) -> None:
        self.base, self.token, self.client = base, token, client

    def call(self, method: str, path: str, **kw) -> dict[str, Any]:
        import httpx
        base, token = self.base(), self.token()
        if not base or not token:
            raise RuntimeError("BMC 대기 주소나 토큰이 설정되지 않았다")
        c = self.client or httpx.Client(timeout=8)
        r = c.request(method, base + path, headers={"Authorization": f"Bearer {token}"}, **kw)
        r.raise_for_status()
        return r.json()

    def pending(self) -> list[dict[str, Any]]:
        return [{"id": f"eve:{x['id']}", "name": str(x.get("supporter_name") or "")[:40], "amount": x.get("amount"),
                 "currency": str(x.get("currency") or ""), "note": str(x.get("note") or "")[:80], "live": True,
                 "received_at": x.get("received_at") or x.get("supported_at") or ""}
                for x in self.call("GET", "/internal/edge/bmc/pending").get("supports", [])]

    def ack(self, ids: list[str]) -> None:
        self.call("POST", "/internal/edge/bmc/ack", json={"ids": ids})


def shop_repo() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_SHOP_REPO", r"C:\projects\innollia.github.io"))


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


def build_router(ctx: ConsoleContext, repo: ShopRepo | None = None, eve: EveBmc | None = None) -> APIRouter:
    ledger = Ledger(ctx.feature_dir("shop-pay"))
    shop = repo or ShopRepo(shop_repo())
    bmc = eve or EveBmc()
    router = APIRouter()

    @router.get("/api/shop-pay")
    def listing(_: str = Depends(ctx.current_user)) -> dict[str, Any]:
        data = ledger.load()
        try:   # Eve 쪽 대기가 원본이다. 환불되면 거기서 빠지므로 매번 새로 받아 바꿔 끼운다.
            fresh = bmc.pending()
            data["pending"] = [x for x in data["pending"] if not x["id"].startswith("eve:")] + fresh
            ledger.save(data)
            data["eve_error"] = ""
        except Exception as e:  # noqa: BLE001 - 못 받으면 마지막으로 받은 목록을 보여 준다
            data["eve_error"] = str(e)[:200]
        return data

    def take_pending(data: dict[str, Any], pending_id: str) -> None:
        if pending_id.startswith("eve:"):
            bmc.ack([pending_id[4:]])
        data["pending"] = [x for x in data["pending"] if x["id"] != pending_id]

    @router.delete("/api/shop-pay/pending/{pending_id}")
    def dismiss(pending_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        data = ledger.load()
        take_pending(data, pending_id)
        ledger.save(data)
        return {"ok": True}

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
        if p.pending_id:
            try:
                take_pending(data, p.pending_id)
            except Exception:  # noqa: BLE001 - 공개 기록은 이미 올라갔다. ack는 다음에 '대기에서 빼기'로 다시 한다.
                pass
        if p.dm_user_id:
            add_request(data, p.dm_user_id, "unlock", p.order_id)
        ledger.save(data)
        return {"commit": commit, "row": row}

    def add_request(data: dict[str, Any], user_id: str, action: str, order_id: str) -> dict[str, Any]:
        req = {"request_id": secrets.token_hex(8), "user_id": user_id, "action": action, "order_id": order_id,
               "requested_at": datetime.now(UTC).isoformat(timespec="seconds"), "done": False}
        data.setdefault("access", []).append(req)
        return req

    @router.post("/api/shop-pay/{order_id}/dm/{action}")
    def dm(order_id: str, action: Literal["unlock", "revoke"], _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        data = ledger.load()
        found = next((x for x in data["paid"] if x["order_id"] == order_id), None)
        if found is None or not found.get("dm_user_id"):
            raise HTTPException(404, "해금 대상이 있는 확인 기록 없음")
        req = add_request(data, found["dm_user_id"], action, order_id)
        ledger.save(data)
        return req

    # Eve가 15초마다 가져간다(엣지 토큰). 처리 결과는 ack로, 상태는 /internal/edge/eve/unlocked-dm의 access로도 온다.
    def edge(request: Request) -> None:
        if ctx.verify_edge is None:
            raise HTTPException(503, "edge authentication not configured")
        ctx.verify_edge(request.headers.get("authorization"))

    @router.get("/internal/edge/eve/access-requests")
    def access_requests(request: Request) -> dict[str, Any]:
        edge(request)
        keep = ("request_id", "user_id", "action", "order_id", "requested_at")
        return {"requests": [{k: r[k] for k in keep} for r in ledger.load().get("access", []) if not r["done"]]}

    @router.post("/internal/edge/eve/access-requests/ack")
    def access_ack(ack: AccessAck, request: Request) -> dict[str, Any]:
        edge(request)
        data = ledger.load()
        req = next((r for r in data.get("access", []) if r["request_id"] == ack.request_id), None)
        if req is None:
            raise HTTPException(404, "no such request")
        if not req["done"]:
            req.update(done=True, ok=ack.ok, state=ack.state, error=ack.error,
                       acked_at=datetime.now(UTC).isoformat(timespec="seconds"))
            ledger.save(data)
        return {"ok": True}

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


    return router
