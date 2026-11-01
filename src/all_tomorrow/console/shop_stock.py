"""봉봉봉 재고·가격: 상점의 일시품절·시급·AI 사용료·할인율·고정가를 고친다.

  GET  /api/shop-stock    지금 값(innollia.github.io static/shop/stock.js)과 상품 이름
  PUT  /api/shop-stock    값을 바꿔 stock.js에 쓰고, index.html의 stock.js?v=N을 1 올려 두 파일만 커밋·push

stock.js는 위가 주석, 아래가 `window.STOCK = { ... };` 한 덩어리다. 그 JSON만 다시 쓰고 주석은 그대로 둔다.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext
from all_tomorrow.console.shop_pay import ShopRepo, shop_repo

STOCK = "static/shop/stock.js"
INDEX = "static/shop/index.html"
DIALOGUE = "static/shop/dialogue.js"
GOODS = ("game", "web", "bot", "read", "song", "oracle", "research", "xpost", "dm", "ss0feat", "partner")
FIXED = ("song", "research", "xpost", "dm")
BLOCK = re.compile(r"window\.STOCK\s*=\s*(\{.*\})\s*;", re.S)
VERSION = re.compile(r"stock\.js\?v=(\d+)")


class Stock(BaseModel):
    labor: int = Field(ge=0, le=10_000_000)
    aiHour: int = Field(ge=0, le=10_000_000)
    aiSale: int = Field(ge=0, le=100)
    aiItems: list[str]
    soldOut: list[str]
    price: dict[str, int]


def names(text: str) -> dict[str, str]:
    found = dict(re.findall(r"^\s+(\w+): \{ name: '([^']*)'", text, re.M))
    return {g: found.get(g, g) for g in GOODS}


def read(shop: ShopRepo) -> tuple[str, dict[str, Any]]:
    text = (shop.root / STOCK).read_text(encoding="utf-8")
    m = BLOCK.search(text)
    if not m:
        raise HTTPException(500, "stock.js에서 window.STOCK 덩어리를 못 찾았다")
    return text, json.loads(m.group(1))


def build_router(ctx: ConsoleContext, repo: ShopRepo | None = None) -> APIRouter:
    shop = repo or ShopRepo(shop_repo())
    router = APIRouter()

    @router.get("/api/shop-stock")
    def current(_: str = Depends(ctx.current_user)) -> dict[str, Any]:
        _, stock = read(shop)
        d = shop.root / DIALOGUE
        return {"stock": stock, "names": names(d.read_text(encoding="utf-8") if d.exists() else ""), "fixed": list(FIXED)}

    @router.put("/api/shop-stock")
    def save(s: Stock, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        bad = [g for g in [*s.aiItems, *s.soldOut] if g not in GOODS] + [g for g in s.price if g not in FIXED]
        if bad or any(v < 0 for v in s.price.values()):
            raise HTTPException(422, f"모르는 상품 id: {', '.join(bad)}" if bad else "가격은 0원 이상")
        with shop.lock:
            text, old = read(shop)
            new = {**old, **s.model_dump(), "price": {**old.get("price", {}), **s.price}}
            if new == old:
                return {"commit": "", "unchanged": True}
            body = "{\n" + ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in new.items()) + "\n}"
            m = BLOCK.search(text)
            (shop.root / STOCK).write_text(text[:m.start(1)] + body + text[m.end(1):], encoding="utf-8", newline="\n")
            index = (shop.root / INDEX).read_text(encoding="utf-8")
            v = VERSION.search(index)
            if not v:
                raise HTTPException(500, "index.html에서 stock.js?v=N을 못 찾았다")
            (shop.root / INDEX).write_text(index[:v.start(1)] + str(int(v.group(1)) + 1) + index[v.end(1):], encoding="utf-8", newline="\n")
            shop.git("add", "--", STOCK, INDEX)
            shop.git("commit", "-m", "상점: 재고·가격 바꿈", "--", STOCK, INDEX)
            shop.git("push", "origin", "HEAD:main")
            return {"commit": shop.git("rev-parse", "--short", "HEAD").strip(), "stock": new}

    return router
