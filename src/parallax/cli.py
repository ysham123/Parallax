"""CLI and stdio MCP facade over the same persistent loopback runtime."""
from __future__ import annotations
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .models import RunSpec, ProjectProfile
from .store import Store, state_directory

def _request(endpoint,method,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(endpoint["url"]+path,data=data,method=method,headers={"Authorization":"Bearer "+endpoint["token"],"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(request,timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try: detail=json.load(exc).get("detail",str(exc))
        except ValueError: detail=str(exc)
        raise ValueError(str(detail)) from exc

def service(workspace:str|None=None):
    home=state_directory();home.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=home/"server.json"
    try:
        endpoint=json.loads(descriptor.read_text())
        if _request(endpoint,"GET","/api/health")["version"]=="1.1.0": return endpoint
    except (OSError,ValueError,KeyError,urllib.error.URLError): pass
    import fcntl
    with (home/"launch.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            endpoint=json.loads(descriptor.read_text())
            if _request(endpoint,"GET","/api/health")["version"]=="1.1.0": return endpoint
        except (OSError,ValueError,KeyError,urllib.error.URLError): pass
        with (home/"runtime.log").open("a") as log:
            env=os.environ.copy()
            env["PYTHONPATH"]=str(Path(__file__).resolve().parent.parent)
            subprocess.Popen([sys.executable,"-m","parallax.cli","serve","--workspace",workspace or os.getcwd()],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        for _ in range(100):
            time.sleep(.1)
            try:
                endpoint=json.loads(descriptor.read_text())
                if _request(endpoint,"GET","/api/health")["version"]=="1.1.0": return endpoint
            except (OSError,ValueError,KeyError,urllib.error.URLError): pass
        raise ValueError(f"Runtime did not start. Inspect {home/'runtime.log'}")

def serve(workspace):
    import uvicorn
    from .server import create_app
    home=state_directory();home.mkdir(parents=True,exist_ok=True,mode=0o700)
    import fcntl
    runtime_lock=(home/"runtime.lock").open("a")
    try: fcntl.flock(runtime_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        runtime_lock.close()
        raise ValueError("A Parallax runtime already owns this state directory")
    path=home/"server.json"
    try: previous=json.loads(path.read_text())
    except (OSError,ValueError): previous={}
    token=previous.get("token") or secrets.token_urlsafe(32)
    preferred=urllib.parse.urlsplit(previous.get("url","")).port or 0
    listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try: listener.bind(("127.0.0.1",preferred))
    except OSError: listener.bind(("127.0.0.1",0))
    listener.listen(128)
    port=listener.getsockname()[1]
    endpoint={"url":f"http://127.0.0.1:{port}","token":token,"pid":os.getpid(),"workspace":workspace,"version":"1.1.0"}
    temporary=home/"server.json.tmp";temporary.write_text(json.dumps(endpoint));temporary.chmod(0o600);temporary.replace(path)
    try:
        uvicorn.run(create_app(token=token,workspace=workspace),log_level="warning",access_log=False,
                    fd=listener.fileno(),timeout_graceful_shutdown=3)
    finally:
        listener.close()
        runtime_lock.close()

def invoke(name,args):
    endpoint=service(args.get("workspace"))
    if name=="doctor": return _request(endpoint,"GET","/api/providers")
    if name=="models":
        query=urllib.parse.urlencode({k:args[k] for k in ("transport","connection_id") if args.get(k)})
        return _request(endpoint,"GET","/api/models/"+urllib.parse.quote(args["provider"],safe="")+("?"+query if query else ""))
    if name=="connections": return _request(endpoint,"GET","/api/connections")
    if name=="save_connection": return _request(endpoint,"PUT","/api/connections/"+urllib.parse.quote(args["id"],safe=""),args["config"])
    if name=="test_connection": return _request(endpoint,"POST","/api/connections/"+urllib.parse.quote(args["id"],safe="")+"/test")
    if name=="delete_connection": return _request(endpoint,"DELETE","/api/connections/"+urllib.parse.quote(args["id"],safe=""))
    if name=="profiles": return _request(endpoint,"GET","/api/profiles")
    if name=="save_profile": return _request(endpoint,"PUT","/api/profiles/"+urllib.parse.quote(args["name"],safe=""),RunSpec.model_validate(args["spec"]).model_dump())
    if name=="assess_project": return _request(endpoint,"POST","/api/project/assess",{k:v for k,v in args.items() if k in {"workspace","package_roots","checks","participants"}})
    if name=="project_profiles": return _request(endpoint,"GET","/api/project-profiles")
    if name=="save_project_profile": return _request(endpoint,"PUT","/api/project-profiles/"+urllib.parse.quote(args["name"],safe=""),ProjectProfile.model_validate(args["profile"]).model_dump())
    if name=="delete_project_profile": return _request(endpoint,"DELETE","/api/project-profiles/"+urllib.parse.quote(args["name"],safe=""))
    if name=="get_recovery": return _request(endpoint,"GET","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/recovery")
    if name=="recover_run": return _request(endpoint,"POST","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/recover",{"action":args["action"]})
    if name=="record_feedback": return _request(endpoint,"POST","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/feedback",args["feedback"])
    if name=="record_baseline_feedback": return _request(endpoint,"POST","/api/feedback/baseline",args["feedback"])
    if name=="export_feedback": return _request(endpoint,"GET","/api/feedback/export")
    if name=="start_run": return _request(endpoint,"POST","/api/runs",RunSpec.model_validate(args["spec"]).model_dump())
    if name=="get_run": return _request(endpoint,"GET","/api/runs/"+urllib.parse.quote(args["run_id"],safe=""))
    if name=="get_receipt": return _request(endpoint,"GET","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/receipt")
    if name=="list_runs": return _request(endpoint,"GET","/api/runs")
    if name in {"pause","cancel","resume"}: return _request(endpoint,"POST","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/"+name)
    if name=="steer": return _request(endpoint,"POST","/api/runs/"+urllib.parse.quote(args["run_id"],safe="")+"/steer",{"message":args["message"]})
    if name=="studio":
        workspace=args.get("workspace") or endpoint["workspace"]
        return {"url":endpoint["url"]+"/?"+urllib.parse.urlencode({"token":endpoint["token"],"workspace":workspace}),"workspace":workspace,"version":"1.1.0"}
    raise ValueError("Unknown operation")

def _schema(properties=None,required=None):
    return {"type":"object","properties":properties or {},"required":required or [],"additionalProperties":False}

def mcp_tools():
    text={"type":"string"};run_id=_schema({"run_id":text},["run_id"])
    spec_schema=RunSpec.model_json_schema()
    definitions_schema=spec_schema.pop("$defs",{})
    def spec_input(extra=None,required=None):
        value=_schema({**(extra or {}),"spec":spec_schema},required or ["spec"])
        value["$defs"]=definitions_schema
        return value
    from .server import AssessmentRequest
    from .recovery import AlphaFeedback
    def nested_schema(name,model,extra,required):
        definition=model.model_json_schema();defs=definition.pop("$defs",{})
        schema=_schema({**extra,name:definition},required)
        if defs: schema["$defs"]=defs
        return schema
    assessment_schema=AssessmentRequest.model_json_schema()
    definitions=[
        ("assess_project","Inspect project readiness, packages, checks and execution isolation without running project code.",assessment_schema),
        ("project_profiles","List reusable project package roots and check commands.",_schema()),
        ("save_project_profile","Save a reusable project profile without weakening an existing run.",nested_schema("profile",ProjectProfile,{"name":text},["name","profile"])),
        ("delete_project_profile","Delete a saved project profile; run specifications remain unchanged.",_schema({"name":text},["name"])),
        ("get_recovery","Read contextual recovery actions for retained run evidence.",run_id),
        ("recover_run","Resume with recorded failure evidence after process and action reconciliation.",_schema({"run_id":text,"action":{"enum":["retry_interrupted","repair_candidate"]}},["run_id","action"])),
        ("record_feedback","Opt in to local bounded alpha metrics. No automatic sharing.",nested_schema("feedback",AlphaFeedback,{"run_id":text},["run_id","feedback"])),
        ("record_baseline_feedback","Record local single-Codex comparison metrics without a Parallax run or source data.",nested_schema("feedback",AlphaFeedback,{},["feedback"])),
        ("export_feedback","Export opt-in aggregate alpha metrics without prompts, code, paths or sessions.",_schema()),
        ("doctor","Inspect local provider executables, login state and capabilities.",_schema()),
        ("models","Discover a CLI or API model and effort catalog.",_schema({"provider":text,"transport":{"type":"string","enum":["cli","api"]},"connection_id":text},["provider"])),
        ("connections","Inspect CLI and API connections without exposing credentials.",_schema()),
        ("test_connection","Authenticate and discover account models without inference.",_schema({"id":text},["id"])),
        ("profiles","List saved team profiles.",_schema()),
        ("save_profile","Save an explicitly selected team profile.",spec_input({"name":text},["name","spec"])),
        ("start_run","Start a requested Parallax team run in a local project.",spec_input()),
        ("get_run","Read run status, evidence, changes and effective settings.",run_id),
        ("get_receipt","Export a verification record with integration gates and evidence hashes, without prompts or raw sessions.",run_id),
        ("list_runs","List recent local team runs.",_schema()),
        ("pause","Pause new assignments after active work finishes.",run_id),
        ("cancel","Stop managed processes and preserve partial work.",run_id),
        ("resume","Resume a paused or interrupted run after reconciliation.",run_id),
        ("steer","Add instructions to an active run's next checkpoint.",_schema({"run_id":text,"message":text},["run_id","message"])),
        ("studio","Return an authenticated local Studio URL for this project.",_schema({"workspace":text})),
    ]
    return [{"name":"parallax_"+name,"description":description,"inputSchema":schema,
        "annotations":{"readOnlyHint":name in {"doctor","models","connections","profiles","get_run","get_receipt","list_runs","assess_project","project_profiles","get_recovery","export_feedback"},"openWorldHint":name=="test_connection"}}
        for name,description,schema in definitions]

def mcp():
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if "id" not in request: continue
            method=request.get("method");params=request.get("params",{})
            if method=="initialize":
                result={"protocolVersion":params.get("protocolVersion","2024-11-05"),"capabilities":{"tools":{}},"serverInfo":{"name":"parallax","version":"1.1.0"}}
            elif method=="ping": result={}
            elif method=="tools/list": result={"tools":mcp_tools()}
            elif method=="tools/call":
                try:
                    name=params["name"]
                    if name not in {tool["name"] for tool in mcp_tools()}: raise ValueError("Unknown Parallax tool")
                    output=invoke(name.removeprefix("parallax_"),params.get("arguments",{}))
                    result={"content":[{"type":"text","text":json.dumps(output,ensure_ascii=False)}],"isError":False}
                except Exception as exc:
                    result={"content":[{"type":"text","text":str(exc)}],"isError":True}
            else:
                print(json.dumps({"jsonrpc":"2.0","id":request["id"],"error":{"code":-32601,"message":"Unknown method"}}),flush=True);continue
            print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}),flush=True)
        except (ValueError,KeyError,TypeError):
            print(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Invalid JSON-RPC request"}}),flush=True)

def main():
    parser=argparse.ArgumentParser(description="Parallax Constellation local coding teams")
    parser.add_argument("--version",action="version",version="Parallax 1.1.0 Constellation")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("doctor");models=sub.add_parser("models");models.add_argument("provider");models.add_argument("--transport",choices=["cli","api"],default="cli");models.add_argument("--connection-id")
    sub.add_parser("connections")
    connect=sub.add_parser("connect");connect.add_argument("id");connect.add_argument("--spec",type=Path,required=True)
    for name in ("test-connection","delete-connection"):
        connection=sub.add_parser(name);connection.add_argument("id")
    studio=sub.add_parser("studio");studio.add_argument("--workspace",default=os.getcwd())
    server=sub.add_parser("serve");server.add_argument("--workspace",default=os.getcwd())
    sub.add_parser("mcp");sub.add_parser("history")
    profile=sub.add_parser("profiles");profile.add_argument("--save");profile.add_argument("--spec",type=Path)
    assessment=sub.add_parser("assess");assessment.add_argument("--workspace",default=os.getcwd());assessment.add_argument("--package-root",action="append",dest="package_roots",default=[]);assessment.add_argument("--spec",type=Path)
    project_profile=sub.add_parser("project-profiles");project_profile.add_argument("--save");project_profile.add_argument("--delete");project_profile.add_argument("--spec",type=Path)
    recovery=sub.add_parser("recover");recovery.add_argument("run_id");recovery.add_argument("--action",choices=["retry_interrupted","repair_candidate"])
    feedback=sub.add_parser("feedback");feedback.add_argument("--run-id");feedback.add_argument("--spec",type=Path);feedback.add_argument("--export",action="store_true");feedback.add_argument("--baseline",action="store_true")
    run=sub.add_parser("run");run.add_argument("--spec",type=Path);run.add_argument("--workspace",default=os.getcwd());run.add_argument("--prompt-file",type=Path);run.add_argument("--mode",choices=["review","build","compare"],default="build");run.add_argument("--profile");run.add_argument("--wait",action="store_true")
    for operation in ("status","receipt","pause","cancel","resume"):
        command=sub.add_parser(operation);command.add_argument("run_id")
    steer=sub.add_parser("steer");steer.add_argument("run_id");steer.add_argument("--message",required=True)
    args=parser.parse_args()
    try:
        if args.command=="serve": serve(args.workspace);return
        if args.command=="mcp": mcp();return
        if args.command=="run":
            if args.spec: spec=RunSpec.model_validate_json(args.spec.read_text())
            else:
                saved=next((p["spec"] for p in invoke("profiles",{}) if p["name"]==args.profile),{}) if args.profile else {}
                prompt=args.prompt_file.read_text() if args.prompt_file else sys.stdin.read()
                spec=RunSpec.model_validate({**saved,"workspace":args.workspace,"prompt":prompt,"mode":args.mode})
            output=invoke("start_run",{"spec":spec.model_dump()})
            if args.wait:
                while output["status"] not in {"completed","failed","cancelled","needs_attention","paused","interrupted"}:
                    time.sleep(1);output=invoke("get_run",{"run_id":output["run_id"]})
        elif args.command=="profiles" and args.save:
            if not args.spec: raise ValueError("--save requires --spec")
            output=invoke("save_profile",{"name":args.save,"spec":json.loads(args.spec.read_text())})
        elif args.command=="assess":
            body=json.loads(args.spec.read_text()) if args.spec else {"workspace":args.workspace,"package_roots":args.package_roots}
            output=invoke("assess_project",body)
        elif args.command=="project-profiles":
            if args.save:
                if not args.spec: raise ValueError("--save requires --spec")
                output=invoke("save_project_profile",{"name":args.save,"profile":json.loads(args.spec.read_text())})
            elif args.delete: output=invoke("delete_project_profile",{"name":args.delete})
            else: output=invoke("project_profiles",{})
        elif args.command=="recover":
            output=invoke("recover_run" if args.action else "get_recovery",vars(args))
        elif args.command=="feedback":
            if args.export: output=invoke("export_feedback",{})
            elif args.baseline:
                if not args.spec: raise ValueError("--baseline requires --spec")
                output=invoke("record_baseline_feedback",{"feedback":json.loads(args.spec.read_text())})
            else:
                if not args.spec or not args.run_id: raise ValueError("Feedback requires --run-id and --spec, or --export")
                output=invoke("record_feedback",{"run_id":args.run_id,"feedback":json.loads(args.spec.read_text())})
        elif args.command=="connect":
            output=invoke("save_connection",{"id":args.id,"config":json.loads(args.spec.read_text())})
        else:
            name={"status":"get_run","receipt":"get_receipt","history":"list_runs","test-connection":"test_connection","delete-connection":"delete_connection"}.get(args.command,args.command)
            output=invoke(name,vars(args))
        print(json.dumps(output,ensure_ascii=False,indent=2))
    except (ValueError,OSError,urllib.error.URLError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)}),file=sys.stderr);raise SystemExit(1)

if __name__=="__main__": main()
