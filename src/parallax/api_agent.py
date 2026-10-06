"""Bounded API coding agent. The runtime, not the model, owns filesystem tools."""
from __future__ import annotations
import asyncio
import fnmatch
import fcntl
import hashlib
import hmac
import inspect
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
import httpx

TOOL_SCHEMAS={
    "list_files":{"type":"object","properties":{},"required":[],"additionalProperties":False},
    "read_file":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False},
    "write_file":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False},
    "run_command":{"type":"object","properties":{"argv":{"type":"array","items":{"type":"string"},"minItems":1}},"required":["argv"],"additionalProperties":False},
}
DESCRIPTIONS={"list_files":"List non-secret project files in your isolated workspace.","read_file":"Read a UTF-8 file within the isolated project.","write_file":"Write a UTF-8 file within your assigned ownership.","run_command":"Run a supported project verification command in a sandbox. No shell strings."}
BLOCKED={".git",".parallax-home",".parallax-api",".ssh",".aws",".config",".grok",".claude",".codex",".netrc",".npmrc",".pypirc","node_modules",".venv","__pycache__"}
MAX_JOURNAL=16_000_000

async def _bounded_json(client,method,url,*,headers,limit,timeout,body=None):
    """Cap decompressed response bytes while reading, including supplied clients."""
    async with client.stream(method,url,headers=headers,json=body,timeout=timeout,follow_redirects=False) as response:
        if response.status_code>=300: return response.status_code,None
        content=bytearray()
        async for chunk in response.aiter_bytes(65536):
            if len(content)+len(chunk)>limit: raise ApiFailure("malformed_stream","API response exceeds the size limit")
            content.extend(chunk)
        try: return response.status_code,json.loads(content)
        except (ValueError,UnicodeError) as exc: raise ApiFailure("malformed_stream","API response is not valid JSON") from exc

def _validate_schema(value,schema,root=None,depth=0):
    """Validate the JSON Schema subset emitted by runtime Pydantic contracts."""
    root=root or schema
    if depth>64: raise ValueError("Structured output nesting exceeds the limit")
    if "$ref" in schema:
        if not schema["$ref"].startswith("#/"): raise ValueError("External schema references are unsupported")
        target=root
        for part in schema["$ref"][2:].split("/"): target=target[part.replace("~1","/").replace("~0","~")]
        return _validate_schema(value,target,root,depth+1)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try: _validate_schema(value,option,root,depth+1);return
            except ValueError: pass
        raise ValueError("Structured output does not match an allowed type")
    types={"object":dict,"array":list,"string":str,"boolean":bool,"integer":int,"number":(int,float),"null":type(None)}
    kind=schema.get("type")
    if kind and (not isinstance(value,types[kind]) or kind in {"integer","number"} and isinstance(value,bool)):
        raise ValueError("Structured output has an invalid value type")
    if "enum" in schema and value not in schema["enum"]: raise ValueError("Structured output has an unsupported value")
    if isinstance(value,dict):
        props=schema.get("properties",{})
        if any(k not in value for k in schema.get("required",[])): raise ValueError("Structured output is missing a required field")
        if schema.get("additionalProperties") is False and set(value)-set(props): raise ValueError("Structured output contains unknown fields")
        for name,item in value.items():
            if name in props: _validate_schema(item,props[name],root,depth+1)
    elif isinstance(value,list):
        if len(value)<schema.get("minItems",0) or len(value)>schema.get("maxItems",10000): raise ValueError("Structured output array length is invalid")
        for item in value: _validate_schema(item,schema.get("items",{}),root,depth+1)
    elif isinstance(value,str):
        if len(value)<schema.get("minLength",0) or len(value)>schema.get("maxLength",8_000_000): raise ValueError("Structured output string length is invalid")
        if "pattern" in schema and re.search(schema["pattern"],value) is None: raise ValueError("Structured output string does not match the required format")
    elif isinstance(value,(int,float)) and not isinstance(value,bool):
        if value<schema.get("minimum",float("-inf")) or value>schema.get("maximum",float("inf")): raise ValueError("Structured output number is outside its bounds")

def _save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    encoded=json.dumps(data,allow_nan=False).encode()
    if len(encoded)>MAX_JOURNAL: raise ApiFailure("session_size_limit","API session journal exceeds its size limit")
    descriptor,temporary=tempfile.mkstemp(prefix=".journal-",dir=path.parent)
    try:
        with os.fdopen(descriptor,"wb") as handle: handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def _path(root,name):
    if not isinstance(name,str) or not name or "\0" in name: raise ValueError("File path must be a nonempty string")
    relative=Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or any(p.casefold() in BLOCKED or p.casefold().startswith(".env") or p.casefold()==".parallax-owned" for p in relative.parts):
        raise ValueError("File path is outside the readable project scope")
    target=root
    for part in relative.parts:
        target=target/part
        if target.is_symlink(): raise ValueError("Symlink paths are outside API tool scope")
    target=target.resolve()
    if not target.is_relative_to(root.resolve()): raise ValueError("Symlink escapes the isolated workspace")
    return target

def _directory(root,parts,*,create=False):
    """Open every parent relative to its descriptor; never follow a swapped link."""
    descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                try: os.mkdir(part,0o755,dir_fd=descriptor)
                except FileExistsError: pass
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        return descriptor
    except BaseException: os.close(descriptor);raise

class ApiAgent:
    def __init__(self,home:Path,client=None): self.home=home;self.client=client
    async def run(self,config,*,session_id=None,**kwargs):
        identifier=session_id or "api-"+str(uuid.uuid4())
        try:
            if not identifier.startswith("api-") or str(uuid.UUID(identifier[4:]))!=identifier[4:]: raise ValueError
        except (ValueError,AttributeError): raise ValueError("Invalid API session id")
        folder=self.home/"api-sessions";folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        descriptor=os.open(folder/(identifier+".lock"),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try: fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError("API session is already active; concurrent continuation is unsupported")
            return await self._run_session(config,identifier=identifier,session_id=session_id,**kwargs)
        finally: os.close(descriptor)
    async def _run_session(self,config,*,identifier,key,effective,workspace,prompt,model=None,effort=None,mode="consult",session_id=None,timeout=600,schema=None,on_event=None,cancel_event=None,allowed_files=None):
        workspace=Path(workspace).resolve()
        marker=workspace/".parallax-owned"
        if not marker.is_file() or marker.is_symlink(): raise ValueError("API agents require a runtime-owned workspace")
        if not isinstance(key,str) or not key or any(ord(c)<32 or ord(c)==127 for c in key): raise ValueError("Invalid or missing API credentials")
        if not isinstance(prompt,str) or len(prompt.encode())>1_000_000: raise ValueError("API prompt exceeds its size limit")
        if mode not in {"consult","coordinate","edit"}: raise ValueError("Unsupported API agent mode")
        requested={"model":model,"effort":effort,"transport":"api","connection_id":config["id"]}
        identity={"connection_id":config["id"],"provider":config["provider"],"protocol":config["protocol"],"model":effective["model"],"effort":effective["effort"],"endpoint":config["endpoint"],"workspace":str(workspace),"mode":mode,
                  "credential_version":config.get("credential_version"),"allowed_files":sorted(allowed_files or []),"schema":hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest()}
        path=self.home/"api-sessions"/(identifier+".json")
        if session_id:
            try:
                if path.is_symlink() or path.stat().st_size>MAX_JOURNAL: raise ValueError
                state=json.loads(path.read_text())
                if not isinstance(state,dict) or not isinstance(state.get("history"),list) or not isinstance(state.get("tools"),dict) or not isinstance(state.get("usage"),list) or not isinstance(state.get("identity"),dict) or not isinstance(state.get("answer"),str): raise ValueError
                if not isinstance(state.get("turns",0),int) or isinstance(state.get("turns",0),bool) or not 0<=state.get("turns",0)<=32: raise ValueError
                if any(not isinstance(t,dict) or t.get("status") not in {"issued","completed"} for t in state["tools"].values()): raise ValueError
                if not isinstance(state.get("credential_nonce"),str) or not isinstance(state.get("credential_binding"),str) or not re.fullmatch(r"[a-f0-9]{64}",state["credential_binding"]): raise ValueError
            except (OSError,ValueError,TypeError): raise ValueError("API session journal is missing or unreadable")
            if state["identity"]!=identity: raise ValueError("API resume settings or workspace differ from the saved session")
            binding=hmac.new(str(state.get("credential_nonce","")).encode(),key.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(binding,state.get("credential_binding","")): raise ValueError("API credentials changed since this session; start a new session")
            if any(t["status"]=="issued" for t in state["tools"].values()):
                return {"ok":False,"provider":config["provider"],"session_id":identifier,"requested_settings":requested,"effective_settings":effective,"error":{"code":"tool_reconciliation_required","message":"An interrupted tool has an unknown result; inspect the workspace before retrying"},"partial_output":state.get("answer","")}
            # Recover the old completion/save window without repeating the tool.
            known=self._result_ids(config["protocol"],state["history"])
            for tool_id,tool in state["tools"].items():
                if tool_id not in known:
                    if not isinstance(tool.get("call"),dict) or not isinstance(tool.get("output"),dict): raise ValueError("API tool journal is unreadable")
                    state["history"].append(self._tool_result(config["protocol"],tool["call"],tool["output"]))
        else:
            nonce=str(uuid.uuid4())
            state={"identity":identity,"history":[],"tools":{},"usage":[],"answer":"","turns":0,"credential_nonce":nonce,"credential_binding":hmac.new(nonce.encode(),key.encode(),hashlib.sha256).hexdigest()}
        if cancel_event is not None and cancel_event.is_set(): raise asyncio.CancelledError
        state["history"].append({"role":"user","content":prompt})
        _save(path,state)
        async def emit(event):
            if on_event:
                returned=on_event(event)
                if inspect.isawaitable(returned): await returned
        await emit({"type":"api.session","session_id":identifier,"effective_settings":effective})
        async def execute():
            owned_client=self.client is None
            client=self.client or httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False)
            try:
                while state.get("turns",0)<32:
                    if cancel_event is not None and cancel_event.is_set(): raise asyncio.CancelledError
                    state["turns"]=state.get("turns",0)+1;_save(path,state)
                    await emit({"type":"api.request","turn":state["turns"],"connection_id":config["id"],"model":effective["model"]})
                    body,headers,route=self._request(config,key,effective,state["history"],mode,schema)
                    status,data=await _bounded_json(client,"POST",config["endpoint"]+route,headers=headers,body=body,limit=8_000_000,timeout=timeout)
                    if status>=300:
                        code="authentication_failed" if status in {401,403} else "api_request_failed"
                        raise ApiFailure(code,f"API returned HTTP {status}; check credentials, model access and endpoint settings")
                    try: answer,calls,history=self._response(config["protocol"],data)
                    except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc: raise ApiFailure("malformed_stream","API response does not match its configured protocol") from exc
                    if isinstance(data.get("usage"),dict):
                        usage={k:v for k,v in data["usage"].items() if isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<10**15}
                        if usage: state["usage"].append(usage)
                    fresh=set()
                    for call in calls:
                        if call["name"]=="finish": continue
                        previous=state["tools"].get(call["id"])
                        if previous and previous.get("call")!=call: raise ApiFailure("duplicate_action","A tool id was reused with different arguments")
                        if previous and previous.get("status")!="completed": raise ApiFailure("tool_reconciliation_required","Interrupted command cannot be repeated automatically")
                        if previous is None:
                            if len(state["tools"])>=512: raise ApiFailure("agent_tool_limit","API session reached its tool limit")
                            state["tools"][call["id"]]={"call":call,"status":"issued"};fresh.add(call["id"])
                    state["history"].extend(history);state["answer"]=answer or state["answer"]
                    _save(path,state)
                    if answer: await emit({"type":"api.message","text":answer[:16000]})
                    if not calls:
                        if schema:
                            try: structured=json.loads(answer);_validate_schema(structured,schema)
                            except ValueError: raise ApiFailure("invalid_structured_output","API did not return the requested action schema")
                        else: structured=None
                        return answer,structured
                    for call in calls:
                        if call["name"]=="finish":
                            if not schema or len(calls)!=1: raise ApiFailure("invalid_structured_output","Finish requires the requested schema and cannot be combined with filesystem actions")
                            try: _validate_schema(call["arguments"],schema)
                            except ValueError: raise ApiFailure("invalid_structured_output","API did not return the requested action schema")
                            state["answer"]=json.dumps(call["arguments"])
                            state["history"].append(self._tool_result(config["protocol"],call,{"ok":True,"accepted":True}))
                            _save(path,state)
                            return state["answer"],call["arguments"]
                        identifier_tool=call["id"]
                        if identifier_tool not in fresh:
                            previous=state["tools"][identifier_tool]
                            if previous["call"]!=call: raise ApiFailure("duplicate_action","A tool id was reused with different arguments")
                            if previous["status"]!="completed": raise ApiFailure("tool_reconciliation_required","Interrupted command cannot be repeated automatically")
                            output=previous["output"]
                        else:
                            await emit({"type":"api.tool_started","name":call["name"],"call_id":identifier_tool,"path":call["arguments"].get("path")})
                            try: output=await self._tool(workspace,call["name"],call["arguments"],mode,allowed_files,cancel_event,emit)
                            except ValueError as exc: output={"ok":False,"error":{"code":"permission_denied","message":str(exc)}}
                            state["tools"][identifier_tool].update(status="completed",output=output)
                        state["history"].append(self._tool_result(config["protocol"],call,output))
                        _save(path,state)
                        await emit({"type":"api.tool_finished","name":call["name"],"call_id":identifier_tool,"ok":output.get("ok",True)})
                raise ApiFailure("agent_turn_limit","API agent reached its 32-turn limit")
            finally:
                if owned_client: await client.aclose()
        task=asyncio.create_task(execute());watcher=None
        try:
            if cancel_event is not None:
                async def watch(): await cancel_event.wait();task.cancel()
                watcher=asyncio.create_task(watch())
            answer,structured=await asyncio.wait_for(task,timeout)
            outcome={"ok":True,"answer":answer,"structured_output":structured,"error":None}
        except asyncio.CancelledError:
            task.cancel();await asyncio.gather(task,return_exceptions=True);raise
        except (ApiFailure,httpx.HTTPError,asyncio.TimeoutError) as exc:
            outcome={"ok":False,"answer":state.get("answer",""),"structured_output":None,"error":{"code":exc.code if isinstance(exc,ApiFailure) else "api_unavailable","message":str(exc).replace(key,"[redacted]")[:1000]},"partial_output":state.get("answer","")}
        finally:
            if watcher: watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
        return {**outcome,"session_id":identifier,"provider":config["provider"],"requested_settings":requested,"effective_settings":effective,"usage":{"reports":state["usage"]} if state["usage"] else {},"exit_code":0 if outcome["ok"] else 1}
    def _request(self,config,key,effective,history,mode,schema):
        names=["list_files","read_file"]+(["write_file","run_command"] if mode=="edit" else [])
        tools=[{"name":n,"description":DESCRIPTIONS[n],"parameters":TOOL_SCHEMAS[n]} for n in names]
        if schema: tools.append({"name":"finish","description":"Return the final structured result matching this schema.","parameters":schema})
        instructions="You are a Parallax coding agent in an isolated workspace. Use only the provided tools. Do not start recursive agents, publish, deploy, or push. Read project instructions. Preserve existing changes. "
        if mode!="edit": instructions+="You have read-only tools. "
        if schema: instructions+="Conclude by calling finish with the required structured result. "
        protocol=config["protocol"];base={"model":effective["model"]}
        if protocol=="responses":
            body={**base,"instructions":instructions,"input":history,"tools":[{"type":"function",**t} for t in tools],"store":False,"max_output_tokens":8192}
            if effective["effort"]: body["reasoning"]={"effort":effective["effort"]}
            return body,{"Authorization":"Bearer "+key},"/responses"
        if protocol=="anthropic":
            body={**base,"system":instructions,"messages":history,"max_tokens":8192,"tools":[{"name":t["name"],"description":t["description"],"input_schema":t["parameters"]} for t in tools]}
            if effective["effort"]: body["output_config"]={"effort":effective["effort"]}
            return body,{"x-api-key":key,"anthropic-version":"2023-06-01"},"/messages"
        body={**base,"messages":[{"role":"system","content":instructions},*history],"tools":[{"type":"function","function":t} for t in tools]}
        if effective["effort"]: body["reasoning_effort"]=effective["effort"]
        return body,{"Authorization":"Bearer "+key},"/chat/completions"
    def _response(self,protocol,data):
        if not isinstance(data,dict): raise ValueError("Response must be an object")
        if protocol=="responses":
            if data.get("status") not in {None,"completed"}: raise ApiFailure("partial_response","API response is incomplete or failed")
            output=data["output"];answer="";calls=[]
            for item in output:
                if item["type"]=="message": answer+="".join(p.get("text","") for p in item["content"] if p.get("type")=="output_text")
                elif item["type"]=="function_call": calls.append({"id":item["call_id"],"name":item["name"],"arguments":json.loads(item["arguments"])})
            history=output
        elif protocol=="anthropic":
            if data.get("stop_reason") in {"max_tokens","refusal"}: raise ApiFailure("partial_response","API stopped before completing the agent turn")
            output=data["content"];answer="".join(p["text"] for p in output if p["type"]=="text")
            calls=[{"id":p["id"],"name":p["name"],"arguments":p["input"]} for p in output if p["type"]=="tool_use"]
            history=[{"role":"assistant","content":output}]
        else:
            choice=data["choices"][0]
            if choice.get("finish_reason") in {"length","content_filter"}: raise ApiFailure("partial_response","API stopped before completing the agent turn")
            message=data["choices"][0]["message"]
            if message.get("role") not in {None,"assistant"}: raise ValueError("Invalid assistant role")
            calls=[{"id":p["id"],"name":p["function"]["name"],"arguments":json.loads(p["function"]["arguments"])} for p in message.get("tool_calls",[])]
            answer=message.get("content") or "";history=[message]
        if not isinstance(answer,str) or not answer and not calls: raise ValueError("API response contains no assistant result")
        if len(calls)>64: raise ValueError("API response contains too many tool calls")
        seen=set()
        for call in calls:
            if not isinstance(call["id"],str) or not 1<=len(call["id"])<=200 or any(ord(c)<32 for c in call["id"]): raise ValueError("Invalid tool id")
            if call["id"] in seen: raise ValueError("Duplicate tool ids in one response")
            seen.add(call["id"])
            if not isinstance(call["name"],str) or not 1<=len(call["name"])<=64 or not isinstance(call["arguments"],dict): raise ValueError("Invalid tool name or argument object")
        return answer,calls,history
    def _result_ids(self,protocol,history):
        identifiers=set()
        for item in history:
            if not isinstance(item,dict): raise ValueError("API session history is unreadable")
            if protocol=="responses" and item.get("type")=="function_call_output": identifiers.add(item.get("call_id"))
            elif protocol=="openai" and item.get("role")=="tool": identifiers.add(item.get("tool_call_id"))
            elif protocol=="anthropic" and isinstance(item.get("content"),list):
                for block in item["content"]:
                    if isinstance(block,dict) and block.get("type")=="tool_result": identifiers.add(block.get("tool_use_id"))
        return identifiers
    def _tool_result(self,protocol,call,output):
        encoded=json.dumps(output)
        if protocol=="responses": return {"type":"function_call_output","call_id":call["id"],"output":encoded}
        if protocol=="anthropic": return {"role":"user","content":[{"type":"tool_result","tool_use_id":call["id"],"content":encoded}]}
        return {"role":"tool","tool_call_id":call["id"],"content":encoded}
    async def _tool(self,root,name,args,mode,allowed,cancel_event,emit):
        if name not in TOOL_SCHEMAS or not isinstance(args,dict): raise ValueError("Unknown tool or invalid arguments")
        _validate_schema(args,TOOL_SCHEMAS[name])
        if name=="list_files":
            files=[]
            for folder,dirs,names in os.walk(root,followlinks=False):
                dirs[:]=[d for d in dirs if d.casefold() not in BLOCKED and not d.casefold().startswith(".env") and not (Path(folder)/d).is_symlink()]
                for filename in names:
                    relative=str((Path(folder)/filename).relative_to(root))
                    try: _path(root,relative)
                    except ValueError: continue
                    files.append(relative)
                    if len(files)>=5000: return {"ok":True,"files":sorted(files),"truncated":True}
            return {"ok":True,"files":sorted(files)}
        if name in {"read_file","write_file"}:
            if not isinstance(args["path"],str): raise ValueError("Path must be a string")
            target=_path(root,args["path"])
            parts=target.relative_to(root.resolve()).parts
            if name=="read_file":
                try:
                    parent=_directory(root,parts[:-1])
                    try: descriptor=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                    finally: os.close(parent)
                    with os.fdopen(descriptor,"rb") as handle:
                        import stat
                        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode): raise ValueError("Only regular project files are readable")
                        data=handle.read(128001)
                    if len(data)>128000: raise ValueError("File exceeds the read limit")
                    return {"ok":True,"content":data.decode("utf-8")}
                except (OSError,UnicodeError) as exc: raise ValueError("File is missing or is not readable UTF-8") from exc
            if mode!="edit": raise ValueError("Read-only agents cannot write files")
            relative=target.relative_to(root.resolve()).as_posix()
            if not allowed or not any(relative==p.rstrip("/") or relative.startswith(p.rstrip("/")+"/") or fnmatch.fnmatchcase(relative,p) for p in allowed): raise ValueError("File is outside this task's ownership")
            if not isinstance(args["content"],str) or len(args["content"].encode())>256000: raise ValueError("Write exceeds the file size limit")
            parent=_directory(root,parts[:-1],create=True)
            temporary=".api-write-"+uuid.uuid4().hex
            try:
                descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                with os.fdopen(descriptor,"wb") as handle:
                    try:
                        import stat
                        previous=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
                        if not stat.S_ISREG(previous.st_mode): raise ValueError("Only regular project files can be written")
                        permissions=previous.st_mode&0o777
                    except FileNotFoundError: permissions=0o644
                    os.fchmod(handle.fileno(),permissions)
                    handle.write(args["content"].encode());handle.flush();os.fsync(handle.fileno())
                os.replace(temporary,parts[-1],src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
            finally:
                try: os.unlink(temporary,dir_fd=parent)
                except FileNotFoundError: pass
                os.close(parent)
            return {"ok":True,"path":relative}
        if mode!="edit": raise ValueError("Read-only agents cannot run commands")
        argv=args["argv"]
        if not isinstance(argv,list) or not argv or any(not isinstance(a,str) or not a or "\0" in a for a in argv): raise ValueError("Command must be an argv array")
        from .engine import _project_check
        if not _project_check(argv,root): raise ValueError("Only project verification commands are supported by API workers")
        if sys.platform!="darwin": raise ValueError("API command execution currently requires the macOS sandbox")
        from .providers import _capture
        import shutil
        executable=shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
        if not executable: raise ValueError("Verification executable is unavailable")
        executable=Path(executable)
        launch=executable.absolute() if (executable.parent.parent/"pyvenv.cfg").is_file() else executable.resolve()
        command=[str(launch),*argv[1:]]
        # A fresh command home stays outside the candidate and exposes no other
        # user's temporary files. Only this command's temporary directory is writable.
        with tempfile.TemporaryDirectory(prefix="parallax-api-command-") as temporary:
            rule,env=_command_scope(root,Path(temporary).resolve())
            async def command_event(event):
                if emit and event.get("type") in {"parallax.process_started","parallax.process_finished","parallax.process_termination_failed"}:
                    returned=emit(event)
                    if inspect.isawaitable(returned): await returned
            result=await _capture(["/usr/bin/sandbox-exec","-p",rule,*command],cwd=root,env=env,timeout=120,cancel_event=cancel_event,on_event=command_event,max_output=65536)
        if result.failure=="cancelled": raise asyncio.CancelledError
        return {"ok":result.exit_code==0 and not result.failure,"exit_code":result.exit_code,"output":result.stdout+result.stderr,"error":result.failure}

def _command_scope(root,temporary):
    root=root.resolve();temporary=temporary.resolve()
    writable=[str(root),str(temporary)]
    readable=[str(root),str(temporary),str(Path(sys.prefix).resolve()),str(Path(sys.base_prefix).resolve())]
    userdata=["/Users","/Volumes","/private/var/folders","/private/tmp","/tmp","/System/Volumes/Data/Users","/System/Volumes/Data/private/var/folders","/System/Volumes/Data/private/tmp"]
    rule="(version 1)(allow default)(deny network*)(deny file-write*)"
    rule+="(allow file-write* "+" ".join("(subpath "+json.dumps(p)+")" for p in writable)+' (literal "/dev/null"))'
    # Leave OS launch assessment and dyld caches readable. A global read deny
    # can strand unsigned user-installed runtimes during macOS native exec.
    protected_scope="(require-any "+" ".join("(subpath "+json.dumps(p)+")" for p in userdata)+")"
    permitted_scope="(require-any "+" ".join("(subpath "+json.dumps(p)+")" for p in readable)+")"
    rule+="(deny file-read-data (require-all "+protected_scope+" (require-not "+permitted_scope+")))"
    protected=sorted(BLOCKED-{"node_modules",".venv","__pycache__"})+[".parallax-owned"]
    for name in protected:
        rule+="(deny file-read* file-write* (subpath "+json.dumps(str(root/name))+"))"
    insensitive=lambda name:"".join("["+c.lower()+c.upper()+"]" if c.isascii() and c.isalpha() else re.escape(c) for c in name)
    names="|".join(insensitive(name) for name in protected)
    secret_pattern="^"+re.escape(str(root))+r"/([^/]+/)*("+insensitive(".env")+"[^/]*|"+names+")(/.*)?$"
    rule+="(deny file-read* file-write* (regex "+json.dumps(secret_pattern)+"))"
    env={"PATH":os.environ.get("PATH","/usr/bin:/bin"),"HOME":str(temporary),"TMPDIR":str(temporary),"CI":"true","PYTHONDONTWRITEBYTECODE":"1"}
    return rule,env

class ApiFailure(Exception):
    def __init__(self,code,message): super().__init__(message);self.code=code
