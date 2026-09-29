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

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from all_tomorrow.contracts import Project
from all_tomorrow.edge import EdgeAction, EdgeAnalysis, load_edge_policy
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web_control import NotFound, WebControl

# Feature 7: attachment limits (per plan: max 10MB, max 5 files per request).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5


SESSION_COOKIE = "all_tomorrow_session"


@dataclass(slots=True)
class WebState:
    projects: dict[str, Project] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class SubmitRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class EdgeDecisionRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=128)
    needs_shared_memory: bool = False
    needs_project_state: bool = False
    needs_cross_project_knowledge: bool = False
    needs_remote_tool: bool = False
    needs_long_running_task: bool = False
    needs_canonical_mutation: bool = False
    tool_risk: str | None = None
    # Feature 8: present only on a Discord-originated decision request, so a
    # CENTRAL_TASK verdict can be stored as the same Goal/Work as the web UI.
    discord_user_id: str | None = None
    discord_message_id: str | None = None
    text: str | None = None


class Auth:
    """Feature 10: password change, brute-force lockout, revoke-all-sessions.

    Sessions are minted as before (signed, stateless, ``ttl_seconds`` absolute
    expiry) for backward-compatible cookie verification, but the account itself
    now goes through ``auth.AuthEngine`` (PBKDF2 password hash, 5-failed-attempt
    lockout, per-login session id). A session id is embedded in the token so
    ``revoke_all_sessions`` can invalidate every outstanding token at once by
    bumping a generation counter -- an already-issued token whose session id
    predates the bump is rejected even though its signature still checks out.
    """

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
        self._secret = secret.encode()
        self.ttl_seconds = ttl_seconds
        self._edge_token_digest = hashlib.sha256(edge_token.encode()).digest() if edge_token else None
        from all_tomorrow.auth import AuthEngine, Role

        # Plan: 5 failed attempts -> 15 minute lockout.
        self._engine = AuthEngine(max_failed=5, lockout_seconds=15 * 60)
        self._engine.register(username, password, Role.OWNER)
        self._generation = 0  # bumped by revoke_all_sessions; invalidates prior tokens

    def verify_password(self, username: str, password: str) -> bool:
        """Login check only (does not mint a token) -- used by tests and by the
        login route, which calls ``issue()`` separately on success."""
        from all_tomorrow.auth import AuthError

        if username != self.username:
            return False
        try:
            self._engine.login(username, password)
            return True
        except AuthError:
            return False

    def account_locked(self) -> bool:
        from all_tomorrow.domain.ids import utc_now

        acct = self._engine._accounts.get(self.username)
        return bool(acct and acct.locked_until and utc_now() < acct.locked_until)

    def change_password(self, current_password: str, new_password: str) -> None:
        from all_tomorrow.auth import AuthError, Role, hash_password

        if not self.verify_password(self.username, current_password):
            raise AuthError("invalid credentials")
        if not new_password or len(new_password) < 8:
            raise AuthError("new password must be at least 8 characters")
        acct = self._engine._accounts[self.username]
        acct.password = hash_password(new_password)
        # A password change invalidates every existing session -- same intent as
        # "log out everywhere", so it reuses the same generation bump.
        self.revoke_all_sessions()

    def revoke_all_sessions(self) -> None:
        self._generation += 1

    def issue(self) -> str:
        payload = json.dumps(
            {"sub": self.username, "exp": int(time.time()) + self.ttl_seconds, "gen": self._generation},
            separators=(",", ":"),
        )
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
        if int(payload.get("gen", 0)) != self._generation:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session revoked")
        return self.username

    def verify_edge_token(self, authorization: str | None) -> None:
        if self._edge_token_digest is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="edge authentication not configured")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="edge authentication required")
        candidate = hashlib.sha256(authorization[7:].encode()).digest()
        if not hmac.compare_digest(candidate, self._edge_token_digest):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid edge credential")


_BASE_CSS = (
    ":root{color-scheme:dark}"
    "body{font:15px system-ui,sans-serif;background:#000;color:#fff;margin:0}"
    "input,textarea,button{font:inherit;color:#fff;background:#000;border:1px solid #555;border-radius:4px;padding:9px}"
    "input:focus,textarea:focus,button:focus-visible{outline:2px solid #fff;outline-offset:-1px}"
    "button{cursor:pointer}button.primary{background:#fff;color:#000;border-color:#fff}"
    "button:disabled{opacity:.5;cursor:default}.muted{color:#999}.err{color:#f66}"
)


def _login_page() -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow</title><style>{_BASE_CSS}
body{{display:grid;place-items:center;height:100vh}}form{{display:grid;gap:10px;width:min(300px,85vw)}}
h1{{font-size:18px;font-weight:600;margin:0 0 8px}}#error{{font-size:13px;min-height:1.2em}}
</style></head><body><form id="login"><h1>All Tomorrow</h1>
<input id="username" autocomplete="username" placeholder="사용자명" autofocus>
<input id="password" type="password" autocomplete="current-password" placeholder="비밀번호">
<button class="primary">로그인</button><div id="error" class="err"></div></form>
<script>login.onsubmit=async(e)=>{{e.preventDefault();const r=await fetch('/api/login',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{username:username.value,password:password.value}})}});if(r.ok)location='/';else error.textContent='로그인 실패';}}</script></body></html>"""


_STATUS_KO = {
    "ACTIVE": "진행 중", "WAITING": "대기", "SUCCEEDED": "완료", "FAILED": "실패",
    "CANCEL_REQUESTED": "취소 요청됨", "CANCELLED": "취소됨", "PENDING": "대기",
    "RUNNING": "실행 중", "STARTING": "시작 중",
}


def _dashboard(username: str) -> str:
    safe_user = escape(username)
    status_ko = json.dumps(_STATUS_KO, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>All Tomorrow</title><style>{_BASE_CSS}
main{{max-width:720px;margin:0 auto;padding:24px}}
header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #333;padding-bottom:12px}}
h1{{font-size:18px;font-weight:600;margin:0}}h2{{font-size:14px;font-weight:600;margin:28px 0 8px;color:#bbb}}
form.ask{{display:grid;gap:8px;margin-top:20px}}textarea{{min-height:70px;resize:vertical}}
.row{{display:flex;gap:8px;align-items:center;justify-content:space-between}}
ul{{list-style:none;padding:0;margin:0}}li{{padding:10px 0;border-bottom:1px solid #222}}
.title{{word-break:break-word}}.meta{{font-size:13px;color:#999;margin-top:4px}}
.qa{{display:flex;gap:8px;margin-top:8px}}.qa input{{flex:1}}
</style></head><body><main>
<header><h1>All Tomorrow</h1><span>{safe_user} <button onclick="location='/account'">계정</button> <button onclick="logout()">로그아웃</button></span></header>
<form class="ask" id="ask"><label for="text" class="muted">할 일을 요청하세요 (Ctrl+Enter로 보내기)</label>
<textarea id="text" autofocus></textarea>
<div class="row"><span id="askmsg" class="muted"></span><button class="primary" id="send">보내기</button></div></form>
<h2>답을 기다리는 질문</h2><ul id="questions"><li class="muted">불러오는 중</li></ul>
<h2>요청한 일</h2><ul id="goals"><li class="muted">불러오는 중</li></ul>
</main><script>
const KO={status_ko};const ko=s=>KO[s]||s;let pendingKey=null;
async function api(path,body){{const r=await fetch(path,{{method:body?'POST':'GET',headers:body?{{'content-type':'application/json'}}:{{}},body:body?JSON.stringify(body):undefined}});
if(r.status===401){{location='/login';throw new Error('auth');}}if(!r.ok)throw new Error((await r.json().catch(()=>({{}}))).detail||r.status);return r.json();}}
function el(tag,cls,text){{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}}
async function refresh(){{let d;try{{d=await api('/api/overview');}}catch(e){{return;}}
const q=document.getElementById('questions');q.innerHTML='';
if(!d.questions.length)q.appendChild(el('li','muted','없음'));
for(const it of d.questions){{const li=el('li');li.appendChild(el('div','title',it.prompt));li.appendChild(el('div','meta',it.goal_title));
const f=el('form','qa');const inp=el('input');inp.placeholder='답변';inp.setAttribute('aria-label','답변');const b=el('button','primary','답하기');
f.append(inp,b);f.onsubmit=async(e)=>{{e.preventDefault();b.disabled=true;try{{await api('/api/questions/'+encodeURIComponent(it.question_id)+'/answer',{{answer:inp.value}});await refresh();}}catch(err){{b.disabled=false;alert('실패: '+err.message);}}}};
li.appendChild(f);q.appendChild(li);}}
const g=document.getElementById('goals');g.innerHTML='';
if(!d.goals.length)g.appendChild(el('li','muted','없음'));
for(const it of d.goals){{const li=el('li');const row=el('div','row');row.appendChild(el('div','title',it.title));
if(!it.terminal&&it.status!=='CANCEL_REQUESTED'){{const b=el('button',null,'취소');b.onclick=async()=>{{if(!confirm('이 일을 취소할까요?'))return;b.disabled=true;try{{await api('/api/goals/'+encodeURIComponent(it.goal_id)+'/cancel',{{}});}}catch(err){{alert('실패: '+err.message);}}await refresh();}};row.appendChild(b);}}
li.appendChild(row);const runs=it.works.flatMap(w=>w.runs);
const work=it.works.map(w=>ko(w.status)).join(', ');
li.appendChild(el('div','meta',ko(it.status)+(work?' · 작업 '+work:'')+' · 실행 '+runs.length+'회 · '+new Date(it.created_at).toLocaleString('ko-KR')));
g.appendChild(li);}}}}
ask.onsubmit=async(e)=>{{e.preventDefault();const v=text.value.trim();if(!v)return;send.disabled=true;askmsg.textContent='보내는 중';
pendingKey=pendingKey||crypto.randomUUID();
try{{const r=await api('/api/requests',{{text:v,idempotency_key:pendingKey}});pendingKey=null;text.value='';askmsg.textContent=r.is_new?'접수됨':'이미 접수된 요청';await refresh();}}
catch(err){{askmsg.textContent='실패: '+err.message+' (다시 보내도 한 번만 접수됩니다)';}}send.disabled=false;}};
text.addEventListener('input',()=>{{pendingKey=null;}});
text.addEventListener('keydown',e=>{{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){{e.preventDefault();ask.requestSubmit();}}}});
async function logout(){{await fetch('/api/logout',{{method:'POST'}});location='/login';}}
refresh();setInterval(refresh,10000);
</script></body></html>"""

def _account_page(username: str) -> str:
    safe_user = escape(username)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>계정 - All Tomorrow</title><style>{_BASE_CSS}
main{{max-width:420px;margin:0 auto;padding:24px}}h1{{font-size:18px;font-weight:600}}
form{{display:grid;gap:10px;margin-top:16px}}#pwmsg,#outmsg{{font-size:13px;min-height:1.2em}}
a{{color:#fff}}
</style></head><body><main>
<p><a href="/">← 대시보드</a></p>
<h1>계정 ({safe_user})</h1>
<h2 style="font-size:14px;color:#bbb">비밀번호 변경</h2>
<form id="pw">
<input id="cur" type="password" autocomplete="current-password" placeholder="현재 비밀번호">
<input id="new" type="password" autocomplete="new-password" placeholder="새 비밀번호 (8자 이상)">
<button class="primary">변경</button><div id="pwmsg" class="err"></div>
</form>
<h2 style="font-size:14px;color:#bbb;margin-top:24px">모든 기기에서 로그아웃</h2>
<button id="out">모든 기기에서 로그아웃</button><div id="outmsg" class="muted"></div>
<script>
pw.onsubmit=async(e)=>{{e.preventDefault();pwmsg.textContent='';
const r=await fetch('/api/account/change-password',{{method:'POST',headers:{{'content-type':'application/json'}},
body:JSON.stringify({{current_password:cur.value,new_password:new.value}})}});
if(r.ok){{location='/';}}else{{pwmsg.textContent=(await r.json().catch(()=>({{}}))).detail||'변경 실패';}}}};
out.onclick=async()=>{{await fetch('/api/account/logout-everywhere',{{method:'POST'}});location='/login';}};
</script></main></body></html>"""


def create_app(
    *,
    auth: Auth,
    web_state: WebState | None = None,
    policy_path: str = "edge/discord/default.yaml",
    cookie_secure: bool = True,
    control: WebControl | None = None,
    lifespan: Any = None,
    upload_dir: str | None = None,
) -> FastAPI:
    app = FastAPI(title="All Tomorrow Control Plane", version="0.1.0", lifespan=lifespan)
    state_store = web_state or WebState()
    policy = load_edge_policy(policy_path)
    ctl = control or WebControl(InMemoryGoalWorkRunStore())
    from all_tomorrow.storage.artifact_store import LocalArtifactStore

    uploads = LocalArtifactStore(upload_dir or "data/artifacts")

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
        if auth.account_locked():
            raise HTTPException(status_code=423, detail="account temporarily locked")
        if not auth.verify_password(payload.username, payload.password):
            if auth.account_locked():
                raise HTTPException(status_code=423, detail="account temporarily locked")
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

    @app.post("/api/account/change-password", status_code=204)
    async def change_password(
        payload: ChangePasswordRequest, response: Response, _: str = Depends(current_user),
    ) -> None:
        from all_tomorrow.auth import AuthError

        try:
            auth.change_password(payload.current_password, payload.new_password)
        except AuthError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # change_password already revoked every session (including this one's
        # token generation); issue a fresh cookie for the caller who just proved
        # they know the new password.
        response.set_cookie(
            SESSION_COOKIE, auth.issue(), httponly=True, secure=cookie_secure,
            samesite="strict", max_age=auth.ttl_seconds,
        )

    @app.post("/api/account/logout-everywhere", status_code=204)
    async def logout_everywhere(response: Response, _: str = Depends(current_user)) -> None:
        auth.revoke_all_sessions()
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

    @app.get("/account", response_class=HTMLResponse)
    async def account_page(
        all_tomorrow_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Response:
        try:
            user = auth.verify(all_tomorrow_session)
        except HTTPException:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(_account_page(user))

    @app.get("/api/projects")
    async def projects(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return [asdict(project) for project in state_store.projects.values()]

    @app.get("/api/runs")
    async def runs(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.runs)

    @app.get("/api/questions")
    async def questions(_: str = Depends(current_user)) -> list[dict[str, Any]]:
        return list(state_store.questions)

    @app.get("/api/overview")
    async def overview(user: str = Depends(current_user)) -> dict[str, Any]:
        return await ctl.overview(user)

    @app.post("/api/requests")
    async def submit_request(payload: SubmitRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return await ctl.submit(user, payload.text, payload.idempotency_key)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/requests/with-attachments")
    async def submit_request_with_attachments(
        text: str,
        idempotency_key: str,
        user: str = Depends(current_user),
        files: list[UploadFile] = File(default=[]),
    ) -> dict[str, Any]:
        if len(files) > MAX_ATTACHMENTS:
            raise HTTPException(status_code=422, detail=f"최대 {MAX_ATTACHMENTS}개까지 첨부할 수 있습니다")
        attachment_refs: list[str] = []
        for upload in files:
            data = await upload.read()
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise HTTPException(status_code=422, detail=f"{upload.filename}: 10MB를 초과합니다")
            # Attachment content is untrusted DATA, never inline text and never a
            # source of authority (ingress_policy.attachment_grants_authority).
            ref = await uploads.store(
                data, media_type=upload.content_type or "application/octet-stream", owner_id=user,
            )
            attachment_refs.append(ref.content_hash)
        try:
            return await ctl.submit(user, text, idempotency_key, attachment_refs=tuple(attachment_refs))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/goals/{goal_id}/cancel")
    async def cancel_goal(goal_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return await ctl.cancel(user, goal_id)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.post("/api/questions/{question_id}/answer")
    async def answer_question(
        question_id: str, payload: AnswerRequest, user: str = Depends(current_user)
    ) -> dict[str, Any]:
        try:
            return await ctl.answer(user, question_id, payload.answer)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/goals/{goal_id}")
    async def goal_detail(goal_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return await ctl.goal_detail(user, goal_id)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.get("/api/works/{work_id}/artifacts")
    async def list_work_artifacts(work_id: str, user: str = Depends(current_user)) -> list[dict[str, Any]]:
        try:
            return await ctl.list_work_artifacts(user, work_id)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.get("/api/works/{work_id}/artifacts/{artifact_ref}")
    async def get_work_artifact(
        work_id: str, artifact_ref: str, user: str = Depends(current_user)
    ) -> dict[str, Any]:
        try:
            content = await ctl.get_artifact_content(user, work_id, artifact_ref)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error
        return {"artifact_ref": artifact_ref, "content": content}

    @app.get("/api/reports")
    async def list_reports(user: str = Depends(current_user)) -> list[dict[str, Any]]:
        return ctl.list_reports(user)

    @app.get("/api/reports/{report_id}")
    async def get_report(report_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return ctl.get_report(user, report_id)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.get("/api/broken-work")
    async def list_broken_work(user: str = Depends(current_user)) -> list[dict[str, Any]]:
        return await ctl.list_broken_work(user)

    @app.post("/api/broken-work/{work_id}/retry")
    async def retry_broken_work(work_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return await ctl.retry_broken_work(user, work_id, operator=user)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.post("/api/broken-work/{work_id}/clean-up")
    async def clean_up_broken_work(work_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            return await ctl.clean_up_broken_work(user, work_id, operator=user)
        except NotFound as error:
            raise HTTPException(status_code=404, detail="not found") from error

    @app.post("/api/edge/discord/decide")
    async def decide(payload: EdgeDecisionRequest, _: str = Depends(current_user)) -> dict[str, Any]:
        analysis_fields = {
            k: v for k, v in payload.model_dump().items()
            if k not in {"discord_user_id", "discord_message_id", "text"}
        }
        decision = policy.decide(EdgeAnalysis(**analysis_fields))
        return {
            "policy_id": policy.policy_id,
            "action": decision.action.value,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
        }

    @app.post("/internal/edge/discord/decide")
    async def internal_decide(payload: EdgeDecisionRequest, request: Request) -> dict[str, Any]:
        auth.verify_edge_token(request.headers.get("authorization"))
        analysis_fields = {
            k: v for k, v in payload.model_dump().items()
            if k not in {"discord_user_id", "discord_message_id", "text"}
        }
        decision = policy.decide(EdgeAnalysis(**analysis_fields))
        result: dict[str, Any] = {
            "policy_id": policy.policy_id,
            "action": decision.action.value,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
        }
        if (
            decision.action == EdgeAction.CENTRAL_TASK
            and payload.discord_user_id
            and payload.discord_message_id
            and payload.text
        ):
            stored = await ctl.submit_from_discord(
                payload.discord_user_id, payload.text, payload.discord_message_id,
            )
            result["goal_id"] = stored["goal_id"]
            result["is_new"] = stored["is_new"]
        return result

    return app


def app_from_environment() -> FastAPI:
    username = os.environ.get("ALL_TOMORROW_ADMIN_USER", "")
    password = os.environ.get("ALL_TOMORROW_ADMIN_PASSWORD", "")
    secret = os.environ.get("ALL_TOMORROW_SESSION_SECRET", "")
    edge_token = os.environ.get("ALL_TOMORROW_EDGE_TOKEN")
    # Secure cookies need HTTPS; allow opting out for a plain-HTTP deployment.
    cookie_secure = os.environ.get("ALL_TOMORROW_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
    auth = Auth(username, password, secret, edge_token=edge_token)
    database_url = os.environ.get("ALL_TOMORROW_DATABASE_URL", "")
    if not database_url:
        return create_app(auth=auth, cookie_secure=cookie_secure)

    # Durable mode: the web reads and writes the canonical PostgreSQL store.
    from contextlib import asynccontextmanager
    from pathlib import Path

    from all_tomorrow.requests import PostgresRequestStore
    from all_tomorrow.storage.postgres import PostgresStore
    from all_tomorrow.storage.semantic_store import PostgresGoalWorkRunStore

    semantic = PostgresGoalWorkRunStore(database_url)
    # Feature 11: idempotency keys survive a restart too (same pool, same DB).
    request_store = PostgresRequestStore(database_url, pool=semantic.pool)
    migration_dir = os.environ.get("ALL_TOMORROW_MIGRATIONS", "migrations")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        migrator = PostgresStore(database_url, pool=semantic.pool)
        await semantic.open()
        if Path(migration_dir).is_dir():
            await migrator.migrate(migration_dir)
        try:
            yield
        finally:
            await semantic.close()

    return create_app(
        auth=auth, cookie_secure=cookie_secure,
        control=WebControl(semantic, request_store), lifespan=lifespan,
    )


def run() -> None:
    import uvicorn

    uvicorn.run(
        app_from_environment(),
        host=os.environ.get("ALL_TOMORROW_HOST", "127.0.0.1"),
        port=int(os.environ.get("ALL_TOMORROW_PORT", "8080")),
    )
