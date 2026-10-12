"""Workspace membership and project policy. Client roles are never authority."""
from __future__ import annotations
import hashlib
import json
import secrets
import time
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

class TeamInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)

class InvitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["developer", "reviewer"] = "developer"

class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)

class ProjectBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker: str = Field(pattern=r"^[a-f0-9-]{36}$")
    path: str = Field(min_length=1, max_length=4096)
    members: list[str] = Field(default_factory=list, max_length=100)

class ProjectMembersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    members: list[str] = Field(default_factory=list, max_length=100)

class Teams:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS memberships(workspace TEXT NOT NULL, account TEXT NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY(workspace,account));
                CREATE TABLE IF NOT EXISTS invitations(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL, role TEXT NOT NULL,
                    actor TEXT NOT NULL, expires REAL NOT NULL, accepted_by TEXT);
                CREATE TABLE IF NOT EXISTS project_bindings(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, worker TEXT NOT NULL,
                    path TEXT NOT NULL, members TEXT NOT NULL, UNIQUE(workspace,worker,path));
                CREATE TABLE IF NOT EXISTS team_recipes(workspace TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    body TEXT NOT NULL, actor TEXT NOT NULL, PRIMARY KEY(workspace,id,version));
                CREATE TABLE IF NOT EXISTS project_policy_operations(id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                    binding TEXT NOT NULL, actor TEXT NOT NULL, before_members TEXT NOT NULL,
                    after_members TEXT NOT NULL, created REAL NOT NULL);
            ''')

    def account(self, principal):
        if not principal.account:
            raise HTTPException(403, "Sign in with an individual account for team actions")
        return principal.account["id"]

    def role(self, workspace, actor):
        with self.store.connect() as db:
            row = db.execute("SELECT m.role FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND a.disabled=0", (workspace,actor)).fetchone()
        if not row: raise HTTPException(403, "Workspace membership was removed")
        return row[0]

    def is_team(self, workspace):
        with self.store.connect() as db:
            return bool(db.execute("SELECT 1 FROM workspaces WHERE id=? AND kind='team'", (workspace,)).fetchone())

    def require(self, principal, roles=("owner", "developer", "reviewer")):
        actor = self.account(principal)
        role = self.role(principal.workspace, actor)
        if role not in roles: raise HTTPException(403, "This workspace role cannot perform that action")
        return actor, role

    def list(self, principal):
        actor = self.account(principal)
        with self.store.connect() as db:
            rows = db.execute("SELECT w.id,w.kind,w.name,m.role FROM workspaces w JOIN memberships m ON m.workspace=w.id WHERE m.account=?", (actor,)).fetchall()
            personal = db.execute("SELECT w.id,w.kind,w.name FROM workspaces w JOIN accounts a ON a.workspace=w.id WHERE a.id=?", (actor,)).fetchone()
        result = [dict(row) for row in rows]
        if personal and personal["id"] not in {r["id"] for r in result}: result.insert(0, {**dict(personal), "role":"owner"})
        return result

    def create(self, principal, name):
        actor = self.account(principal)
        if not name.strip(): raise ValueError("Name the team workspace")
        identifier = str(uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM memberships WHERE account=? AND role='owner'", (actor,)).fetchone()[0] >= 10:
                raise HTTPException(409, "Team workspace limit reached")
            db.execute("INSERT INTO workspaces VALUES(?, 'team', ?, 0, ?)", (identifier, name.strip(), time.time()))
            db.execute("INSERT INTO memberships VALUES(?,?,'owner')", (identifier,actor))
        return {"id":identifier,"name":name.strip(),"kind":"team","role":"owner"}

    def invite(self, principal, role):
        actor, _ = self.require(principal, ("owner",))
        token = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute("DELETE FROM invitations WHERE expires<?", (time.time(),))
            if db.execute("SELECT COUNT(*) FROM invitations WHERE workspace=? AND accepted_by IS NULL", (principal.workspace,)).fetchone()[0] >= 100:
                raise HTTPException(409, "Invitation limit reached")
            db.execute("INSERT INTO invitations VALUES(?,?,?,?,?,NULL)", (hashlib.sha256(token.encode()).hexdigest(),principal.workspace,role,actor,time.time()+7*86400))
        return {"token":token,"expires_in":7*86400}

    def accept(self, principal, token):
        actor = self.account(principal)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM invitations WHERE hash=? AND expires>=?", (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row or (row["accepted_by"] and row["accepted_by"] != actor): raise HTTPException(410,"Invitation expired or already used")
            if row["accepted_by"] and not db.execute("SELECT 1 FROM memberships WHERE workspace=? AND account=?", (row["workspace"],actor)).fetchone():
                raise HTTPException(410,"Invitation was already used. Ask an owner for a new invitation")
            if not db.execute("SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND m.role='owner' AND a.disabled=0", (row["workspace"],row["actor"])).fetchone():
                raise HTTPException(410,"Invitation issuer is no longer an owner")
            db.execute("INSERT OR IGNORE INTO memberships VALUES(?,?,?)", (row["workspace"],actor,row["role"]))
            db.execute("UPDATE invitations SET accepted_by=? WHERE hash=?", (actor,row["hash"]))
        return {"workspace":row["workspace"]}

    def members(self, principal):
        self.require(principal)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("SELECT m.account,m.role,a.login,a.name FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=?", (principal.workspace,))]

    def remove(self, principal, account):
        self.require(principal, ("owner",))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT role FROM memberships WHERE workspace=? AND account=?", (principal.workspace,account)).fetchone()
            if row and row[0] == "owner": raise HTTPException(409,"Transfer ownership before removing an owner")
            db.execute("DELETE FROM memberships WHERE workspace=? AND account=?", (principal.workspace,account))
            db.execute("DELETE FROM sessions WHERE account=? AND workspace=? AND kind='team'", (account,principal.workspace))
        return {"ok":True}

    def change_role(self, principal, account, role):
        self.require(principal,("owner",))
        if role not in {"owner","developer","reviewer"}: raise ValueError("Choose a workspace role")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            member=db.execute("SELECT role FROM memberships WHERE workspace=? AND account=?",(principal.workspace,account)).fetchone()
            if not member: raise HTTPException(404,"Member not found")
            if member[0]=='owner' and role!='owner' and db.execute("SELECT COUNT(*) FROM memberships WHERE workspace=? AND role='owner'",(principal.workspace,)).fetchone()[0]<=1:
                raise HTTPException(409,"Promote another owner before changing the last owner's role")
            db.execute("UPDATE memberships SET role=? WHERE workspace=? AND account=?",(role,principal.workspace,account))
        return {"ok":True}

    def projects(self, principal):
        actor, role = self.require(principal)
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM project_bindings WHERE workspace=?", (principal.workspace,))]
        return [r for r in rows if role == "owner" or not json.loads(r["members"]) or actor in json.loads(r["members"])]

    def bind(self, principal, body, hub):
        self.require(principal, ("owner",))
        worker = hub.worker(body.worker, principal.workspace)
        if body.path not in worker["workspaces"]: raise HTTPException(403,"The worker has not approved this exact project path")
        for member in body.members: self.role(principal.workspace, member)
        with self.store.connect() as db:
            db.execute("INSERT INTO project_bindings VALUES(?,?,?,?,?) ON CONFLICT(workspace,worker,path) DO UPDATE SET members=excluded.members",
                (str(uuid4()),principal.workspace,body.worker,body.path,json.dumps(body.members)))
        return self.projects(principal)

    def update_project_members(self, principal, identifier, body):
        """Change an existing grant, including archived projects, without pairing a machine.

        Resolve the owner and session after taking the writer lock so a queued
        policy change cannot outlive membership or session revocation.
        """
        actor = self.account(principal)
        members = sorted(set(body.members))
        encoded = json.dumps(members)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND m.role='owner' AND a.disabled=0",
                               (principal.workspace, actor)).fetchone()
            session = db.execute("SELECT 1 FROM sessions WHERE hash=? AND account=? AND workspace=? AND expires>=?",
                                 (principal.session, actor, principal.workspace, time.time())).fetchone()
            if not owner or not session:
                raise HTTPException(403, "Current workspace owner authorization is required")
            project = db.execute("SELECT * FROM project_bindings WHERE id=? AND workspace=?", (identifier, principal.workspace)).fetchone()
            if not project:
                raise HTTPException(404, "Project binding not found")
            for member in members:
                if not db.execute("SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND a.disabled=0",
                                  (principal.workspace, member)).fetchone():
                    raise HTTPException(403, "Project grants require current workspace members")
            previous = db.execute("SELECT workspace,binding,actor,after_members FROM project_policy_operations WHERE id=?", (body.request_id,)).fetchone()
            if previous:
                if tuple(previous) != (principal.workspace, identifier, actor, encoded):
                    raise HTTPException(409, "Request identity was reused with different content")
                return {"ok": True, "operation_id": body.request_id}
            db.execute("UPDATE project_bindings SET members=? WHERE id=? AND workspace=?", (encoded, identifier, principal.workspace))
            db.execute("INSERT INTO project_policy_operations VALUES(?,?,?,?,?,?,?)",
                       (body.request_id, principal.workspace, identifier, actor, project["members"], encoded, time.time()))
        return {"ok": True, "operation_id": body.request_id}

    def context(self, principal, worker):
        actor, role = self.require(principal)
        projects = [p["path"] for p in self.projects(principal) if p["worker"]==worker]
        return {"version":"2.0", "workspace":principal.workspace,"actor":actor,"role":role,"team":True,"session":principal.session,"reviewers":[m["account"] for m in self.members(principal)],
                "reviewers_by_project":{path:actors for path,actors in self.reviewers_by_project(principal.workspace, worker).items() if path in projects},
                "recipes":self.recipe_versions(principal.workspace),"projects":projects}

    def review_target(self, principal, hub, workspace, worker, workflow):
        """Read-only preview of a review link from managed records.

        Membership and project grants are resolved for the target workspace, not
        the session's current one. Nothing is queued, sent to a machine or
        switched. Every refusal looks the same so a link reveals nothing.
        """
        unavailable = HTTPException(404, "Review link is unavailable")
        try:
            from uuid import UUID
            workspace, worker, workflow = (str(UUID(value)) for value in (workspace, worker, workflow))
        except (ValueError, AttributeError, TypeError):
            raise unavailable
        if not principal.account:
            raise unavailable
        actor = principal.account["id"]
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE hash=? AND account=? AND expires>=?",
                              (principal.session, actor, time.time())).fetchone():
                raise unavailable
            space = db.execute("SELECT id,kind,name FROM workspaces WHERE id=?", (workspace,)).fetchone()
            if not space:
                raise unavailable
            if space["kind"] == "team":
                row = db.execute("SELECT m.role FROM memberships m JOIN accounts a ON a.id=m.account "
                                 "WHERE m.workspace=? AND m.account=? AND a.disabled=0", (workspace, actor)).fetchone()
                role = row[0] if row else None
            else:
                owned = db.execute("SELECT 1 FROM accounts WHERE id=? AND workspace=? AND disabled=0", (actor, workspace)).fetchone()
                role = "owner" if owned else None
            if role is None:
                raise unavailable
            bindings = db.execute("SELECT path,members FROM project_bindings WHERE workspace=? AND worker=?",
                                  (workspace, worker)).fetchall() if space["kind"] == "team" else []
        try:
            machine = hub.worker(worker, workspace)
        except HTTPException:
            raise unavailable
        team = space["kind"] == "team"
        if team and "workflow-v2" not in machine.get("features", []):
            raise unavailable
        record = None
        cached = hub.cached(worker, "/api/workflows/" + workflow)
        if cached and cached.get("status") == 200 and isinstance(cached.get("body"), dict):
            record = cached["body"]
        else:
            listed = hub.cached(worker, "/api/workflows")
            rows = listed.get("body") if listed and listed.get("status") == 200 else None
            if isinstance(rows, list):
                record = next((row for row in rows if isinstance(row, dict) and row.get("id") == workflow), None)
        if not record or record.get("id") != workflow:
            raise unavailable
        project = record.get("workspace")
        if not isinstance(project, str) or project not in machine.get("workspaces", []):
            raise unavailable
        if team:
            permitted = [path for path, members in bindings
                         if role == "owner" or not json.loads(members) or actor in json.loads(members)]
            if project not in permitted:
                raise unavailable
        title = record.get("title")
        status = record.get("status")
        return {
            "schema_version": "1.0",
            "capability": "review-target-v1",
            "actor": actor,
            "workspace": {"id": space["id"], "name": space["name"], "kind": space["kind"], "role": role},
            "worker": {"id": machine["id"], "name": machine["name"], "online": bool(machine.get("online"))},
            "workflow": {"id": workflow, "title": title if isinstance(title, str) else None,
                         "status": status if isinstance(status, str) else None},
            "source": "managed_cache",
        }

    def reviewers_by_project(self, workspace, worker):
        with self.store.connect() as db:
            projects = db.execute("SELECT path,members FROM project_bindings WHERE workspace=? AND worker=?", (workspace,worker)).fetchall()
            members = db.execute("SELECT m.account,m.role FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND a.disabled=0", (workspace,)).fetchall()
        return {project["path"]:[member["account"] for member in members if member["role"] == "owner" or not json.loads(project["members"]) or member["account"] in json.loads(project["members"])] for project in projects}

    def recipes(self, principal):
        self.require(principal)
        return self.recipe_versions(principal.workspace, latest=True)

    def recipe_versions(self, workspace, latest=False):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,version,body FROM team_recipes WHERE workspace=?" + (" AND version=(SELECT MAX(t.version) FROM team_recipes t WHERE t.workspace=team_recipes.workspace AND t.id=team_recipes.id)" if latest else ""), (workspace,)).fetchall()
        return [{"id":r[0],"version":r[1],**json.loads(r[2])} for r in rows]

    def save_recipe(self, principal, body, identifier=None):
        actor,_ = self.require(principal,("owner","developer"))
        updating = identifier is not None
        identifier=identifier or str(uuid4())
        from uuid import UUID
        UUID(identifier)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if updating and not db.execute("SELECT 1 FROM team_recipes WHERE workspace=? AND id=?", (principal.workspace,identifier)).fetchone():
                raise KeyError(identifier)
            if db.execute("SELECT COUNT(*) FROM team_recipes WHERE workspace=?",(principal.workspace,)).fetchone()[0]>=1000:
                raise HTTPException(409,"Shared recipe version limit reached")
            version=db.execute("SELECT COALESCE(MAX(version),0)+1 FROM team_recipes WHERE workspace=? AND id=?",(principal.workspace,identifier)).fetchone()[0]
            db.execute("INSERT INTO team_recipes VALUES(?,?,?,?,?)",(principal.workspace,identifier,version,json.dumps(body.model_dump()),actor))
        return {"id":identifier,"version":version,**body.model_dump()}

    def reauthorize(self, context, worker, method, path):
        role = self.role(context["workspace"], context["actor"])
        with self.store.connect() as db:
            if context.get("session") and not db.execute("SELECT 1 FROM sessions WHERE hash=? AND account=? AND workspace=? AND expires>=?", (context["session"],context["actor"],context["workspace"],time.time())).fetchone():
                raise HTTPException(403,"Session ended before queued dispatch")
            rows = db.execute("SELECT path,members FROM project_bindings WHERE workspace=? AND worker=?", (context["workspace"],worker)).fetchall()
        projects = [r[0] for r in rows if role == "owner" or not json.loads(r[1]) or context["actor"] in json.loads(r[1])]
        if not projects: raise HTTPException(403,"No approved project binding is available to this member")
        if method == "GET" and not (path in {"/api/context","/api/deployment","/api/providers","/api/connections","/api/workflows","/api/runs","/api/workflow-templates","/api/pilot/report"} or path.startswith(("/api/models/","/api/workflows/","/api/runs/"))):
            raise HTTPException(403,"This machine-level data is not shared with the team")
        if method != "GET":
            if path.endswith('/decision') or path.endswith('/approve') or path.endswith('/comment') or path == '/api/pilot/observations':
                pass
            elif role == "reviewer": raise HTTPException(403,"Reviewers may inspect, comment and approve")
            if not (path.startswith('/api/workflows') or path == '/api/project/assess' or path.startswith('/api/workflow-templates') or path.endswith('/steer') or path in {'/api/pilot/benchmark','/api/pilot/observations'}):
                raise HTTPException(403,"Team work must use approved workflow operations")
        with self.store.connect() as db:
            reviewers = [r[0] for r in db.execute("SELECT account FROM memberships WHERE workspace=?", (context["workspace"],))]
        return {**context,"role":role,"projects":projects,"reviewers":reviewers,
                "reviewers_by_project":{path:actors for path,actors in self.reviewers_by_project(context["workspace"],worker).items() if path in projects},
                "recipes":self.recipe_versions(context["workspace"])}
