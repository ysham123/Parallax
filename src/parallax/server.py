"""Authenticated loopback API and packaged Studio."""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from .engine import Engine
from .models import RunSpec, ProjectProfile, Participant
from .recovery import RecoveryRequest, AlphaFeedback, recovery_options, save_feedback, save_baseline_feedback, export_feedback
from .connections import ConnectionInput
from .store import Store
from .receipt import get_receipt

class AssessmentRequest(ProjectProfile):
    participants: list[Participant] = Field(default_factory=list)

class Steering(BaseModel):
    message: str = Field(min_length=1,max_length=20000)

def create_app(store:Store|None=None, registry=None, *, token:str|None=None, workspace:str|None=None):
    store=store or Store()
    engine=Engine(store,registry)
    token=token or secrets.token_urlsafe(32)
    def session_valid(value):
        try:
            identifier,stamp,signature=value.split(".")
            age=time.time()-int(stamp)
            expected=hmac.new(token.encode(),(identifier+"."+stamp).encode(),"sha256").hexdigest()
            return 0<=age<=86400 and hmac.compare_digest(signature,expected)
        except (AttributeError,ValueError): return False
    static=Path(__file__).parent/"static"
    @asynccontextmanager
    async def lifespan(app):
        engine.recover()
        await engine.reconcile_children()
        yield
        await engine.shutdown()
    app=FastAPI(title="Parallax",version="1.1.0",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=engine;app.state.token=token;app.state.store=store

    @app.middleware("http")
    async def guard(request:Request,call_next):
        host=request.headers.get("host","").split(":")[0]
        if host not in {"127.0.0.1","localhost","testserver"}:
            return JSONResponse({"detail":"Loopback Host required"},status_code=403)
        origin=request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail":"Cross-origin requests are not allowed"},status_code=403)
        if request.url.path=="/api/health":
            return await call_next(request)
        bearer=request.headers.get("authorization","").removeprefix("Bearer ")
        authorized=session_valid(request.cookies.get("parallax_session")) or (bool(bearer) and hmac.compare_digest(bearer,token))
        presented=request.query_params.get("token","")
        if request.url.path=="/" and presented and hmac.compare_digest(presented,token):
            session=secrets.token_urlsafe(32)+"."+str(int(time.time()))
            session+="."+hmac.new(token.encode(),session.encode(),"sha256").hexdigest()
            selected=request.query_params.get("workspace","")
            destination="/?"+urlencode({"workspace":selected}) if selected and len(selected)<=4096 else "/"
            response=RedirectResponse(destination,status_code=303)
            response.set_cookie("parallax_session",session,httponly=True,samesite="strict",max_age=86400)
            response.headers["Referrer-Policy"]="no-referrer"
            response.headers["Cache-Control"]="no-store"
            return response
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
        await engine.validate_settings(spec)
        store.put_profile(name,spec.model_dump())
        return {"name":name,"spec":spec.model_dump()}
    @app.delete("/api/profiles/{name}")
    async def remove_profile(name:str): store.delete_profile(name);return {"ok":True}
    @app.post("/api/project/assess")
    async def assess(body:AssessmentRequest):
        return await engine.assess(body.workspace,body.package_roots,body.checks,body.participants)
    @app.get("/api/project-profiles")
    async def project_profiles(): return store.project_profiles()
    @app.put("/api/project-profiles/{name}")
    async def project_profile(name:str,body:ProjectProfile):
        assessment=await engine.assess(body.workspace,body.package_roots,body.checks)
        store.put_project_profile(name,body.model_dump())
        return {"name":name,"profile":body.model_dump(),"assessment":assessment}
    @app.delete("/api/project-profiles/{name}")
    async def remove_project_profile(name:str): store.delete_project_profile(name);return {"ok":True}
    @app.post("/api/feedback/baseline")
    async def baseline_feedback(body:AlphaFeedback): return save_baseline_feedback(store,body)
    @app.get("/api/feedback/export")
    async def feedback_export():
        return JSONResponse(export_feedback(store),headers={"Content-Disposition":"attachment; filename=parallax-alpha-metrics.json"})
    @app.get("/api/runs/{run_id}/recovery")
    async def recovery(run_id:str): return recovery_options(store.get(run_id))
    @app.post("/api/runs/{run_id}/recover")
    async def recover(run_id:str,body:RecoveryRequest): return engine.recover_run(run_id,body.action)
    @app.post("/api/runs/{run_id}/feedback")
    async def feedback(run_id:str,body:AlphaFeedback): return save_feedback(store,run_id,body)
    @app.get("/api/runs")
    async def runs(): return store.runs()
    @app.post("/api/runs")
    async def start(spec:RunSpec): return await engine.start(spec)
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
    async def steer(run_id:str,body:Steering): return engine.steer(run_id,body.message)
    @app.post("/api/runs/{run_id}/{operation}")
    async def control(run_id:str,operation:str): return engine.control(run_id,operation)
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
    @app.get("/{path:path}")
    async def studio(path:str):
        requested=(static/path).resolve()
        if not requested.is_relative_to(static.resolve()): raise HTTPException(404)
        if requested.is_file(): return FileResponse(requested)
        if (static/"index.html").exists(): return FileResponse(static/"index.html")
        return JSONResponse({"detail":"Studio assets are missing. Run the frontend build or reinstall the release."},status_code=503)
    return app
