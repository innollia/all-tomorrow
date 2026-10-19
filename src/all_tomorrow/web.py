from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from all_tomorrow.contracts import Project
from all_tomorrow.edge import EdgeAnalysis, load_edge_policy


SESSION_COOKIE = "all_tomorrow_session"


@dataclass(slots=True)
class WebState:
    projects: dict[str, Project] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    usage_path: Path | None = None
    project_snapshot: dict[str, Any] | None = None
    project_snapshot_path: Path | None = None
    # Encoded once per push, so repeated reads cost no JSON work and can answer 304.
    project_snapshot_body: bytes | None = None
    project_snapshot_etag: str | None = None

    def __post_init__(self) -> None:
        if self.usage is None and self.usage_path and self.usage_path.exists():
            self.usage = json.loads(self.usage_path.read_text(encoding="utf-8"))
        if self.project_snapshot is None and self.project_snapshot_path and self.project_snapshot_path.exists():
            self.project_snapshot = json.loads(self.project_snapshot_path.read_text(encoding="utf-8"))
        if self.project_snapshot is not None:
            self._encode_project_snapshot()

    def _encode_project_snapshot(self) -> None:
        self.project_snapshot_body = json.dumps(self.project_snapshot, ensure_ascii=False).encode()
        self.project_snapshot_etag = '"' + hashlib.sha256(self.project_snapshot_body).hexdigest()[:16] + '"'

    def store_project_snapshot(self, snapshot: dict[str, Any]) -> None:
        # Collected on the user's PC; the server only keeps the latest copy.
        self.project_snapshot = snapshot
        self._encode_project_snapshot()
        if self.project_snapshot_path:
            self.project_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.project_snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    def store_usage(self, snapshot: dict[str, Any]) -> None:
        self.usage = snapshot
        if self.usage_path:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            self.usage_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")


class UsageWindow(BaseModel):
    label: str = Field(max_length=64)
    percent: float = Field(ge=0, le=1000)
    resets_at: str | None = Field(default=None, max_length=64)


class UsageProvider(BaseModel):
    id: str = Field(max_length=32)
    name: str = Field(max_length=64)
    plan: str | None = Field(default=None, max_length=64)
    status: str = Field(max_length=32)
    observed_at: str | None = Field(default=None, max_length=64)
    windows: list[UsageWindow] = Field(default_factory=list, max_length=10)


class UsageSnapshot(BaseModel):
    collected_at: str = Field(max_length=64)
    providers: list[UsageProvider] = Field(max_length=10)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class EdgeDecisionRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=128)
    needs_shared_memory: bool = False
    needs_project_state: bool = False
    needs_cross_project_knowledge: bool = False
    needs_remote_tool: bool = False
    needs_long_running_task: bool = False
    needs_canonical_mutation: bool = False
    tool_risk: str | None = None


class Auth:
    def __init__(
        self,
        username: str,
        password: str,
        secret: str,
        ttl_seconds: int = 86_400,
        edge_token: str | None = None,
        usage_token: str | None = None,
    ) -> None:
        if not username or not password or len(secret) < 32:
            raise ValueError("web auth requires username, password, and a session secret of at least 32 characters")
        self.username = username
        self._password_digest = hashlib.sha256(password.encode()).digest()
        self._secret = secret.encode()
        self.ttl_seconds = ttl_seconds
        self._edge_token_digest = hashlib.sha256(edge_token.encode()).digest() if edge_token else None
        self._usage_token_digest = hashlib.sha256(usage_token.encode()).digest() if usage_token else None

    def verify_password(self, username: str, password: str) -> bool:
        candidate = hashlib.sha256(password.encode()).digest()
        return hmac.compare_digest(username, self.username) and hmac.compare_digest(candidate, self._password_digest)

    def issue(self) -> str:
        payload = json.dumps({"sub": self.username, "exp": int(time.time()) + self.ttl_seconds}, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify(self, token: str | None) -> str:
        if not token or "." not in token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session") from error
        if payload.get("sub") != self.username or int(payload.get("exp", 0)) <= int(time.time()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expired session")
        return self.username

    def verify_edge_token(self, authorization: str | None) -> None:
        if self._edge_token_digest is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="edge authentication not configured")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="edge authentication required")
        candidate = hashlib.sha256(authorization[7:].encode()).digest()
        if not hmac.compare_digest(candidate, self._edge_token_digest):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid edge credential")

    def verify_usage_token(self, authorization: str | None) -> None:
        if self._usage_token_digest is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="usage ingest not configured")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="usage authentication required")
        candidate = hashlib.sha256(authorization[7:].encode()).digest()
        if not hmac.compare_digest(candidate, self._usage_token_digest):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid usage credential")


def _login_page() -> str:
    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow Login</title><style>
body{font:16px system-ui;background:#10131a;color:#e8ecf3;display:grid;place-items:center;height:100vh;margin:0}
form{display:grid;gap:12px;width:min(360px,85vw);padding:28px;background:#1a2030;border-radius:16px}
input,button{font:inherit;padding:12px;border-radius:8px;border:1px solid #39435a;background:#111623;color:inherit}
button{background:#6d5dfc;border:0;font-weight:700;cursor:pointer}#error{color:#ff9a9a;min-height:1.2em}
</style></head><body><form id="login"><h1>All Tomorrow</h1><input id="username" autocomplete="username" placeholder="사용자명">
<input id="password" type="password" autocomplete="current-password" placeholder="비밀번호"><button>로그인</button><div id="error"></div></form>
<script>login.onsubmit=async(e)=>{e.preventDefault();const r=await fetch('/api/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:username.value,password:password.value})});if(r.ok)location='/';else error.textContent='로그인 실패';}</script></body></html>"""


STATIC_DIR = Path(__file__).parent / "static"
MAX_PROJECT_SNAPSHOT_BYTES = 1_000_000


def _dashboard(username: str) -> str:
    return (STATIC_DIR / "console.html").read_text(encoding="utf-8").replace("__USER__", escape(username))


def create_app(
    *,
    auth: Auth,
    web_state: WebState | None = None,
    policy_path: str = "edge/discord/default.yaml",
    factory: Any = None,
    lifespan: Any = None,
) -> FastAPI:
    app = FastAPI(title="All Tomorrow Control Plane", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    state_store = web_state or WebState()
    policy = load_edge_policy(policy_path)

    def current_user(all_tomorrow_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> str:
        return auth.verify(all_tomorrow_session)

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "all-tomorrow", "version": app.version}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page() -> str:
        return _login_page()

    @app.post("/api/login", status_code=204)
    async def login(payload: LoginRequest, response: Response) -> None:
        if not auth.verify_password(payload.username, payload.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
        response.set_cookie(
            SESSION_COOKIE,
            auth.issue(),
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=auth.ttl_seconds,
        )

    @app.post("/api/logout", status_code=204)
    async def logout(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(user: str = Depends(current_user)) -> str:
        return _dashboard(user)

    @app.get("/api/projects")
    async def projects(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return [asdict(project) for project in state_store.projects.values()]

    @app.get("/api/runs")
    async def runs(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.runs)

    @app.get("/api/questions")
    async def questions(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.questions)

    @app.get("/api/usage")
    async def usage(_: str = Depends(current_user)) -> dict[str, Any] | None:
        return state_store.usage

    @app.post("/internal/usage", status_code=204)
    async def ingest_usage(payload: UsageSnapshot, request: Request) -> None:
        auth.verify_usage_token(request.headers.get("authorization"))
        state_store.store_usage(payload.model_dump())

    @app.get("/api/project-snapshot")
    async def project_snapshot(request: Request, _: str = Depends(current_user)) -> Response:
        if state_store.project_snapshot_body is None:
            return Response("null", media_type="application/json")
        headers = {"ETag": state_store.project_snapshot_etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == state_store.project_snapshot_etag:
            return Response(status_code=304, headers=headers)
        return Response(state_store.project_snapshot_body, media_type="application/json", headers=headers)

    @app.post("/internal/projects", status_code=204)
    async def ingest_projects(request: Request) -> None:
        # Same collector credential as usage. Size-capped: the server is small.
        auth.verify_usage_token(request.headers.get("authorization"))
        body = await request.body()
        if len(body) > MAX_PROJECT_SNAPSHOT_BYTES:
            raise HTTPException(status_code=413, detail="snapshot too large")
        snapshot = json.loads(body)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("projects"), list):
            raise HTTPException(status_code=422, detail="snapshot must have a projects list")
        state_store.store_project_snapshot(snapshot)

    @app.post("/api/edge/discord/decide")
    async def decide(payload: EdgeDecisionRequest, _: str = Depends(current_user)) -> dict[str, Any]:
        decision = policy.decide(EdgeAnalysis(**payload.model_dump()))
        return {
            "policy_id": policy.policy_id,
            "action": decision.action.value,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
        }

    @app.post("/internal/edge/discord/decide")
    async def internal_decide(payload: EdgeDecisionRequest, request: Request) -> dict[str, Any]:
        auth.verify_edge_token(request.headers.get("authorization"))
        decision = policy.decide(EdgeAnalysis(**payload.model_dump()))
        return {
            "policy_id": policy.policy_id,
            "action": decision.action.value,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
        }

    if factory is not None:
        from all_tomorrow.idea_factory.web_routes import build_router

        app.include_router(build_router(factory, current_user))

    return app


def _factory_from_environment() -> tuple[Any, Any]:
    """Idea factory runtime when IDEA_FACTORY_ENABLED=1; DBOS launches with the web process."""
    if os.environ.get("IDEA_FACTORY_ENABLED") != "1":
        return None, None
    from contextlib import asynccontextmanager

    from all_tomorrow.idea_factory import pipeline
    from all_tomorrow.idea_factory.config import REPO_ROOT, load_roster
    from all_tomorrow.idea_factory.store import Store
    from all_tomorrow.idea_factory.web_routes import FactoryRuntime

    store = Store(os.environ.get("IDEA_FACTORY_STORE", REPO_ROOT / ".artifacts" / "idea-factory.sqlite"))
    runtime = FactoryRuntime(store=store, roster=load_roster(),
                             start_topic=lambda text, actor: pipeline.start_topic(text, actor),
                             kill_all=lambda actor: pipeline.kill_all(actor))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        from dbos import DBOS

        pipeline.launch(store, roster_obj=runtime.roster)
        yield
        DBOS.destroy()

    return runtime, lifespan


def app_from_environment() -> FastAPI:
    username = os.environ.get("ALL_TOMORROW_ADMIN_USER", "")
    password = os.environ.get("ALL_TOMORROW_ADMIN_PASSWORD", "")
    secret = os.environ.get("ALL_TOMORROW_SESSION_SECRET", "")
    edge_token = os.environ.get("ALL_TOMORROW_EDGE_TOKEN")
    usage_token = os.environ.get("ALL_TOMORROW_USAGE_TOKEN")
    usage_path = Path(os.environ.get("ALL_TOMORROW_USAGE_PATH", ".artifacts/usage.json"))
    snapshot_path = Path(os.environ.get("ALL_TOMORROW_PROJECTS_PATH", ".artifacts/projects-snapshot.json"))
    factory, lifespan = _factory_from_environment()
    return create_app(
        auth=Auth(username, password, secret, edge_token=edge_token, usage_token=usage_token),
        web_state=WebState(usage_path=usage_path, project_snapshot_path=snapshot_path),
        factory=factory,
        lifespan=lifespan,
    )


def run() -> None:
    import uvicorn

    uvicorn.run(
        app_from_environment(),
        host=os.environ.get("ALL_TOMORROW_HOST", "127.0.0.1"),
        port=int(os.environ.get("ALL_TOMORROW_PORT", "8080")),
    )
