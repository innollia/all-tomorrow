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

    def __post_init__(self) -> None:
        if self.usage is None and self.usage_path and self.usage_path.exists():
            self.usage = json.loads(self.usage_path.read_text(encoding="utf-8"))

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


def _dashboard(username: str) -> str:
    safe_user = escape(username)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow</title><style>
body{{font:15px system-ui;margin:0;background:#0c1018;color:#e9edf5}}header{{padding:18px 24px;background:#161c29;display:flex;justify-content:space-between}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;padding:20px}}section{{background:#171e2c;padding:18px;border-radius:14px;min-height:180px}}
pre{{white-space:pre-wrap;color:#b8c4dc}}
#usage{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;padding:20px 20px 0}}
.uc{{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:16px}}.uh{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}}
.uh b{{font-size:17px}}.uh small{{color:#8a8f99;margin-left:6px}}.ok{{color:#4ccf8a}}.bad{{color:#ff9a9a}}.ub{{background:#222;border-radius:12px;padding:10px 16px}}
.ur{{padding:9px 0}}.ul{{display:flex;justify-content:space-between;font-size:14px}}.ul span{{color:#9aa0aa;font-family:ui-monospace,monospace;font-size:12.5px}}
.bar{{height:5px;background:#333;border-radius:3px;margin-top:7px}}.bar i{{display:block;height:100%;border-radius:3px;background:#f26b1d}}.bar i.hi{{background:#e2685f}}.stale{{color:#8a8f99;font-size:12px;margin-top:6px}}button{{background:#6d5dfc;color:white;border:0;padding:8px 12px;border-radius:7px;cursor:pointer}}
</style></head><body><header><strong>All Tomorrow Control Plane</strong><span>{safe_user} <button onclick="logout()">로그아웃</button></span></header>
<div id="usage"></div>
<main><section><h2>Chat</h2><p>Edge routing preview가 먼저 적용됩니다. 실행 pipeline 연결은 다음 단계입니다.</p></section>
<section><h2>Projects</h2><pre id="projects">loading…</pre></section><section><h2>Runs</h2><pre id="runs">loading…</pre></section>
<section><h2>Pending Questions</h2><pre id="questions">loading…</pre></section></main>
<script>async function load(id,path){{const r=await fetch(path);document.getElementById(id).textContent=r.ok?JSON.stringify(await r.json(),null,2):'불러오기 실패';}}
function left(t){{const ms=new Date(t)-Date.now();if(!(ms>0))return null;const m=Math.floor(ms/60000),d=Math.floor(m/1440),h=Math.floor(m%1440/60);return d?`${{d}}일 ${{h}}시간`:h?`${{h}}시간 ${{m%60}}분`:`${{m%60}}분`;}}
function esc(v){{return String(v??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');}}
async function loadUsage(){{const box=document.getElementById('usage');const r=await fetch('/api/usage');if(!r.ok){{box.textContent='사용량 불러오기 실패';return;}}
const snap=await r.json();if(!snap){{box.innerHTML='<div class="uc">사용량 데이터 없음 — 로컬 PC에서 all-tomorrow-usage push 실행 필요</div>';return;}}
box.innerHTML=snap.providers.map(p=>{{const ok=p.status==='connected';const rows=p.windows.map(w=>{{const l=left(w.resets_at);const pct=l===null?0:Math.round(w.percent);
return `<div class="ur"><div class="ul">${{esc(w.label)}}<span>${{pct}}% 사용 · ${{l===null?'초기화됨':l+' 후 초기화'}}</span></div><div class="bar"><i class="${{pct>=80?'hi':''}}" style="width:${{Math.min(pct,100)}}%"></i></div></div>`;}}).join('');
const age=Math.round((Date.now()-new Date(p.observed_at))/60000);
return `<div class="uc"><div class="uh"><div><b>${{esc(p.name)}}</b><small>${{esc(p.plan)}}</small></div><span class="${{ok?'ok':'bad'}}">● ${{ok?'연결됨':esc(p.status)}}</span></div><div class="ub">${{rows||'데이터 없음'}}</div>${{age>30?`<div class="stale">${{age<1440?Math.round(age/60)+'시간':Math.round(age/1440)+'일'}} 전 관측값</div>`:''}}</div>`;}}).join('');}}
loadUsage();setInterval(loadUsage,60000);
load('projects','/api/projects');load('runs','/api/runs');load('questions','/api/questions');
async function logout(){{await fetch('/api/logout',{{method:'POST'}});location='/login';}}</script></body></html>"""


def create_app(*, auth: Auth, web_state: WebState | None = None, policy_path: str = "edge/discord/default.yaml") -> FastAPI:
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
    usage_token = os.environ.get("ALL_TOMORROW_USAGE_TOKEN")
    usage_path = Path(os.environ.get("ALL_TOMORROW_USAGE_PATH", ".artifacts/usage.json"))
    return create_app(
        auth=Auth(username, password, secret, edge_token=edge_token, usage_token=usage_token),
        web_state=WebState(usage_path=usage_path),
    )


def run() -> None:
    import uvicorn

    uvicorn.run(
        app_from_environment(),
        host=os.environ.get("ALL_TOMORROW_HOST", "127.0.0.1"),
        port=int(os.environ.get("ALL_TOMORROW_PORT", "8080")),
    )
