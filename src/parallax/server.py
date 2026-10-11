"""Authenticated loopback API and packaged Studio."""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import re
import secrets
import time
import httpx
from collections import Counter
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from . import __version__
from .engine import Engine
from .models import RunSpec, RunResult, RunEvent, ProjectProfile, Participant
from .recovery import RecoveryRequest, AlphaFeedback, recovery_options, save_feedback, save_baseline_feedback, export_feedback
from .connections import ConnectionInput
from .store import Store
from .receipt import get_receipt
from .workflows import Workflows, WorkflowStart, TemplateInput, Decision, RevisionRequest, ApprovalRequest, DeliveryRequest, ReviewerAssignment, CommentInput
from .deployment import Deployment
from . import authority
from .teams import TeamInput, InvitationInput, InvitationAccept, ProjectBinding, ProjectMembersInput
from .pilot import Pilot, BenchmarkInput
from .github_delivery import GitHubDelivery, RepositoryBinding, PublicationRequest
from .accounts import (Accounts, Principal, SignInRefused, operator_principal, SESSION_COOKIE, FLOW_COOKIE,
                       FLOW_COOKIE_PATH, OAUTH_FLOW_PATH, OWNER_WORKSPACE)

# Paths a workspace without hosted execution may use. Everything else under /api
# reaches the hosted runtime's own engine, CLI sign-ins, and project clones.
HOST_SHAPE = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::[0-9]{1,5})?")
WORKSPACE_ROUTES = re.compile(r"/api/(?:session|account|workspaces(?:/.*)?|invitations/accept|github(?:/.*)?|pilot/config|oauth/consent|oauth/grants|oauth/grants/[a-f0-9-]+|executors|executors/pair|executors/[^/]+|executors/[^/]+/proxy/.*)")
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

class MemberRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(owner|developer|reviewer)$")

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
PUBLIC_NAVIGATIONS = {"/api/github/connect/callback","/api/auth/github/callback", "/api/auth/oauth/callback", "/api/auth/confirm", "/api/oauth/callback"}
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
    features: list[str] = Field(default_factory=list, max_length=16)

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
    features: list[str] = Field(default_factory=list,max_length=16)

class WorkerTransportStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "local_evidence_only"] = "ok"
    problem_count: int = Field(default=0, ge=0, le=1000)
    limit_bytes: Literal[8388608] = 8388608
    detail: str = Field(default="", max_length=512)

class WorkerHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: list[str] = Field(default_factory=list, max_length=16)
    transport_status: WorkerTransportStatus = Field(default_factory=WorkerTransportStatus)

def create_app(store:Store|None=None, registry=None, *, token:str|None=None, workspace:str|None=None, deployment:Deployment|None=None, allowed_workspaces:tuple[Path,...]|None=None, http_transport=None):
    store=store or Store()
    engine=Engine(store,registry)
    token=token or secrets.token_urlsafe(32)
    if deployment and not hmac.compare_digest(token,deployment.token):
        raise ValueError("Hosted access token does not match deployment configuration")
    accounts=Accounts(store,deployment,transport=http_transport) if deployment else None
    def check_workspace(value):
        authority.require_project(str(Path(value).expanduser().resolve()))
        if deployment: deployment.check_workspace(value)
        if allowed_workspaces is not None and Path(value).expanduser().resolve() not in allowed_workspaces:
            raise ValueError("This project was not approved on the execution machine")
    workflows = Workflows(engine, check_workspace)
    pilot = Pilot(workflows)
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
        await workflows.recover()
        janitor = asyncio.create_task(remote.consent.janitor()) if remote else None
        try:
            yield
        finally:
            if janitor:
                janitor.cancel()
                await asyncio.gather(janitor, return_exceptions=True)
                await remote.consent.close()
            await workflows.close()
            await engine.shutdown()
    app=FastAPI(title="Parallax",version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=engine;app.state.token=token;app.state.store=store;app.state.accounts=accounts
    app.state.workflows = workflows
    from .executors import ExecutorHub, MAX_MESSAGE, limits_for, is_control, CONTROL_SLOTS
    hub = ExecutorHub(store, accounts=accounts) if deployment else None
    app.state.executors = hub
    github = GitHubDelivery(store,transport=http_transport)
    app.state.github_delivery = github
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
    def queued_requester(request):
        principal = principal_of(request)
        return {"session":principal.session, "workspace":principal.workspace,
                "actor":(principal.account or {}).get("id", "operator")} if principal.session else None
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
        if path=="/api/health" or (path=="/api/github/webhook" and request.method=="POST"):
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
                request.state.worker = await asyncio.to_thread(hub.authenticate, request.headers.get("authorization", "").removeprefix("Bearer "))
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
        if deployment and principal.workspace_kind == "team" and not deployment.pilot_enabled:
            return JSONResponse({"detail":"Team pilot is disabled on this deployment"},status_code=403)
        request.state.principal=principal
        ctx = None
        if not deployment and allowed_workspaces is not None and request.headers.get("x-parallax-authority"):
            try:
                ctx = json.loads(request.headers["x-parallax-authority"])
                if ctx.get("version") != "2.0" or not isinstance(ctx.get("projects"), list): raise ValueError()
            except (ValueError, TypeError):
                return JSONResponse({"detail":"Update required for authenticated worker operations"}, status_code=409)
        if ctx and ctx.get("team") and re.match(r"^/api/runs/[a-f0-9-]{36}(?:/|$)", path):
            try:
                saved = store.get(path.split('/')[3])
                if saved["spec"]["workspace"] not in ctx["projects"] or saved["artifacts"].get("authority",{}).get("workspace") != ctx["workspace"]:
                    raise KeyError()
            except KeyError: return JSONResponse({"detail":"Run not found"},status_code=404)
        binding = authority.current.set(ctx)
        try: response=await call_next(request)
        finally: authority.current.reset(binding)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Cache-Control"]="no-store"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({"detail":str(exc)},status_code=400)
    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
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
    async def context():
        ctx=authority.context()
        projects=(ctx or {}).get("projects") or [workspace or os.environ.get("PARALLAX_WORKSPACE","")]
        return {"workspace":projects[0],"authority":ctx}
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
    def require_pilot():
        if deployment and not deployment.pilot_enabled: raise HTTPException(503,"The invited pilot is not enabled on this deployment")
    def teams():
        if not accounts: raise HTTPException(404)
        return accounts.teams
    @app.get("/api/workspaces")
    async def workspace_list(request:Request): return teams().list(principal_of(request))
    @app.post("/api/workspaces")
    async def workspace_create(body:TeamInput, request:Request):
        require_pilot()
        return teams().create(principal_of(request), body.name)
    @app.post("/api/workspaces/{identifier}/switch")
    async def workspace_switch(identifier:str, request:Request):
        teams()
        value,lifetime=accounts.switch_workspace(principal_of(request), identifier)
        return set_session(JSONResponse({"ok":True}),value,lifetime)
    @app.get("/api/workspaces/members")
    async def workspace_members(request:Request): return teams().members(principal_of(request))
    @app.delete("/api/workspaces/members/{identifier}")
    async def workspace_remove(identifier:str, request:Request): return teams().remove(principal_of(request),identifier)
    @app.patch("/api/workspaces/members/{identifier}")
    async def workspace_member_role(identifier:str, body:MemberRoleInput, request:Request): return teams().change_role(principal_of(request),identifier,body.role)
    @app.post("/api/workspaces/invitations")
    async def workspace_invite(body:InvitationInput, request:Request): return teams().invite(principal_of(request),body.role)
    @app.post("/api/invitations/accept")
    async def invitation_accept(body:InvitationAccept, request:Request): return teams().accept(principal_of(request),body.token)
    @app.get("/api/workspaces/projects")
    async def workspace_projects(request:Request): return teams().projects(principal_of(request))
    @app.post("/api/workspaces/projects")
    async def workspace_bind(body:ProjectBinding, request:Request): return teams().bind(principal_of(request),body,hub)
    @app.patch("/api/workspaces/projects/{identifier}")
    async def workspace_project_members(identifier:str, body:ProjectMembersInput, request:Request):
        return await asyncio.to_thread(teams().update_project_members, principal_of(request), identifier, body)
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
        return set_session(RedirectResponse("/studio",status_code=303),value,lifetime)
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
            response=set_session(RedirectResponse("/studio",status_code=303),value,lifetime)
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
            response=set_session(RedirectResponse("/studio",status_code=303),value,lifetime)
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
        machines = await asyncio.to_thread(hub.workers, scope) if hub else []
        if accounts and teams().is_team(scope):
            actor,role = teams().require(principal_of(request))
            if role != "owner":
                projects = teams().projects(principal_of(request))
                machines = [{**m,"workspaces":[p["path"] for p in projects if p["worker"]==m["id"]]} for m in machines]
                machines = [m for m in machines if m["workspaces"]]
        return JSONResponse(machines,headers={"X-Parallax-Workspace":scope})
    @app.get("/api/executors/archives")
    async def executor_archives(request:Request, cursor:int=0, limit:int=50):
        if not hub: raise HTTPException(404)
        principal = principal_of(request)
        ctx = {"actor":(principal.account or {}).get("id"), "session":principal.session}
        return await asyncio.to_thread(hub.archives, principal.workspace, authority=ctx, cursor=cursor, limit=limit)
    @app.post("/api/executors/pair")
    async def pair_worker(request:Request):
        if not hub: raise HTTPException(404)
        principal = principal_of(request)
        issuer = None
        if teams().is_team(principal.workspace):
            actor, _ = teams().require(principal,("owner",))
            issuer = {"actor":actor, "session":principal.session}
        return await asyncio.to_thread(hub.pair, principal.workspace, authority=issuer)
    @app.delete("/api/executors/{identifier}")
    async def revoke_worker(identifier:str,request:Request):
        if not hub: raise HTTPException(404)
        principal = principal_of(request)
        ctx = None
        if teams().is_team(principal.workspace):
            actor, _ = teams().require(principal,("owner",))
            ctx = {"actor": actor, "session": principal.session}
        return await asyncio.to_thread(hub.revoke, identifier, principal.workspace, authority=ctx)
    # Small SQLite worker operations run in threads; dispatch also refreshes remote baselines.
    @app.post("/api/worker/connect")
    def connect_worker(body:WorkerConnect):
        if not hub: raise HTTPException(404)
        if any(len(path)>4096 or not Path(path).is_absolute() for path in body.workspaces):
            raise ValueError("Worker projects must be absolute paths")
        return hub.connect(body.code,body.name,{"platform":body.platform,"workspaces":body.workspaces,"features":body.features})
    @app.get("/api/worker/next")
    async def next_worker(request:Request):
        if not hub: raise HTTPException(404)
        commands = await asyncio.to_thread(hub.pending,request.state.worker,mark_dispatched=False)
        ready = []
        for command in commands:
            ctx = command.get("authority") or {}
            target = ctx.get("github_target")
            delivered = await asyncio.to_thread(hub.dispatched,request.state.worker,command["id"])
            if not delivered and target and command["method"] == "POST" and (command["path"] == "/api/workflows" or command["path"].endswith(("/revise", "/resume"))):
                try:
                    fresh = await github.baseline(ctx["workspace"],target["id"])
                    if any(fresh[k] != target[k] for k in ("base_commit","base_tree")):
                        raise HTTPException(409,"Remote base changed before execution. Start a fresh task")
                except (HTTPException, httpx.HTTPError) as exc:
                    rejected = await asyncio.to_thread(hub.reject_undispatched,request.state.worker,command["id"],{"status":getattr(exc,"status_code",502),"body":{"detail":getattr(exc,"detail","GitHub baseline could not be verified before dispatch")},"content_type":"application/json"})
                    if rejected:
                        continue
            dispatched = await asyncio.to_thread(hub.dispatch,request.state.worker,command["id"])
            if dispatched is not None:
                ready.append(dispatched)
        return ready
    @app.post("/api/worker/reply")
    def reply_worker(body:WorkerReply,request:Request):
        if not hub: raise HTTPException(404)
        return hub.complete(request.state.worker,body.id,body.model_dump(exclude={"id"}))
    @app.post("/api/worker/sync")
    def sync_worker(body:WorkerSync,request:Request):
        if not hub: raise HTTPException(404)
        hub.features(request.state.worker, body.features)
        return hub.sync(request.state.worker,[r.model_dump() for r in body.runs],[e.model_dump() for e in body.events])
    @app.post("/api/worker/heartbeat")
    def heartbeat_worker(body:WorkerHeartbeat, request:Request):
        if not hub: raise HTTPException(404)
        return hub.heartbeat(request.state.worker, body.features, body.transport_status.model_dump())
    @app.api_route("/api/executors/{identifier}/proxy/{path:path}", methods=["GET","POST","PUT","DELETE"])
    async def worker_proxy(identifier:str,path:str,request:Request):
        if not hub: raise HTTPException(404)
        scope=principal_of(request).workspace
        limits=limits_for(scope)
        if path.endswith(("/record-publication", "/begin-publication")): raise HTTPException(403,"Publication operations are recorded by the relay")
        descriptor = await asyncio.to_thread(hub.worker, identifier, scope)
        if "workflow-v2" not in descriptor.get("features",[]) and (path.endswith(("/revise","/approve","/apply","/publication-preview")) or (request.method=="POST" and path=="workflows")):
            # Legacy personal starts remain available; versioned starts are checked below after parsing.
            if path != "workflows": raise HTTPException(409,"Update this worker for candidate revision and separate delivery")
        auth = {"version":"2.0","workspace":scope,"actor":(principal_of(request).account or {}).get("id", "operator"),"role":"owner","team":False,"projects":descriptor["workspaces"]} if "workflow-v2" in descriptor.get("features",[]) else None
        if teams().is_team(scope):
            if "workflow-v2" not in descriptor.get("features",[]): raise HTTPException(409,"Update this worker for team workflows")
            auth = teams().context(principal_of(request), identifier)
            auth = teams().reauthorize(auth,identifier,request.method,"/api/"+path)
            if path.startswith("runs/"):
                saved = hub.cached(identifier,"/api/runs/"+path.split('/')[1])
                if not saved or saved.get("body",{}).get("spec",{}).get("workspace") not in auth["projects"]:
                    raise HTTPException(404,"Run not found")
        if request.method=="GET" and re.fullmatch(r"runs/[a-f0-9-]{36}/events",path):
            try: cursor=max(0,int(request.query_params.get("cursor","0")),int(request.headers.get("last-event-id","0")))
            except ValueError: raise HTTPException(400,"Invalid event cursor")
            if event_streams[scope]>=limits.event_streams:
                raise HTTPException(429,"Too many live event streams are open for this workspace. Close another Studio tab and retry.")
            async def replay():
                # Counted from the first iteration: an unstarted generator never reaches its finally block.
                event_streams[scope]+=1
                position=cursor
                try:
                    while not await request.is_disconnected():
                        if not await asyncio.to_thread(still_signed_in, request): break
                        try:
                            items = await asyncio.to_thread(hub.events, identifier, path.split('/')[1], position, scope, authority=auth)
                        except HTTPException as exc:
                            if exc.status_code in {401, 403, 404}: break
                            raise
                        for event in items:
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
        if auth and auth.get("team") and path.startswith("workflow-templates") and request.method in {"POST","PUT"}:
            identifier=path.split('/')[1] if '/' in path else None
            return teams().save_recipe(principal_of(request),TemplateInput.model_validate(body),identifier)
        if request.method=="POST" and path=="workflows" and isinstance(body,dict) and body.get("schema_version")=="2.0" and auth is None:
            raise HTTPException(409,"Update this worker for versioned tasks")
        if request.method=="POST" and path=="workflows" and isinstance(body,dict) and body.get("task_settings") is not None and "workflow-task-settings-v1" not in descriptor.get("features",[]):
            raise HTTPException(409,"Update this worker to use task-specific instructions and checks")
        if request.method=="POST" and path=="workflows" and isinstance(body,dict) and body.get("github_binding"):
            if auth is None: raise HTTPException(409,"Update this worker for GitHub delivery")
            target=await github.baseline(scope,body["github_binding"])
            if target["worker"]!=identifier or target["project"]!=body.get("workspace") or target["project"] not in auth["projects"]:
                raise HTTPException(403,"GitHub project binding does not match the task")
            auth["github_target"]=target
        if auth and request.method=="POST" and re.fullmatch(r"workflows/[a-f0-9-]{36}/(?:revise|resume)",path):
            parent_reply=await hub.request(identifier,"GET","/api/"+path.rsplit('/',1)[0],"",None,workspace=scope,authority=auth,requester=queued_requester(request))
            if parent_reply["status"]!=200: raise HTTPException(parent_reply["status"],"Task is unavailable")
            target=parent_reply["body"].get("github_target")
            if target:
                fresh=await github.baseline(scope,target["id"])
                if any(fresh[k]!=target[k] for k in ("base_commit","base_tree")):
                    raise HTTPException(409,"Remote base changed. Start a fresh task")
                auth["github_target"]=target
        capacity = limits.relay_requests + (CONTROL_SLOTS if is_control(request.method, "/api/"+path) else 0)
        if relay_inflight[scope]>=capacity:
            raise HTTPException(429,"Too many requests are waiting on this workspace's machines. Retry shortly.")
        relay_inflight[scope]+=1
        try: reply=await hub.request(identifier,request.method,"/api/"+path,str(request.query_params),body,workspace=scope,authority=auth,requester=queued_requester(request))
        finally: relay_inflight[scope]-=1
        headers={"X-Parallax-Worker":identifier,"X-Parallax-Offline":"true" if reply.get("offline") else "false"}
        if path.endswith('/patch'):
            headers["Content-Disposition"]='attachment; filename=parallax.patch'
            return Response(str(reply["body"]),status_code=reply["status"],media_type="text/plain",headers=headers)
        if path.endswith('/receipt'): headers["Content-Disposition"]='attachment; filename=parallax-verification.json'
        return JSONResponse(reply["body"],status_code=reply["status"],headers=headers)
    def github_owner(principal):
        if not principal.account: raise HTTPException(403,"Connect GitHub with an individual owner account")
        if teams().is_team(principal.workspace): teams().require(principal,("owner",))
        return principal.account["id"]
    def github_actor_owner(workspace, actor):
        if teams().is_team(workspace):
            if teams().role(workspace, actor) != "owner": raise HTTPException(403,"Ownership was removed")
        else:
            with store.connect() as db:
                if not db.execute("SELECT 1 FROM accounts WHERE id=? AND workspace=? AND disabled=0",(actor,workspace)).fetchone():
                    raise HTTPException(403,"Ownership was removed")
    @app.get("/api/github/config")
    async def github_config(): return {"configured":github.configured() and (not deployment or deployment.pilot_enabled),"installation_url":"https://github.com/apps/"+github.config.get("slug","")+"/installations/new","permissions":["Contents write","Pull requests write","Checks read","Statuses read","Actions read"]}
    @app.post("/api/github/connect/start")
    async def github_connect(request:Request):
        require_pilot()
        principal=principal_of(request); github_owner(principal)
        url,binding=github.begin(principal,deployment.public_origin)
        response=JSONResponse({"url":url,"installation_url":"https://github.com/apps/"+github.config["slug"]+"/installations/new"})
        response.set_cookie("parallax_github",binding,httponly=True,secure=True,samesite="lax",max_age=600,path="/api/github/connect")
        return response
    @app.get("/api/github/connect/callback")
    async def github_connect_callback(request:Request):
        if not deployment: raise HTTPException(404)
        await github.finish(request.query_params.get("code",""),request.query_params.get("state",""),request.cookies.get("parallax_github",""),deployment.public_origin,github_actor_owner)
        response=RedirectResponse("/?github_connected=1",status_code=303)
        response.delete_cookie("parallax_github",secure=True,httponly=True,samesite="lax",path="/api/github/connect")
        return response
    @app.get("/api/github/installations")
    async def github_installations(request:Request):
        github_owner(principal_of(request)); return github.installations(principal_of(request).workspace)
    @app.get("/api/github/installations/{identifier}/repositories")
    async def github_repositories(identifier:int, request:Request):
        github_owner(principal_of(request)); return await github.repositories(principal_of(request).workspace,identifier)
    @app.get("/api/github/bindings")
    async def github_bindings(request:Request):
        principal=principal_of(request)
        result=github.bindings(principal.workspace)
        if teams().is_team(principal.workspace):
            projects=teams().projects(principal)
            result=[b for b in result if any(p["worker"]==b["worker"] and p["path"]==b["project"] for p in projects)]
        return result
    @app.post("/api/github/bindings")
    async def github_bind(body:RepositoryBinding, request:Request):
        require_pilot()
        principal=principal_of(request); github_owner(principal)
        machine=hub.worker(body.worker,principal.workspace)
        if body.project not in machine["workspaces"]: raise HTTPException(403,"Project is not approved by this worker")
        if teams().is_team(principal.workspace) and not any(p["worker"]==body.worker and p["path"]==body.project for p in teams().projects(principal)):
            raise HTTPException(403,"Bind this team project first")
        return await github.bind(principal.workspace,body)
    @app.post("/api/github/publish")
    async def github_publish(body:PublicationRequest, request:Request):
        require_pilot()
        principal=principal_of(request); binding=github.binding(principal.workspace,body.binding)
        descriptor=hub.worker(binding["worker"],principal.workspace)
        if "workflow-v2" not in descriptor.get("features",[]): raise HTTPException(409,"Update the worker for GitHub delivery")
        auth={"version":"2.0","workspace":principal.workspace,"actor":(principal.account or {}).get("id","operator"),"role":"owner","team":False,"projects":descriptor["workspaces"]}
        if teams().is_team(principal.workspace):
            auth=teams().context(principal,binding["worker"])
            auth=teams().reauthorize(auth,binding["worker"],"POST","/api/workflows/"+body.workflow+"/publish")
        if binding["project"] not in auth["projects"]: raise HTTPException(403,"Project permission was removed")
        def authorize_publication():
            if not still_signed_in(request): raise HTTPException(403,"Session ended before publication")
            if auth.get("team"):
                fresh=teams().reauthorize(auth,binding["worker"],"POST","/api/workflows/"+body.workflow+"/publish")
                if binding["project"] not in fresh["projects"]: raise HTTPException(403,"Project permission was removed")
            hub.worker(binding["worker"],principal.workspace)
        authorize_publication()
        result=github.completed_publication(principal.workspace,auth["actor"],body)
        if result is None:
            preview=await hub.request(binding["worker"],"POST",f'/api/workflows/{body.workflow}/begin-publication',"",{"request_id":str(body.request_id),"candidate_digest":body.candidate_digest},workspace=principal.workspace,authority=auth,requester=queued_requester(request))
            if preview["status"]!=200: raise HTTPException(preview["status"],preview["body"].get("detail","Candidate unavailable"))
            result=await github.publish(principal.workspace,auth["actor"],body,preview["body"],authorize=authorize_publication)
        recorded=await hub.request(binding["worker"],"POST",f'/api/workflows/{body.workflow}/record-publication',"",result,workspace=principal.workspace,authority=auth,requester=queued_requester(request))
        if recorded["status"]!=200: raise HTTPException(409,"Draft PR exists. Retry the same publication request to reconcile its worker receipt")
        return result
    @app.get("/api/github/publication/{workflow}")
    async def github_publication(workflow:str, request:Request):
        principal=principal_of(request)
        value=github.publication(principal.workspace,workflow)
        if not value: return None
        binding=github.binding(principal.workspace,value["request"]["binding"])
        hub.worker(binding["worker"],principal.workspace)
        if teams().is_team(principal.workspace) and not any(p["worker"]==binding["worker"] and p["path"]==binding["project"] for p in teams().projects(principal)):
            raise HTTPException(404,"No publication")
        return {**value,"can_retry":value["actor"]==(principal.account or {}).get("id","operator")}
    @app.get("/api/github/feedback/{workflow}")
    async def github_feedback(workflow:str, request:Request):
        principal=principal_of(request)
        # Authorize the saved publication's bound project before returning CI or review content.
        with store.connect() as db:
            row=db.execute("SELECT body FROM github_publications WHERE workspace=? AND workflow=? ORDER BY rowid DESC LIMIT 1",(principal.workspace,workflow)).fetchone()
        if not row: raise HTTPException(404,"No publication")
        binding=github.binding(principal.workspace,json.loads(row[0])["binding"])
        if teams().is_team(principal.workspace) and not any(p["worker"]==binding["worker"] and p["path"]==binding["project"] for p in teams().projects(principal)):
            raise HTTPException(404,"No publication")
        return await github.feedback(principal.workspace,workflow)
    @app.post("/api/github/webhook")
    async def github_webhook(request:Request): return github.webhook(request.headers.get("x-github-delivery"),request.headers.get("x-hub-signature-256"),await request.body())
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
        result = await engine.assess(body.workspace,body.package_roots,body.checks,body.participants)
        pilot.setup(body.workspace,result)
        return result
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
    async def runs():
        if not authority.context(): return store.runs()
        return [r for r in store.runs() if r["spec"]["workspace"] in authority.context()["projects"] and r["artifacts"].get("authority",{}).get("workspace")==authority.context()["workspace"]]
    @app.get("/api/pilot/report")
    async def pilot_report(): return pilot.report()
    @app.post("/api/pilot/benchmark")
    async def pilot_benchmark(body:BenchmarkInput): return pilot.benchmark(body)
    @app.get("/api/workflow-templates")
    async def workflow_templates(): return workflows.templates()
    @app.post("/api/workflow-templates")
    async def create_workflow_template(body:TemplateInput): return workflows.save_template(body)
    @app.put("/api/workflow-templates/{identifier}")
    async def update_workflow_template(identifier:str, body:TemplateInput): return workflows.save_template(body, identifier)
    @app.get("/api/workflows")
    async def workflow_list(): return workflows.listing()
    @app.post("/api/workflows")
    async def workflow_start(body:WorkflowStart): return await workflows.start(body)
    @app.get("/api/workflows/{identifier}")
    async def workflow_get(identifier:str):
        value = workflows.get(identifier)
        check_workspace(value["spec"]["workspace"])
        return workflows.public(value)
    @app.post("/api/workflows/{identifier}/decision")
    async def workflow_decide(identifier:str, body:Decision): return await workflows.decide(identifier, body)
    @app.post("/api/workflows/{identifier}/approve")
    async def workflow_approve(identifier:str, body:ApprovalRequest):
        if (authority.context() or {}).get("team") and body.action == "approve":
            value = workflows.get(identifier)
            check_workspace(value["spec"]["workspace"])
            detail = await asyncio.to_thread(workflows.public, value)
            reply = {"status": 200, "body": detail, "content_type": "application/json"}
            exceeds_limit = len(json.dumps(reply, separators=(",", ":")).encode()) > MAX_MESSAGE
            if value.get("run_id"):
                result = await asyncio.to_thread(store.get, value["run_id"])
                envelope = {"runs": [result], "events": [], "features": ["workflow-v2", "workflow-task-settings-v1", "worker-control-v1", "worker-byte-batches-v1"]}
                exceeds_limit = exceeds_limit or len(json.dumps(envelope, separators=(",", ":")).encode()) > MAX_MESSAGE
            if exceeds_limit:
                raise HTTPException(413, "Full candidate evidence exceeds the relay's 8 MiB message limit. Inspect it in local Studio; team approval through the relay is unavailable for this candidate.")
        return await workflows.approve(identifier,body)
    @app.post("/api/workflows/{identifier}/apply")
    async def workflow_apply(identifier:str, body:DeliveryRequest): return await workflows.apply_candidate(identifier,body)
    @app.post("/api/workflows/{identifier}/reviewer")
    async def workflow_reviewer(identifier:str, body:ReviewerAssignment): return workflows.assign(identifier,body.reviewer)
    @app.post("/api/workflows/{identifier}/comment")
    async def workflow_comment(identifier:str, body:CommentInput): return workflows.comment(identifier,body)
    @app.post("/api/workflows/{identifier}/publication-preview")
    async def publication_preview(identifier:str, body:DeliveryRequest): return await workflows.publication_preview(identifier,body)
    @app.post("/api/workflows/{identifier}/begin-publication")
    async def begin_publication(identifier:str, body:DeliveryRequest): return await workflows.begin_publication(identifier,body)
    @app.post("/api/workflows/{identifier}/record-publication")
    async def record_publication(identifier:str, body:dict): return workflows.record_publication(identifier,body)
    @app.post("/api/workflows/{identifier}/revise")
    async def workflow_revise(identifier:str, body:RevisionRequest): return await workflows.revise(identifier, body)
    @app.post("/api/workflows/{identifier}/resume")
    async def workflow_resume(identifier:str): return await workflows.resume(identifier)
    @app.post("/api/workflows/{identifier}/cancel")
    async def workflow_cancel(identifier:str): return await workflows.cancel(identifier)
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
            position=cursor
            while not await request.is_disconnected():
                if not await asyncio.to_thread(still_signed_in, request):
                    break
                try:
                    items = await asyncio.to_thread(store.events, run_id, position)
                except HTTPException as exc:
                    if exc.status_code in {401, 403, 404}: break
                    raise
                for item in items:
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
