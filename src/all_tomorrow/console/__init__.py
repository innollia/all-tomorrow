"""Console features: optional routers mounted next to the core control-plane API.

Each module in this package that defines `build_router(ctx: ConsoleContext) -> APIRouter`
is mounted by `web.create_app`. Features keep their own state under `ctx.data_dir`
and must not edit `web.py`; the matching UI lives in static/console/pages/<feature>.js.

The server is a small single node, so features do no heavy work per request:
collectors on the user's PCs push precomputed snapshots (`ctx.verify_collector`),
and the server only stores and serves them.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, status

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ConsoleContext:
    current_user: Callable[..., str]   # FastAPI dependency: returns the logged-in user or raises 401
    data_dir: Path                      # per-feature state lives in data_dir/<feature>
    collector_token: str | None = None  # bearer token the PC-side collectors push with

    def feature_dir(self, name: str) -> Path:
        path = self.data_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def verify_collector(self, authorization: str | None) -> None:
        if not self.collector_token:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "collector ingest not configured")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "collector authentication required")
        expected = hashlib.sha256(self.collector_token.encode()).digest()
        if not hmac.compare_digest(hashlib.sha256(authorization[7:].encode()).digest(), expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid collector credential")


def include_features(app: FastAPI, ctx: ConsoleContext) -> list[str]:
    mounted = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        build = getattr(module, "build_router", None)
        if build is None:
            continue
        app.include_router(build(ctx))
        mounted.append(info.name)
    log.info("console features mounted: %s", mounted)
    return mounted
