from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass, field
from html import escape
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from all_tomorrow.contracts import Project
from all_tomorrow.edge import EdgeAnalysis, load_edge_policy


SESSION_COOKIE = "all_tomorrow_session"


@dataclass(slots=True)
class WebState:
    projects: dict[str, Project] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)


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
    ) -> None:
        if not username or not password or len(secret) < 32:
            raise ValueError("web auth requires username, password, and a session secret of at least 32 characters")
        self.username = username
        self._password_digest = hashlib.sha256(password.encode()).digest()
        self._secret = secret.encode()
        self.ttl_seconds = ttl_seconds
        self._edge_token_digest = hashlib.sha256(edge_token.encode()).digest() if edge_token else None

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


def _login_page() -> str:
    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow</title><style>
body{font:15px system-ui,sans-serif;background:#fafafa;color:#111;display:grid;place-items:center;height:100vh;margin:0}
form{display:grid;gap:10px;width:min(300px,85vw)}h1{font-size:18px;font-weight:600;margin:0 0 8px}
input,button{font:inherit;padding:10px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#111}
input:focus{outline:2px solid #111;outline-offset:-1px}button{background:#111;color:#fff;border-color:#111;cursor:pointer}
#error{color:#b00;font-size:13px;min-height:1.2em}
</style></head><body><form id="login"><h1>All Tomorrow</h1><input id="username" autocomplete="username" placeholder="사용자명">
<input id="password" type="password" autocomplete="current-password" placeholder="비밀번호"><button>로그인</button><div id="error"></div></form>
<script>login.onsubmit=async(e)=>{e.preventDefault();const r=await fetch('/api/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:username.value,password:password.value})});if(r.ok)location='/';else error.textContent='로그인 실패';}</script></body></html>"""


def _dashboard(username: str) -> str:
    safe_user = escape(username)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow</title><style>
body{{font:15px system-ui,sans-serif;margin:0 auto;max-width:720px;padding:24px;background:#fafafa;color:#111}}
header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #ddd;padding-bottom:12px}}
h1{{font-size:18px;font-weight:600;margin:0}}h2{{font-size:14px;font-weight:600;margin:28px 0 8px;color:#555}}
ul{{list-style:none;padding:0;margin:0}}li{{padding:8px 0;border-bottom:1px solid #eee;word-break:break-all}}.empty{{color:#999}}
button{{font:inherit;background:none;border:1px solid #ccc;border-radius:4px;padding:4px 10px;cursor:pointer}}
</style></head><body><header><h1>All Tomorrow</h1><span>{safe_user} <button onclick="logout()">로그아웃</button></span></header>
<h2>프로젝트</h2><ul id="projects"><li class="empty">불러오는 중</li></ul>
<h2>실행 기록</h2><ul id="runs"><li class="empty">불러오는 중</li></ul>
<h2>답을 기다리는 질문</h2><ul id="questions"><li class="empty">불러오는 중</li></ul>
<script>function label(x){{if(typeof x!=='object'||!x)return String(x);return x.title||x.name||x.question||x.text||x.id||JSON.stringify(x);}}
async function load(id,path){{const el=document.getElementById(id);const r=await fetch(path);if(!r.ok){{el.innerHTML='<li class="empty">불러오기 실패</li>';return;}}
const items=await r.json();el.innerHTML='';if(!items.length){{el.innerHTML='<li class="empty">없음</li>';return;}}
for(const it of items){{const li=document.createElement('li');li.textContent=label(it);el.appendChild(li);}}}}
load('projects','/api/projects');load('runs','/api/runs');load('questions','/api/questions');
async function logout(){{await fetch('/api/logout',{{method:'POST'}});location='/login';}}</script></body></html>"""


def create_app(
    *,
    auth: Auth,
    web_state: WebState | None = None,
    policy_path: str = "edge/discord/default.yaml",
    cookie_secure: bool = True,
) -> FastAPI:
    app = FastAPI(title="All Tomorrow Control Plane", version="0.1.0")
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
            secure=cookie_secure,
            samesite="strict",
            max_age=auth.ttl_seconds,
        )

    @app.post("/api/logout", status_code=204)
    async def logout(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        all_tomorrow_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Response:
        # Browsers get sent to the login page instead of a raw JSON 401.
        try:
            user = auth.verify(all_tomorrow_session)
        except HTTPException:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(_dashboard(user))

    @app.get("/api/projects")
    async def projects(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return [asdict(project) for project in state_store.projects.values()]

    @app.get("/api/runs")
    async def runs(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.runs)

    @app.get("/api/questions")
    async def questions(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.questions)

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

    return app


def app_from_environment() -> FastAPI:
    username = os.environ.get("ALL_TOMORROW_ADMIN_USER", "")
    password = os.environ.get("ALL_TOMORROW_ADMIN_PASSWORD", "")
    secret = os.environ.get("ALL_TOMORROW_SESSION_SECRET", "")
    edge_token = os.environ.get("ALL_TOMORROW_EDGE_TOKEN")
    # Secure cookies need HTTPS; allow opting out for a plain-HTTP deployment.
    cookie_secure = os.environ.get("ALL_TOMORROW_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
    return create_app(auth=Auth(username, password, secret, edge_token=edge_token), cookie_secure=cookie_secure)


def run() -> None:
    import uvicorn

    uvicorn.run(
        app_from_environment(),
        host=os.environ.get("ALL_TOMORROW_HOST", "127.0.0.1"),
        port=int(os.environ.get("ALL_TOMORROW_PORT", "8080")),
    )
