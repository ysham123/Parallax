"""Authenticated loopback API and packaged Studio."""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from .engine import Engine
from .models import RunSpec, RunResult, RunEvent, ProjectProfile, Participant
from .recovery import RecoveryRequest, AlphaFeedback, recovery_options, save_feedback, save_baseline_feedback, export_feedback
from .connections import ConnectionInput
from .store import Store
from .receipt import get_receipt
from .deployment import Deployment

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

def create_app(store:Store|None=None, registry=None, *, token:str|None=None, workspace:str|None=None, deployment:Deployment|None=None, allowed_workspaces:tuple[Path,...]|None=None):
    store=store or Store()
    engine=Engine(store,registry)
    token=token or secrets.token_urlsafe(32)
    if deployment and not hmac.compare_digest(token,deployment.token):
        raise ValueError("Hosted access token does not match deployment configuration")
    def check_workspace(value):
        if deployment: deployment.check_workspace(value)
        if allowed_workspaces is not None and Path(value).expanduser().resolve() not in allowed_workspaces:
            raise ValueError("This project was not approved on the execution machine")
    def set_session(response):
        session=secrets.token_urlsafe(32)+"."+str(int(time.time()))
        session+="."+hmac.new(token.encode(),session.encode(),"sha256").hexdigest()
        response.set_cookie("parallax_session",session,httponly=True,secure=bool(deployment),samesite="strict",max_age=86400)
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Cache-Control"]="no-store"
        return response
    attempts=[]
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
        yield
        await engine.shutdown()
    app=FastAPI(title="Parallax",version="1.1.0",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=engine;app.state.token=token;app.state.store=store
    from .executors import ExecutorHub, MAX_MESSAGE
    hub = ExecutorHub(store) if deployment else None
    app.state.executors = hub

    @app.middleware("http")
    async def guard(request:Request,call_next):
        host=request.headers.get("host","").split(":")[0]
        allowed_hosts=deployment.hosts|{"127.0.0.1","localhost"} if deployment else {"127.0.0.1","localhost","testserver"}
        if deployment and host=="healthcheck.railway.app" and request.url.path=="/api/health":
            return await call_next(request)
        if host.lower() not in allowed_hosts:
            return JSONResponse({"detail":"Host is not allowed" if deployment else "Loopback Host required"},status_code=403)
        origin=request.headers.get("origin")
        allowed_origins=deployment.origins if deployment else {f"{request.url.scheme}://{request.headers.get('host')}"}
        if origin and origin not in allowed_origins:
            return JSONResponse({"detail":"Cross-origin requests are not allowed"},status_code=403)
        if request.url.path=="/api/health":
            return await call_next(request)
        if hub and request.url.path.startswith("/api/worker/"):
            if origin:
                return JSONResponse({"detail":"Worker protocol requires an outbound CLI connection"},status_code=403)
            try: size=int(request.headers.get("content-length", "0"))
            except ValueError: return JSONResponse({"detail":"Invalid content length"},status_code=400)
            if size > MAX_MESSAGE:
                return JSONResponse({"detail":"Worker message exceeds limit"},status_code=413)
            if request.url.path == "/api/worker/connect" and request.method == "POST":
                return await call_next(request)
            try:
                request.state.worker = hub.authenticate(request.headers.get("authorization", "").removeprefix("Bearer "))
            except HTTPException as exc:
                return JSONResponse({"detail":exc.detail},status_code=exc.status_code)
            return await call_next(request)
        bearer=request.headers.get("authorization","").removeprefix("Bearer ")
        authorized=session_valid(request.cookies.get("parallax_session")) or (bool(bearer) and hmac.compare_digest(bearer.encode(),token.encode()))
        if deployment and request.method not in {"GET","HEAD","OPTIONS"} and not bearer and origin not in allowed_origins:
            return JSONResponse({"detail":"Studio Origin required"},status_code=403)
        if deployment and request.url.path=="/api/session" and request.method=="POST":
            return await call_next(request)
        presented=request.query_params.get("token","")
        if not deployment and request.url.path=="/" and presented and hmac.compare_digest(presented,token):
            selected=request.query_params.get("workspace","")
            destination="/?"+urlencode({"workspace":selected}) if selected and len(selected)<=4096 else "/"
            response=RedirectResponse(destination,status_code=303)
            return set_session(response)
        if not authorized:
            return JSONResponse({"detail":"Open Studio from Parallax to establish a local session"},status_code=401)
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
    async def health(): return {"ok":True,"version":"1.1.0"}
    @app.get("/api/context")
    async def context(): return {"workspace":workspace or os.environ.get("PARALLAX_WORKSPACE","")}
    @app.post("/api/session")
    async def sign_in(body:SessionInput):
        if not deployment: raise HTTPException(404)
        stamp=time.monotonic()
        attempts[:]=[value for value in attempts if stamp-value<60]
        if len(attempts)>=20: raise HTTPException(429,"Too many sign-in attempts. Try again in one minute.")
        attempts.append(stamp)
        if not hmac.compare_digest(body.token.encode(),token.encode()): raise HTTPException(401,"Invalid access key")
        return set_session(JSONResponse({"ok":True}))
    @app.get("/api/session")
    async def session(): return {"ok":True,"mode":"hosted" if deployment else "local"}
    @app.delete("/api/session")
    async def sign_out():
        response=JSONResponse({"ok":True})
        response.delete_cookie("parallax_session",secure=bool(deployment),httponly=True,samesite="strict")
        return response
    @app.get("/api/deployment")
    async def deployment_status():
        from .assessment import execution_capability
        return {"mode":"hosted" if deployment else "local","execution":execution_capability()}
    @app.get("/api/executors")
    async def executors():
        return hub.workers() if hub else []
    @app.post("/api/executors/pair")
    async def pair_worker():
        if not hub: raise HTTPException(404)
        return hub.pair()
    @app.delete("/api/executors/{identifier}")
    async def revoke_worker(identifier:str):
        if not hub: raise HTTPException(404)
        return hub.revoke(identifier)
    @app.post("/api/worker/connect")
    async def connect_worker(body:WorkerConnect):
        if not hub: raise HTTPException(404)
        if any(len(path)>4096 or not Path(path).is_absolute() for path in body.workspaces):
            raise ValueError("Worker projects must be absolute paths")
        return hub.connect(body.code,body.name,{"platform":body.platform,"workspaces":body.workspaces})
    @app.get("/api/worker/next")
    async def next_worker(request:Request):
        if not hub: raise HTTPException(404)
        return hub.pending(request.state.worker)
    @app.post("/api/worker/reply")
    async def reply_worker(body:WorkerReply,request:Request):
        if not hub: raise HTTPException(404)
        return hub.complete(request.state.worker,body.id,body.model_dump(exclude={"id"}))
    @app.post("/api/worker/sync")
    async def sync_worker(body:WorkerSync,request:Request):
        if not hub: raise HTTPException(404)
        return hub.sync(request.state.worker,[r.model_dump() for r in body.runs],[e.model_dump() for e in body.events])
    @app.api_route("/api/executors/{identifier}/proxy/{path:path}", methods=["GET","POST","PUT","DELETE"])
    async def worker_proxy(identifier:str,path:str,request:Request):
        if not hub: raise HTTPException(404)
        hub.worker(identifier)
        if request.method=="GET" and re.fullmatch(r"runs/[a-f0-9-]{36}/events",path):
            try: cursor=max(0,int(request.query_params.get("cursor","0")),int(request.headers.get("last-event-id","0")))
            except ValueError: raise HTTPException(400,"Invalid event cursor")
            async def replay():
                position=cursor
                while not await request.is_disconnected():
                    hub.worker(identifier)
                    for event in hub.events(identifier,path.split('/')[1],position):
                        position=event["sequence"]
                        yield f"id: {position}\ndata: {json.dumps(event)}\n\n"
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1)
            return StreamingResponse(replay(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})
        raw=await request.body()
        if len(raw)>MAX_MESSAGE: raise HTTPException(413,"Worker request exceeds limit")
        try: body=json.loads(raw) if raw else None
        except ValueError: raise HTTPException(400,"Invalid JSON body")
        reply=await hub.request(identifier,request.method,"/api/"+path,str(request.query_params),body)
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
            position=cursor
            while not await request.is_disconnected():
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
