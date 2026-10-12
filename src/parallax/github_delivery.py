"""GitHub App delivery. Only managed trees and expected remote heads may publish."""
from __future__ import annotations
import base64
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID
from urllib.parse import urlencode
import httpx
import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

API = "https://api.github.com"
PERMISSIONS = {"contents":"write","pull_requests":"write","checks":"read","statuses":"read","actions":"read"}

class RepositoryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    installation: int = Field(gt=0)
    repository: int = Field(gt=0)
    worker: str = Field(pattern=r"^[a-f0-9-]{36}$")
    project: str = Field(min_length=1,max_length=4096)
    base: str = Field(default="main",pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_./-]{0,200}$")

class PublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding: str = Field(pattern=r"^[a-f0-9-]{36}$")
    workflow: str = Field(pattern=r"^[a-f0-9-]{36}$")
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(default="",max_length=20000)

class GitHubDelivery:
    def __init__(self, store, *, transport=None, config=None):
        self.store, self.transport = store, transport
        self.config = config if config is not None else {key:os.environ.pop("PARALLAX_GITHUB_APP_"+key.upper(),"") for key in ("id","private_key_path","client_id","client_secret","webhook_secret","slug")}
        from .isolation import register_private_paths
        register_private_paths(store,state=[store.home],files=[self.config.get("private_key_path")])
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS github_flows(state TEXT PRIMARY KEY, binding TEXT NOT NULL, workspace TEXT NOT NULL, actor TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS github_installations(workspace TEXT NOT NULL, installation INTEGER NOT NULL, actor TEXT NOT NULL, PRIMARY KEY(workspace,installation));
                CREATE TABLE IF NOT EXISTS github_bindings(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS github_binding_operations(id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                    actor TEXT NOT NULL, signature TEXT NOT NULL, binding TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS github_publications(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, workflow TEXT NOT NULL, actor TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS github_deliveries(id TEXT PRIMARY KEY, hash TEXT NOT NULL, received REAL NOT NULL);
            ''')

    def configured(self):
        return all(self.config.get(key) for key in ("id","private_key_path","client_id","client_secret","webhook_secret","slug"))

    def app_jwt(self):
        if not self.configured(): raise HTTPException(503,"Configure the GitHub App on staging before GitHub delivery")
        stamp = int(time.time())
        return jwt.encode({"iat":stamp-60,"exp":stamp+540,"iss":self.config["id"]},Path(self.config["private_key_path"]).read_bytes(),algorithm="RS256")

    async def request(self, method, path, token, body=None):
        async with httpx.AsyncClient(transport=self.transport,timeout=30,trust_env=False,follow_redirects=False) as client:
            response = await client.request(method,API+path,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2026-03-10","User-Agent":"Parallax"},json=body)
        if response.status_code >= 400:
            raise HTTPException(409 if response.status_code in (404,409,422) else 502,"GitHub refused the operation. Refresh installation, repository and remote state before retrying.")
        return response.json() if response.content else {}

    async def token(self, installation, repository=None):
        body = {"permissions":PERMISSIONS if repository else {"metadata":"read"}, **({"repository_ids":[repository]} if repository else {})}
        result = await self.request("POST",f"/app/installations/{installation}/access_tokens",self.app_jwt(),body)
        return result["token"]  # Never stored in SQLite or sent to a browser/worker.

    def begin(self, principal, origin):
        if not self.configured(): raise HTTPException(503,"GitHub App setup is required")
        if not principal.account: raise HTTPException(403,"Connect GitHub with an individual owner account")
        state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = hashlib.sha256(binding.encode()).hexdigest()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with self.store.connect() as db:
            db.execute("DELETE FROM github_flows WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO github_flows VALUES(?,?,?,?,?)", (hashlib.sha256(state.encode()).hexdigest(),hashlib.sha256(binding.encode()).hexdigest(),principal.workspace,principal.account["id"],time.time()+600))
        return "https://github.com/login/oauth/authorize?"+urlencode({"client_id":self.config["client_id"],"redirect_uri":origin+"/api/github/connect/callback","state":state,"code_challenge":challenge,"code_challenge_method":"S256"}), binding

    async def finish(self, code, state, binding, origin, owner_check):
        with self.store.connect() as db:
            row = db.execute("DELETE FROM github_flows WHERE state=? AND binding=? AND expires>=? RETURNING workspace,actor",(hashlib.sha256(state.encode()).hexdigest(),hashlib.sha256(binding.encode()).hexdigest(),time.time())).fetchone()
        if not row: raise HTTPException(403,"GitHub authorization expired or belongs to another browser")
        owner_check(row["workspace"],row["actor"])
        async with httpx.AsyncClient(transport=self.transport,timeout=20,trust_env=False,follow_redirects=False) as client:
            response=await client.post("https://github.com/login/oauth/access_token",headers={"Accept":"application/json"},data={"client_id":self.config["client_id"],"client_secret":self.config["client_secret"],"code":code,"redirect_uri":origin+"/api/github/connect/callback","code_verifier":hashlib.sha256(binding.encode()).hexdigest()})
        token = response.json().get("access_token") if response.status_code==200 else None
        if not token: raise HTTPException(403,"GitHub App authorization was declined")
        installations = await self.request("GET","/user/installations?per_page=100",token)
        app_id = int(self.config["id"])
        accepted = [i for i in installations.get("installations",[]) if i.get("app_id")==app_id and not i.get("suspended_at")]
        owner_check(row["workspace"],row["actor"])
        with self.store.connect() as db:
            for installation in accepted:
                db.execute("INSERT OR REPLACE INTO github_installations VALUES(?,?,?)",(row["workspace"],installation["id"],row["actor"]))
        return row["workspace"]

    def installations(self, workspace):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT installation FROM github_installations WHERE workspace=?",(workspace,))]

    async def repositories(self, workspace, installation):
        if installation not in self.installations(workspace): raise HTTPException(404,"Installation not connected to this workspace")
        token = await self.token(installation)
        result = []; page=1
        while True:
            data = await self.request("GET",f"/installation/repositories?per_page=100&page={page}",token)
            rows=data.get("repositories",[]); result.extend(rows)
            if len(rows)<100: break
            page+=1
        return [{k:r[k] for k in ("id","full_name","default_branch")} for r in result]

    async def bind(self, workspace, body, *, actor=None, authorize=lambda: None):
        """Record delivery configuration atomically; every replay rechecks access."""
        authorize()
        if '..' in body.base or body.base.endswith('/') or '@{' in body.base: raise ValueError("Choose a valid remote base branch")
        payload=body.model_dump(exclude={"request_id"})
        operation=str(body.request_id) if body.request_id else None
        if operation and not actor:
            raise ValueError("An authenticated actor is required for binding request identity")
        signature=hashlib.sha256(json.dumps({"scheme":"repository-binding-request-v1","workspace":workspace,
            "actor":actor,"binding":payload},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        def recorded(db):
            if not operation: return None
            row=db.execute("SELECT * FROM github_binding_operations WHERE id=?",(operation,)).fetchone()
            if not row: return None
            if row["workspace"]!=workspace or row["actor"]!=actor or row["signature"]!=signature:
                raise HTTPException(409,"Repository binding request identity was reused with different content")
            binding=db.execute("SELECT body FROM github_bindings WHERE id=? AND workspace=?",(row["binding"],workspace)).fetchone()
            if not binding:
                raise HTTPException(409,"Saved repository binding is unavailable. Inspect current bindings before starting a new request")
            return {"id":row["binding"],**json.loads(binding["body"])}
        # Reject conflicting IDs before issuing external reads, but never let a
        # saved operation substitute for current repository or owner access.
        with self.store.connect() as db:
            recorded(db)
        repositories=await self.repositories(workspace,body.installation)
        authorize()
        repo=next((r for r in repositories if r["id"]==body.repository),None)
        if not repo: raise HTTPException(403,"Repository not selected for this installation")
        value = {**payload,"full_name":repo["full_name"]}
        identifier=secrets.token_hex(16)
        from uuid import UUID
        identifier=str(UUID(identifier))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            authorize()
            if not db.execute("SELECT 1 FROM github_installations WHERE workspace=? AND installation=?",(workspace,body.installation)).fetchone():
                raise HTTPException(404,"Installation not connected to this workspace")
            previous=recorded(db)
            if previous: return previous
            db.execute("INSERT INTO github_bindings VALUES(?,?,?)",(identifier,workspace,json.dumps(value)))
            if operation:
                db.execute("INSERT INTO github_binding_operations VALUES(?,?,?,?,?,?)",(operation,workspace,actor,signature,identifier,time.time()))
        return {"id":identifier,**value}

    def bindings(self, workspace):
        with self.store.connect() as db:
            return [{"id":r[0],**json.loads(r[1])} for r in db.execute("SELECT id,body FROM github_bindings WHERE workspace=?",(workspace,))]

    def binding(self, workspace, identifier):
        value=next((b for b in self.bindings(workspace) if b["id"]==identifier),None)
        if not value: raise HTTPException(404,"GitHub repository binding not found")
        return value

    async def baseline(self, workspace, identifier):
        binding=self.binding(workspace,identifier)
        token=await self.token(binding["installation"],binding["repository"])
        from urllib.parse import quote
        commit=await self.request("GET",f'/repos/{binding["full_name"]}/commits/{quote(binding["base"],safe="")}',token)
        return {**binding,"base_commit":commit["sha"],"base_tree":commit["commit"]["tree"]["sha"]}

    async def remote(self, binding, token, path):
        return await self.request("GET",f'/repos/{binding["full_name"]}'+path,token)

    async def publish(self, workspace, actor, request, package, *, authorize=lambda: None):
        """Reconcile a durable operation before any remote mutation; GraphQL uses expectedHeadOid."""
        binding=self.binding(workspace,request.binding)
        if package["digest"] != request.candidate_digest or package["workflow"] != request.workflow:
            raise ValueError("Publication must use the approved saved candidate")
        if package.get("binding") != request.binding: raise ValueError("Task was not captured for this remote repository")
        payload={"actor":actor,"request":request.model_dump(mode="json"),"tree":package["tree"],"baseline":package["baseline"]}
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        identifier=str(request.request_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM github_publications WHERE id=?",(identifier,)).fetchone()
            if row and (row["workspace"]!=workspace or row["fingerprint"]!=fingerprint): raise ValueError("Publication request ID was reused")
            value=json.loads(row["body"]) if row else {"state":"pending","request":request.model_dump(mode="json"),"tree":package["tree"],"base_commit":package["baseline"],"branch":package.get("branch") or 'parallax/'+request.workflow,"parent_head":package.get("parent_head"),"actor":actor}
            if not row: db.execute("INSERT INTO github_publications VALUES(?,?,?,?,?,?)",(identifier,workspace,request.workflow,actor,fingerprint,json.dumps(value)))
        if value["state"]=="published": return value
        token=await self.token(binding["installation"],binding["repository"])
        baseline=await self.baseline(workspace,request.binding)
        if baseline["base_commit"]!=value["base_commit"] or baseline["base_tree"]!=package["baseline_tree"]:
            raise ValueError("Remote base drifted. Start a fresh task; automatic rebasing is disabled")
        branch=value["branch"]
        pull_path="/pulls?state=all&head="+binding["full_name"].split('/')[0]+":"+branch+"&base="+binding["base"]
        pulls=await self.remote(binding,token,pull_path)
        existing_pr=next((p for p in pulls if p["head"]["ref"]==branch),None)
        if existing_pr and (existing_pr["state"]!='open' or not existing_pr["draft"]):
            raise ValueError("The existing PR must remain an open draft")
        refs=await self.remote(binding,token,"/git/matching-refs/heads/"+branch)
        ref=next((r for r in refs if r["ref"]=='refs/heads/'+branch),None)
        expected=value.get("parent_head") or value["base_commit"]
        marker='Parallax operation '+identifier+' candidate '+request.candidate_digest
        if ref:
            head=ref["object"]["sha"]
            if value.get("commit") and head != value["commit"]:
                raise ValueError("Draft PR head changed outside Parallax. Refresh and inspect it before retrying")
            commit=await self.remote(binding,token,"/git/commits/"+head)
            if commit["tree"]["sha"]==package["tree"] and marker in commit["message"]:
                value["commit"]=head  # Crash after commit creation: recognize exact operation and exact tree.
            elif head!=expected: raise ValueError("Draft PR head changed outside Parallax. Refresh and inspect it before revising")
        else:
            if value.get("parent_head") or value.get("commit"): raise ValueError("Published branch was removed")
            authorize()
            await self.request("POST",f'/repos/{binding["full_name"]}/git/refs',token,{"ref":"refs/heads/"+branch,"sha":expected})
        if not value.get("commit"):
            mutation='mutation($input:CreateCommitOnBranchInput!){createCommitOnBranch(input:$input){commit{oid}}}'
            authorize()
            result=await self.request("POST","/graphql",token,{"query":mutation,"variables":{"input":{"branch":{"repositoryNameWithOwner":binding["full_name"],"branchName":branch},"expectedHeadOid":expected,"message":{"headline":request.title,"body":marker},"fileChanges":{"additions":package["additions"],"deletions":package["deletions"]}}}})
            if result.get("errors"): raise ValueError("GitHub rejected the expected PR head. Refresh before retrying")
            value["commit"]=result["data"]["createCommitOnBranch"]["commit"]["oid"]
            commit=await self.remote(binding,token,"/git/commits/"+value["commit"])
            if commit["tree"]["sha"]!=package["tree"]: raise ValueError("Published commit tree did not match the approved candidate")
            self.save_publication(identifier,value)
        pulls=await self.remote(binding,token,pull_path)
        pr=next((p for p in pulls if p["head"]["ref"]==branch),None)
        if pr and (pr["state"]!='open' or not pr["draft"]): raise ValueError("The existing PR must remain an open draft")
        if not pr:
            authorize()
            pr=await self.request("POST",f'/repos/{binding["full_name"]}/pulls',token,{"head":branch,"base":binding["base"],"title":request.title,"body":request.description,"draft":True})
        if pr["head"]["sha"]!=value["commit"]: raise ValueError("PR head changed during publication")
        value.update(state="published",pr=pr["number"],url=pr["html_url"],repository=binding["full_name"],binding=request.binding,published_at=time.time())
        self.save_publication(identifier,value)
        return value

    def save_publication(self, identifier, value):
        with self.store.connect() as db: db.execute("UPDATE github_publications SET body=? WHERE id=?",(json.dumps(value),identifier))

    def publication(self, workspace, workflow):
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM github_publications WHERE workspace=? AND workflow=? ORDER BY rowid DESC LIMIT 1", (workspace,workflow)).fetchone()
        return json.loads(row[0]) if row else None

    def completed_publication(self, workspace, actor, request):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM github_publications WHERE id=?", (str(request.request_id),)).fetchone()
        if not row: return None
        value = json.loads(row["body"])
        if row["workspace"] != workspace or row["actor"] != actor or value["request"] != request.model_dump(mode="json"):
            raise ValueError("Publication request ID was reused")
        return value if value["state"] == "published" else None

    async def feedback(self, workspace, workflow):
        with self.store.connect() as db:
            row=db.execute("SELECT body FROM github_publications WHERE workspace=? AND workflow=? ORDER BY rowid DESC LIMIT 1",(workspace,workflow)).fetchone()
        if not row: raise HTTPException(404,"No published draft PR")
        value=json.loads(row[0]); binding=self.binding(workspace,value["binding"])
        token=await self.token(binding["installation"],binding["repository"])
        pr=await self.remote(binding,token,f'/pulls/{value["pr"]}')
        head=pr["head"]["sha"]
        specifications={
            "checks":(f'/commits/{head}/check-runs',"check_runs",("id","name","status","conclusion","html_url")),
            "statuses":(f'/commits/{head}/status',"statuses",("id","context","state","target_url")),
            "comments":(f'/pulls/{value["pr"]}/comments',None,("id","path","line","body","html_url")),
            "reviews":(f'/pulls/{value["pr"]}/reviews',None,("id","state","body","html_url")),
        }
        # Bound output and requests without silently representing a partial page
        # as all feedback. Do not retain provider tokens or arbitrary API fields.
        async def collect(path,key,fields):
            rows=[]; seen=set(); size=0; pages=0
            for page in range(1,11):
                try:
                    data=await self.remote(binding,token,path+f'?per_page=100&page={page}')
                    entries=data.get(key) if key else data
                    total=data.get("total_count") if key else None
                    if not isinstance(entries,list) or (total is not None and not isinstance(total,int)):
                        raise ValueError("Invalid feedback response")
                    pages=page
                    for entry in entries:
                        if not isinstance(entry,dict): raise ValueError("Invalid feedback entry")
                        item={field:entry[field] for field in fields if field in entry}
                        identifier=item.get("id")
                        if identifier in seen: return rows,pages,"Feedback changed during pagination; refresh again."
                        seen.add(identifier)
                        size+=len(json.dumps(item,ensure_ascii=False).encode("utf-8"))
                        if size>1024*1024: return rows,pages,"Feedback exceeds the display limit; inspect the full PR on GitHub."
                        rows.append(item)
                    if len(entries)<100:
                        if total is not None and len(rows)!=total:
                            return rows,pages,"Feedback count changed during pagination; refresh again."
                        return rows,pages,None
                    if total is not None and len(rows)==total: return rows,pages,None
                except (HTTPException,httpx.HTTPError,ValueError,TypeError):
                    return rows,pages,"Feedback could not be fully refreshed. Check GitHub access and retry."
            return rows,pages,"Feedback exceeds 1,000 entries; inspect the full PR on GitHub."
        results=await asyncio.gather(*(collect(*spec) for spec in specifications.values()))
        errors={name:result[2] for name,result in zip(specifications,results) if result[2]}
        try:
            latest=await self.remote(binding,token,f'/pulls/{value["pr"]}')
            if latest["head"]["sha"]!=head:
                errors["head"]="PR head changed during refresh; refresh again before using this feedback."
        except (HTTPException,httpx.HTTPError,KeyError,TypeError):
            errors["head"]="PR head could not be rechecked; refresh again."
        return {"pr":value["pr"],"url":value["url"],"head":head,"external_change":head!=value["commit"],
                **{name:result[0] for name,result in zip(specifications,results)},
                "refreshed_at":time.time(),"incomplete":bool(errors),"feedback_errors":errors,
                "page_counts":{name:result[1] for name,result in zip(specifications,results)}}

    def webhook(self, identifier, signature, body):
        secret=self.config.get("webhook_secret")
        if not secret: raise HTTPException(503,"GitHub webhook secret is not configured")
        expected='sha256='+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature or ''): raise HTTPException(403,"Invalid GitHub webhook signature")
        if not identifier or len(identifier)>128: raise ValueError("Missing delivery ID")
        hashed=hashlib.sha256(body).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing=db.execute("SELECT hash FROM github_deliveries WHERE id=?",(identifier,)).fetchone()
            if existing and existing[0]!=hashed: raise HTTPException(409,"Delivery ID was reused")
            db.execute("INSERT OR IGNORE INTO github_deliveries VALUES(?,?,?)",(identifier,hashed,time.time()))
            db.execute("DELETE FROM github_deliveries WHERE received<?",(time.time()-30*86400,))
        # Events are hints. Studio refresh reads authoritative current state; ordering cannot regress saved state.
        return {"ok":True,"duplicate":bool(existing),"refresh_required":True}
