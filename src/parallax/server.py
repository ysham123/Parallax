"""Authenticated loopback API and packaged Studio."""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import re
import secrets
import time
from collections import Counter
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from . import __version__
from .engine import Engine
from .models import RunSpec, RunResult, RunEvent, ProjectProfile, Participant
from .recovery import RecoveryRequest, AlphaFeedback, recovery_options, save_feedback, save_baseline_feedback, export_feedback
from .connections import ConnectionInput
from .store import Store
from .receipt import get_receipt
from .deployment import Deployment
from .accounts import (Accounts, Principal, SignInRefused, operator_principal, SESSION_COOKIE, FLOW_COOKIE,
                       FLOW_COOKIE_PATH, OAUTH_FLOW_PATH, OWNER_WORKSPACE)

# Paths a workspace without hosted execution may use. Everything else under /api
# reaches the hosted runtime's own engine, CLI sign-ins, and project clones.
HOST_SHAPE = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::[0-9]{1,5})?")
WORKSPACE_ROUTES = re.compile(r"/api/(?:session|account|oauth/consent|oauth/grants|oauth/grants/[a-f0-9-]+|executors|executors/pair|executors/[^/]+|executors/[^/]+/proxy/.*)")
HOSTED_BODY_LIMIT = 2 * 1024 * 1024
WORKER_CONNECT_LIMIT = 128 * 1024


class BodyLimit:
    """Buffer request bodies up to a bound before routing, including chunked bodies."""

    def __init__(self, app, limit_for):
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope["path"])
        declared = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
        if declared:
            try:
                size = int(declared[0])
            except ValueError:
                return await self._reject(send, 400, "Invalid content length")
            if len(declared) > 1 or size < 0:
                return await self._reject(send, 400, "Invalid content length")
            if size > limit:
                return await self._reject(send, 413, "Request body exceeds the limit")
        body, more = bytearray(), True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return await self._reject(send, 400, "Client disconnected before sending the request body")
            body += message.get("body", b"")
            if len(body) > limit:
                return await self._reject(send, 413, "Request body exceeds the limit")
            more = message.get("more_body", False)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send, status, detail):
        payload = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                                (b"cache-control", b"no-store"), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": payload})

class AssessmentRequest(ProjectProfile):
    participants: list[Participant] = Field(default_factory=list)

class Steering(BaseModel):
    message: str = Field(min_length=1,max_length=20000)

class MemoryLessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=4096)
    status: str = Field(pattern=r"^(active|disabled)$")

class SessionInput(BaseModel):
    token: str = Field(min_length=1,max_length=512)

class EmailSignUp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3,max_length=320)
    password: str = Field(min_length=1,max_length=1024)
    name: str | None = Field(default=None,max_length=200)

class EmailLogIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3,max_length=320)
    password: str = Field(min_length=1,max_length=1024)

class PasswordForgot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3,max_length=320)

class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_hash: str = Field(min_length=1,max_length=300)
    password: str = Field(min_length=1,max_length=1024)

class OAuthStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^(github|google)$")

class ConsentPassword(EmailLogIn):
    authorization_id: str = Field(pattern=r"^[a-f0-9-]{36}$")

class ConsentStart(OAuthStart):
    authorization_id: str = Field(pattern=r"^[a-f0-9-]{36}$")

class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approve: bool

# Paths a signed-out browser may call. Top-level navigations (callbacks and emailed links) carry no Origin header
# and are protected by their flow binding or single-use link instead; the POST routes still require the Studio Origin.
PUBLIC_NAVIGATIONS = {"/api/auth/github/callback", "/api/auth/oauth/callback", "/api/auth/confirm", "/api/oauth/callback"}
PUBLIC_POSTS = {"/api/session", "/api/auth/github/start", "/api/auth/oauth/start", "/api/auth/email/signup",
                "/api/auth/email/login", "/api/auth/password/forgot", "/api/auth/password/reset", "/api/oauth/password", "/api/oauth/start"}
REFUSAL_STATUS = {"invalid_email": 400, "weak_password": 400, "link_expired": 400, "credentials": 401, "unconfirmed": 403,
                  "closed": 403, "not_invited": 403, "disabled": 403, "capacity": 409, "busy": 429, "unavailable": 503}

class WorkerConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=20, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=32)
    workspaces: list[str] = Field(min_length=1, max_length=16)

class WorkerReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    status: int = Field(ge=100, le=599)
    body: object = None
    content_type: str = "application/json"

class WorkerSync(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: list[RunResult] = Field(default_factory=list, max_length=100)
    events: list[RunEvent] = Field(default_factory=list, max_length=500)

def create_app(store:Store|None=None, registry=None, *, token:str|None=None, workspace:str|None=None, deployment:Deployment|None=None, allowed_workspaces:tuple[Path,...]|None=None, http_transport=None):
    store=store or Store()
    engine=Engine(store,registry)
    token=token or secrets.token_urlsafe(32)
    if deployment and not hmac.compare_digest(token,deployment.token):
        raise ValueError("Hosted access token does not match deployment configuration")
    accounts=Accounts(store,deployment,transport=http_transport) if deployment else None
    def check_workspace(value):
        if deployment: deployment.check_workspace(value)
        if allowed_workspaces is not None and Path(value).expanduser().resolve() not in allowed_workspaces:
            raise ValueError("This project was not approved on the execution machine")
    def set_session(response,value=None,lifetime=86400):
        # Local Studio: a signed cookie derived from the launch token. Hosted: an opaque server-side session.
        if value is None:
            value=secrets.token_urlsafe(32)+"."+str(int(time.time()))
            value+="."+hmac.new(token.encode(),value.encode(),"sha256").hexdigest()
        response.set_cookie(SESSION_COOKIE,value,httponly=True,secure=bool(deployment),samesite="strict",max_age=lifetime)
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Cache-Control"]="no-store"
        return response
    def session_valid(value):
        try:
            identifier,stamp,signature=value.split(".")
            age=time.time()-int(stamp)
            expected=hmac.new(token.encode(),(identifier+"."+stamp).encode(),"sha256").hexdigest()
            return 0<=age<=86400 and hmac.compare_digest(signature,expected)
        except (AttributeError,ValueError,TypeError): return False
    static=Path(__file__).parent/"static"
    @asynccontextmanager
    async def lifespan(app):
        engine.recover()
        await engine.reconcile_children()
        janitor = asyncio.create_task(remote.consent.janitor()) if remote else None
        try:
            yield
        finally:
            if janitor:
                janitor.cancel()
                await asyncio.gather(janitor, return_exceptions=True)
                await remote.consent.close()
            await engine.shutdown()
    app=FastAPI(title="Parallax",version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=engine;app.state.token=token;app.state.store=store;app.state.accounts=accounts
    from .executors import ExecutorHub, MAX_MESSAGE, limits_for
    hub = ExecutorHub(store) if deployment else None
    app.state.executors = hub
    from .mcp_remote import RemoteMCP, RESOURCE_PATH
    from .mcp_oauth import CONSENT_COOKIE, CONSENT_FLOW_COOKIE, CONSENT_PATH, CONSENT_SECONDS, authorization_id
    remote = RemoteMCP(accounts, hub) if deployment and deployment.remote_mcp else None
    app.state.remote_mcp = remote
    relay_inflight, event_streams = Counter(), Counter()
    def body_limit(path):
        if path == "/api/mcp" or path.startswith("/api/oauth/"):
            return 64 * 1024
        if path == "/api/worker/connect":
            return WORKER_CONNECT_LIMIT  # Unauthenticated: a name, a platform and a list of project paths.
        if path.startswith("/api/worker/") or "/proxy/" in path or not deployment:
            return MAX_MESSAGE + 65536
        return HOSTED_BODY_LIMIT
    app.add_middleware(BodyLimit, limit_for=body_limit)
    def principal_of(request) -> Principal:
        return request.state.principal
    def still_signed_in(request) -> bool:
        """Live streams re-check the session they opened with, so sign-out, expiry or deletion ends them."""
        principal=principal_of(request)
        if not deployment or principal.session is None:
            return True  # Local sessions, and bearer keys checked on every request.
        current=accounts.principal(request.cookies.get(SESSION_COOKIE))
        return current is not None and current.session==principal.session and current.workspace==principal.workspace

    @app.middleware("http")
    async def guard(request:Request,call_next):
        # Decide on the path the router dispatches. request.url is rebuilt from the Host
        # header, so a crafted Host could otherwise make the guard check a different path.
        path=request.scope["path"]
        raw_host=request.headers.get("host","")
        shape=HOST_SHAPE.fullmatch(raw_host)
        host=shape.group(1).lower() if shape else ""
        allowed_hosts=deployment.hosts|{"127.0.0.1","localhost"} if deployment else {"127.0.0.1","localhost","testserver"}
        if deployment and host=="healthcheck.railway.app" and path=="/api/health":
            return await call_next(request)
        if host not in allowed_hosts:
            return JSONResponse({"detail":"Host is not allowed" if deployment else "Loopback Host required"},status_code=403)
        origin=request.headers.get("origin")
        allowed_origins=deployment.origins if deployment else {f"{request.url.scheme}://{request.headers.get('host')}"}
        # OAuth callbacks and emailed links are top-level navigations; their flow binding or single-use link protects them.
        callback=bool(deployment) and path in PUBLIC_NAVIGATIONS and request.method=="GET"
        if origin and origin not in allowed_origins and not callback:
            return JSONResponse({"detail":"Cross-origin requests are not allowed"},status_code=403)
        if path=="/api/health":
            return await call_next(request)
        # MCP has a separate OAuth bearer boundary. Never treat its tokens as operator-key guesses.
        if path == "/api/mcp" or path in {RESOURCE_PATH, "/.well-known/oauth-protected-resource", "/.well-known/openai-apps-challenge"}:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        if hub and path.startswith("/api/worker/"):
            if origin:
                return JSONResponse({"detail":"Worker protocol requires an outbound CLI connection"},status_code=403)
            if path == "/api/worker/connect" and request.method == "POST":
                return await call_next(request)
            try:
                request.state.worker = hub.authenticate(request.headers.get("authorization", "").removeprefix("Bearer "))
            except HTTPException as exc:
                return JSONResponse({"detail":exc.detail},status_code=exc.status_code)
            return await call_next(request)
        bearer=request.headers.get("authorization","").removeprefix("Bearer ")
        if deployment and request.method not in {"GET","HEAD","OPTIONS"} and not bearer and origin not in allowed_origins:
            return JSONResponse({"detail":"Studio Origin required"},status_code=403)
        if deployment and (callback or (path=="/api/auth/config" and request.method=="GET")
                           or (path in PUBLIC_POSTS and request.method=="POST")):
            return await call_next(request)
        principal=None
        if deployment:
            if bearer and hmac.compare_digest(bearer.encode(),token.encode()):
                principal=operator_principal()
            elif bearer:
                # A wrong key here is a guess like a failed sign-in, and shares its throttle.
                if not accounts.operator_failure():
                    return JSONResponse({"detail":"Too many sign-in attempts. Try again in one minute."},status_code=429)
            else:
                principal=accounts.principal(request.cookies.get(SESSION_COOKIE))
        else:
            presented=request.query_params.get("token","")
            if path=="/" and presented and hmac.compare_digest(presented,token):
                selected=request.query_params.get("workspace","")
                destination="/?"+urlencode({"workspace":selected}) if selected and len(selected)<=4096 else "/"
                return set_session(RedirectResponse(destination,status_code=303))
            if session_valid(request.cookies.get(SESSION_COOKIE)) or (bool(bearer) and hmac.compare_digest(bearer.encode(),token.encode())):
                principal=Principal("local",OWNER_WORKSPACE,True,"Local workspace")
        if principal is None:
            return JSONResponse({"detail":"Sign in to continue" if deployment else "Open Studio from Parallax to establish a local session"},status_code=401)
        if deployment and not principal.hosted_execution and path.startswith("/api/") and not WORKSPACE_ROUTES.fullmatch(path):
            return JSONResponse({"detail":"This workspace runs agents on machines you connect. Choose a connected machine in Studio.",
                                 "code":"hosted_execution_unavailable"},status_code=403)
        request.state.principal=principal
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Cache-Control"]="no-store"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({"detail":str(exc)},status_code=400)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        return JSONResponse({"detail":[{k:v for k,v in item.items() if k in {"loc","msg","type"}} for item in exc.errors()]},status_code=422)
    @app.exception_handler(KeyError)
    async def missing(request,exc): return JSONResponse({"detail":"Run not found"},status_code=404)

    @app.get("/api/health")
    async def health(): return {"ok":True,"version":__version__}

    def require_remote():
        if remote is None:
            raise HTTPException(404, "Remote connections are not enabled")
        return remote

    @app.api_route("/api/mcp", methods=["GET", "POST", "DELETE"])
    async def remote_mcp(request:Request):
        return await require_remote().handle(request)

    @app.get(RESOURCE_PATH)
    @app.get("/.well-known/oauth-protected-resource")
    async def protected_resource():
        return require_remote().metadata()

    @app.get("/.well-known/openai-apps-challenge")
    async def openai_challenge():
        if not deployment or not deployment.openai_challenge:
            raise HTTPException(404)
        return Response(deployment.openai_challenge, media_type="text/plain")

    def consent_session(response, values):
        session, lifetime, nonce = values
        set_session(response, session, lifetime)
        response.set_cookie(CONSENT_COOKIE, nonce, httponly=True, secure=True, samesite="strict",
                            max_age=CONSENT_SECONDS, path=CONSENT_PATH)
        return response

    @app.post("/api/oauth/password")
    async def consent_password(body:ConsentPassword):
        service = require_remote().consent
        authorization_id(body.authorization_id)
        try:
            values = await service.sign_in(body.authorization_id, await accounts.password_exchange(body.email, body.password))
        except SignInRefused as refusal:
            return refused(refusal)
        return consent_session(JSONResponse({"ok":True}), values)

    @app.post("/api/oauth/start")
    async def consent_start(body:ConsentStart):
        service = require_remote().consent
        authorization_id(body.authorization_id)
        try:
            url, binding = accounts.begin_oauth(body.provider, redirect=deployment.public_origin + "/api/oauth/callback")
        except SignInRefused as refusal:
            return refused(refusal)
        response = JSONResponse({"url":url}, headers={"Cache-Control":"no-store"})
        response.set_cookie(CONSENT_FLOW_COOKIE, service.seal_flow(binding, body.authorization_id), httponly=True, secure=True,
                            samesite="lax", max_age=600, path=CONSENT_PATH)
        return response

    @app.get("/api/oauth/callback")
    async def consent_callback(request:Request):
        service = require_remote().consent
        identifier = ""
        try:
            binding, identifier = service.open_flow(request.cookies.get(CONSENT_FLOW_COOKIE, ""))
            query = request.query_params
            provider_session = await accounts.oauth_exchange(code=query.get("code", ""), binding=binding, error=query.get("error"))
            values = await service.sign_in(identifier, provider_session)
            response = consent_session(RedirectResponse("/oauth/consent?" + urlencode({"authorization_id":identifier}), status_code=303), values)
        except SignInRefused as refusal:
            response = RedirectResponse("/oauth/consent?" + urlencode({"authorization_id":identifier, "auth_error":refusal.code}), status_code=303)
        response.delete_cookie(CONSENT_FLOW_COOKIE, path=CONSENT_PATH, secure=True, httponly=True, samesite="lax")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/oauth/consent")
    async def consent_details(request:Request):
        try:
            return await require_remote().consent.details(request.cookies.get(CONSENT_COOKIE, ""), principal_of(request), request.query_params.get("authorization_id", ""))
        except SignInRefused as refusal:
            return refused(refusal)

    @app.post("/api/oauth/consent")
    async def consent_decide(request:Request, body:ConsentDecision):
        try:
            data = await require_remote().consent.decide(request.cookies.get(CONSENT_COOKIE, ""), principal_of(request), request.query_params.get("authorization_id", ""), body.approve)
        except SignInRefused as refusal:
            return refused(refusal)
        response = JSONResponse(data)
        response.delete_cookie(CONSENT_COOKIE, path=CONSENT_PATH, secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/api/oauth/grants")
    async def consent_grants(request:Request):
        return require_remote().consent.grants(principal_of(request))

    @app.delete("/api/oauth/grants/{client}")
    async def consent_revoke(client:str, request:Request):
        return require_remote().consent.revoke(principal_of(request), client)
    @app.get("/api/context")
    async def context(): return {"workspace":workspace or os.environ.get("PARALLAX_WORKSPACE","")}
    @app.post("/api/session")
    async def sign_in(body:SessionInput):
        """Operator access key. Opens only the operator workspace."""
        if not deployment: raise HTTPException(404)
        if not hmac.compare_digest(body.token.encode(),token.encode()):
            if not accounts.operator_failure(): raise HTTPException(429,"Too many sign-in attempts. Try again in one minute.")
            raise HTTPException(401,"Invalid access key")
        value,lifetime=accounts.create_session("operator",OWNER_WORKSPACE)
        return set_session(JSONResponse({"ok":True}),value,lifetime)
    @app.get("/api/session")
    async def session(request:Request): return principal_of(request).public()
    @app.delete("/api/session")
    async def sign_out(request:Request):
        if remote:
            await remote.consent.abandon(principal_of(request).session)
        if accounts: accounts.end_session(principal_of(request).session)
        response=JSONResponse({"ok":True})
        response.delete_cookie(SESSION_COOKIE,secure=bool(deployment),httponly=True,samesite="strict")
        return response
    @app.get("/api/auth/config")
    async def auth_config():
        if not deployment: raise HTTPException(404)
        providers=await accounts.providers()
        # "github" stays for Studio builds that predate the providers list.
        identity="supabase" if deployment.supabase else "github" if deployment.github_redirect else None
        return {"github":"github" in providers,"identity":identity,"providers":providers,"signup":deployment.signup,
                **({"remote_mcp":True} if remote else {})}
    def refused(refusal:SignInRefused):
        return JSONResponse({"detail":refusal.code},status_code=REFUSAL_STATUS.get(refusal.code,502),headers={"Cache-Control":"no-store"})
    def auth_error_redirect(refusal:SignInRefused):
        # Supabase flows return to the log-in page, where the error sits beside the form that can fix it.
        response=RedirectResponse("/login?"+urlencode({"auth_error":refusal.code}),status_code=303)
        response.headers["Referrer-Policy"]="no-referrer";response.headers["Cache-Control"]="no-store"
        return response
    @app.post("/api/auth/email/signup")
    async def email_sign_up(body:EmailSignUp):
        if not deployment: raise HTTPException(404)
        try: await accounts.sign_up(body.email,body.password,body.name)
        except SignInRefused as refusal: return refused(refusal)
        return JSONResponse({"ok":True,"next":"confirm"},headers={"Cache-Control":"no-store"})
    @app.post("/api/auth/email/login")
    async def email_log_in(body:EmailLogIn):
        if not deployment: raise HTTPException(404)
        try: value,lifetime=await accounts.log_in(body.email,body.password)
        except SignInRefused as refusal: return refused(refusal)
        return set_session(JSONResponse({"ok":True}),value,lifetime)
    @app.post("/api/auth/password/forgot")
    async def password_forgot(body:PasswordForgot):
        if not deployment: raise HTTPException(404)
        try: await accounts.forgot_password(body.email)
        except SignInRefused as refusal:
            if refusal.code in ("busy","invalid_email","unavailable"): return refused(refusal)
        return JSONResponse({"ok":True},headers={"Cache-Control":"no-store"})
    @app.post("/api/auth/password/reset")
    async def password_reset(body:PasswordReset):
        if not deployment: raise HTTPException(404)
        try: value,lifetime=await accounts.reset_password(body.token_hash,body.password)
        except SignInRefused as refusal: return refused(refusal)
        return set_session(JSONResponse({"ok":True}),value,lifetime)
    @app.get("/api/auth/confirm")
    async def confirm_email(request:Request):
        if not deployment: raise HTTPException(404)
        query=request.query_params
        try: value,lifetime=await accounts.confirm(query.get("token_hash",""),query.get("type",""))
        except SignInRefused as refusal: return auth_error_redirect(refusal)
        return set_session(RedirectResponse("/",status_code=303),value,lifetime)
    @app.post("/api/auth/oauth/start")
    async def oauth_start(body:OAuthStart):
        if not deployment: raise HTTPException(404)
        try: url,binding=accounts.begin_oauth(body.provider)
        except SignInRefused as refusal: return refused(refusal)
        response=JSONResponse({"url":url},headers={"Cache-Control":"no-store"})
        response.set_cookie(FLOW_COOKIE,binding,httponly=True,secure=True,samesite="lax",max_age=600,path=OAUTH_FLOW_PATH)
        return response
    @app.get("/api/auth/oauth/callback")
    async def oauth_callback(request:Request):
        if not deployment: raise HTTPException(404)
        query=request.query_params
        try:
            value,lifetime=await accounts.finish_oauth(code=query.get("code",""),binding=request.cookies.get(FLOW_COOKIE,""),
                                                       error=query.get("error"))
        except SignInRefused as refusal:
            response=auth_error_redirect(refusal)
        else:
            response=set_session(RedirectResponse("/",status_code=303),value,lifetime)
        response.delete_cookie(FLOW_COOKIE,path=OAUTH_FLOW_PATH,secure=True,httponly=True,samesite="lax")
        return response
    @app.post("/api/auth/github/start")
    async def github_start():
        if not deployment: raise HTTPException(404)
        try: url,binding=accounts.begin_github()
        except SignInRefused as refused:
            return JSONResponse({"detail":refused.code},status_code=429 if refused.code=="busy" else 503,headers={"Cache-Control":"no-store"})
        response=JSONResponse({"url":url},headers={"Cache-Control":"no-store"})
        response.set_cookie(FLOW_COOKIE,binding,httponly=True,secure=True,samesite="lax",max_age=600,path=FLOW_COOKIE_PATH)
        return response
    @app.get("/api/auth/github/callback")
    async def github_callback(request:Request):
        if not deployment: raise HTTPException(404)
        query=request.query_params
        try:
            value,lifetime=await accounts.finish_github(state=query.get("state",""),code=query.get("code",""),
                binding=request.cookies.get(FLOW_COOKIE,""),error=query.get("error"))
        except SignInRefused as refused:
            response=RedirectResponse("/?"+urlencode({"auth_error":refused.code}),status_code=303)
            response.headers["Referrer-Policy"]="no-referrer";response.headers["Cache-Control"]="no-store"
        else:
            response=set_session(RedirectResponse("/",status_code=303),value,lifetime)
        response.delete_cookie(FLOW_COOKIE,path=FLOW_COOKIE_PATH,secure=True,httponly=True,samesite="lax")
        return response
    @app.delete("/api/account")
    async def delete_account(request:Request):
        if not deployment: raise HTTPException(404)
        try: await accounts.delete_account(principal_of(request),hub,request.query_params.get("confirm",""))
        except PermissionError as refused: raise HTTPException(409,str(refused))
        if remote: await remote.consent.abandon(principal_of(request).session)
        response=JSONResponse({"ok":True})
        response.delete_cookie(SESSION_COOKIE,secure=True,httponly=True,samesite="strict")
        return response
    @app.get("/api/deployment")
    async def deployment_status():
        from .assessment import execution_capability
        return {"mode":"hosted" if deployment else "local","execution":execution_capability()}
    @app.get("/api/executors")
    async def executors(request:Request):
        scope=principal_of(request).workspace
        # The workspace header lets a stale Studio tab notice that its cookie now belongs to another account.
        return JSONResponse(hub.workers(scope) if hub else [],headers={"X-Parallax-Workspace":scope})
    @app.post("/api/executors/pair")
    async def pair_worker(request:Request):
        if not hub: raise HTTPException(404)
        return hub.pair(principal_of(request).workspace)
    @app.delete("/api/executors/{identifier}")
    async def revoke_worker(identifier:str,request:Request):
        if not hub: raise HTTPException(404)
        return hub.revoke(identifier,principal_of(request).workspace)
    # Worker endpoints are plain functions: FastAPI runs them in a thread, so SQLite work never blocks the event loop.
    @app.post("/api/worker/connect")
    def connect_worker(body:WorkerConnect):
        if not hub: raise HTTPException(404)
        if any(len(path)>4096 or not Path(path).is_absolute() for path in body.workspaces):
            raise ValueError("Worker projects must be absolute paths")
        return hub.connect(body.code,body.name,{"platform":body.platform,"workspaces":body.workspaces})
    @app.get("/api/worker/next")
    def next_worker(request:Request):
        if not hub: raise HTTPException(404)
        return hub.pending(request.state.worker)
    @app.post("/api/worker/reply")
    def reply_worker(body:WorkerReply,request:Request):
        if not hub: raise HTTPException(404)
        return hub.complete(request.state.worker,body.id,body.model_dump(exclude={"id"}))
    @app.post("/api/worker/sync")
    def sync_worker(body:WorkerSync,request:Request):
        if not hub: raise HTTPException(404)
        return hub.sync(request.state.worker,[r.model_dump() for r in body.runs],[e.model_dump() for e in body.events])
    @app.api_route("/api/executors/{identifier}/proxy/{path:path}", methods=["GET","POST","PUT","DELETE"])
    async def worker_proxy(identifier:str,path:str,request:Request):
        if not hub: raise HTTPException(404)
        scope=principal_of(request).workspace
        limits=limits_for(scope)
        hub.worker(identifier,scope)
        if request.method=="GET" and re.fullmatch(r"runs/[a-f0-9-]{36}/events",path):
            try: cursor=max(0,int(request.query_params.get("cursor","0")),int(request.headers.get("last-event-id","0")))
            except ValueError: raise HTTPException(400,"Invalid event cursor")
            if event_streams[scope]>=limits.event_streams:
                raise HTTPException(429,"Too many live event streams are open for this workspace. Close another Studio tab and retry.")
            async def replay():
                # Counted from the first iteration: an unstarted generator never reaches its finally block.
                event_streams[scope]+=1
                position,ticks=cursor,0
                try:
                    while not await request.is_disconnected():
                        ticks+=1
                        if ticks%10==0 and not still_signed_in(request):
                            break
                        for event in hub.events(identifier,path.split('/')[1],position,scope):
                            position=event["sequence"]
                            yield f"id: {position}\ndata: {json.dumps(event)}\n\n"
                        yield ": keepalive\n\n"
                        await asyncio.sleep(1)
                finally:
                    event_streams[scope]-=1
            return StreamingResponse(replay(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})
        raw=await request.body()
        if len(raw)>MAX_MESSAGE: raise HTTPException(413,"Worker request exceeds limit")
        try: body=json.loads(raw) if raw else None
        except ValueError: raise HTTPException(400,"Invalid JSON body")
        if relay_inflight[scope]>=limits.relay_requests:
            raise HTTPException(429,"Too many requests are waiting on this workspace's machines. Retry shortly.")
        relay_inflight[scope]+=1
        try: reply=await hub.request(identifier,request.method,"/api/"+path,str(request.query_params),body,workspace=scope)
        finally: relay_inflight[scope]-=1
        headers={"X-Parallax-Worker":identifier,"X-Parallax-Offline":"true" if reply.get("offline") else "false"}
        if path.endswith('/patch'):
            headers["Content-Disposition"]='attachment; filename=parallax.patch'
            return Response(str(reply["body"]),status_code=reply["status"],media_type="text/plain",headers=headers)
        if path.endswith('/receipt'): headers["Content-Disposition"]='attachment; filename=parallax-verification.json'
        return JSONResponse(reply["body"],status_code=reply["status"],headers=headers)
    @app.get("/api/providers")
    async def providers(refresh:bool=False):
        return await engine.registry.discover(refresh=True) if refresh else await engine.registry.discover()
    @app.get("/api/models/{provider}")
    async def models(provider:str,transport:str="cli",connection_id:str|None=None,refresh:bool=False):
        if transport=="cli":
            return await engine.registry.catalog(provider,refresh=True) if refresh else await engine.registry.catalog(provider)
        return await engine.registry.catalog(provider,transport=transport,connection_id=connection_id)
    @app.get("/api/connections")
    async def connections(): return await engine.registry.connections()
    @app.put("/api/connections/{identifier}")
    async def connection(identifier:str,body:ConnectionInput): return await engine.registry.put(identifier,body)
    @app.delete("/api/connections/{identifier}")
    async def remove_connection(identifier:str): return engine.registry.delete(identifier)
    @app.post("/api/connections/{identifier}/test")
    async def test_connection(identifier:str): return await engine.registry.test(identifier)
    @app.get("/api/profiles")
    async def profiles(): return store.profiles()
    @app.put("/api/profiles/{name}")
    async def profile(name:str,spec:RunSpec):
        check_workspace(spec.workspace)
        await engine.validate_settings(spec)
        store.put_profile(name,spec.model_dump())
        return {"name":name,"spec":spec.model_dump()}
    @app.delete("/api/profiles/{name}")
    async def remove_profile(name:str): store.delete_profile(name);return {"ok":True}
    @app.post("/api/project/assess")
    async def assess(body:AssessmentRequest):
        check_workspace(body.workspace)
        return await engine.assess(body.workspace,body.package_roots,body.checks,body.participants)
    @app.get("/api/project-profiles")
    async def project_profiles(): return store.project_profiles()
    @app.put("/api/project-profiles/{name}")
    async def project_profile(name:str,body:ProjectProfile):
        check_workspace(body.workspace)
        assessment=await engine.assess(body.workspace,body.package_roots,body.checks)
        store.put_project_profile(name,body.model_dump())
        return {"name":name,"profile":body.model_dump(),"assessment":assessment}
    @app.delete("/api/project-profiles/{name}")
    async def remove_project_profile(name:str): store.delete_project_profile(name);return {"ok":True}
    # Project memory is local to this machine: these routes are deliberately absent from the worker relay allowlist.
    def memory_for(workspace:str):
        if not workspace or not Path(workspace).expanduser().is_dir(): raise ValueError("Choose an existing project directory")
        check_workspace(workspace)
        from .ideas import IdeaStore
        return IdeaStore(store.home,str(Path(workspace).expanduser().resolve()))
    @app.get("/api/memory")
    async def memory(workspace:str,q:str="",status:str|None=None,limit:int=50):
        ideas=await asyncio.to_thread(memory_for,workspace)
        return {"lessons":ideas.lessons(q[:500],status,max(1,min(limit,200))),"counts":ideas.counts()}
    @app.patch("/api/memory/lessons/{identifier}")
    async def lesson_status(identifier:str,body:MemoryLessonUpdate):
        ideas=await asyncio.to_thread(memory_for,body.workspace)
        try: ideas.set_status(identifier,body.status)
        except KeyError: raise HTTPException(404,"Lesson not found")
        return {"ok":True}
    @app.delete("/api/memory")
    async def forget_memory(workspace:str):
        ideas=await asyncio.to_thread(memory_for,workspace)
        with store.connect() as db:
            if db.execute("SELECT 1 FROM project_locks WHERE workspace=?",(str(Path(workspace).expanduser().resolve()),)).fetchone():
                raise HTTPException(409,"A run is active in this project; forget its memory after the run finishes")
        ideas.forget()
        return {"ok":True}
    @app.post("/api/feedback/baseline")
    async def baseline_feedback(body:AlphaFeedback): return save_baseline_feedback(store,body)
    @app.get("/api/feedback/export")
    async def feedback_export():
        return JSONResponse(export_feedback(store),headers={"Content-Disposition":"attachment; filename=parallax-alpha-metrics.json"})
    @app.get("/api/runs/{run_id}/recovery")
    async def recovery(run_id:str): return recovery_options(store.get(run_id))
    @app.post("/api/runs/{run_id}/recover")
    async def recover(run_id:str,body:RecoveryRequest):
        check_workspace(store.get(run_id)["spec"]["workspace"])
        return engine.recover_run(run_id,body.action)
    @app.post("/api/runs/{run_id}/feedback")
    async def feedback(run_id:str,body:AlphaFeedback): return save_feedback(store,run_id,body)
    @app.get("/api/runs")
    async def runs(): return store.runs()
    @app.post("/api/runs")
    async def start(spec:RunSpec):
        check_workspace(spec.workspace)
        return await engine.start(spec)
    @app.get("/api/runs/{run_id}")
    async def result(run_id:str): return store.get(run_id)
    @app.get("/api/runs/{run_id}/receipt")
    async def receipt(run_id:str):
        return JSONResponse(get_receipt(store,run_id),headers={"Content-Disposition":"attachment; filename=parallax-verification.json"})
    @app.get("/api/runs/{run_id}/patch")
    async def patch(run_id:str):
        return Response(store.get(run_id).get("diff",""),media_type="text/plain",
                        headers={"Content-Disposition":"attachment; filename=parallax.patch"})
    @app.post("/api/runs/{run_id}/steer")
    async def steer(run_id:str,body:Steering):
        check_workspace(store.get(run_id)["spec"]["workspace"])
        return engine.steer(run_id,body.message)
    @app.post("/api/runs/{run_id}/{operation}")
    async def control(run_id:str,operation:str):
        check_workspace(store.get(run_id)["spec"]["workspace"])
        return engine.control(run_id,operation)
    @app.get("/api/runs/{run_id}/events")
    async def events(run_id:str,request:Request,cursor:int=0):
        store.get(run_id)
        try: cursor=max(cursor,int(request.headers.get("last-event-id","0")))
        except ValueError: raise HTTPException(400,"Invalid event cursor")
        async def stream():
            position,ticks=cursor,0
            while not await request.is_disconnected():
                ticks+=1
                if ticks%10==0 and not still_signed_in(request):
                    break
                for item in store.events(run_id,position):
                    position=item["sequence"]
                    yield f"id: {position}\ndata: {json.dumps(item)}\n\n"
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})
    @app.get("/api/runs/{run_id}/event-log")
    async def event_log(run_id:str,cursor:int=0):
        store.get(run_id)
        return store.events(run_id,max(0,cursor))[:500]
    @app.get("/{path:path}")
    async def studio(path:str):
        requested=(static/path).resolve()
        if not requested.is_relative_to(static.resolve()): raise HTTPException(404)
        if requested.is_file(): return FileResponse(requested)
        if (static/"index.html").exists(): return FileResponse(static/"index.html")
        return JSONResponse({"detail":"Studio assets are missing. Run the frontend build or reinstall the release."},status_code=503)
    return app
