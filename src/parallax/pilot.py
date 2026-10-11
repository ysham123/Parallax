"""Measured pilot outcomes; no inferred costs or productivity claims."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from uuid import UUID
from . import authority
from .store import now

class BenchmarkInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    request_id: UUID
    workflow_id: UUID
    approach: Literal["parallax","single_agent"]
    duration_seconds: float = Field(ge=0,le=86400)
    interventions: int = Field(ge=0,le=10000)
    accepted: bool
    provider_cost_usd: float | None = Field(default=None,ge=0,le=10000)

class Pilot:
    def __init__(self, workflows):
        self.workflows=workflows; self.store=workflows.store
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS pilot_setup(workspace TEXT NOT NULL, actor TEXT NOT NULL, ready_at TEXT NOT NULL, PRIMARY KEY(workspace,actor));
                CREATE TABLE IF NOT EXISTS pilot_benchmarks(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, actor TEXT NOT NULL, body TEXT NOT NULL);''')

    def setup(self, project, assessment):
        if assessment["status"] != "ready": return
        scope=(authority.context() or {}).get("workspace", "local")
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO pilot_setup VALUES(?,?,?)",(scope,authority.actor(),now()))

    def report(self):
        rows=[]
        for brief in self.workflows.listing():
            value=self.workflows.get(brief["id"])
            run=self.store.get(value["run_id"]) if value.get("run_id") else None
            # Store.events is paginated for the activity API. Raw pilot counts
            # must include interventions after its first 250-event page.
            with self.store.connect() as db:
                interventions = db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind IN ('steering','steer','steer_requested','pause_requested','recovery_requested')", (run["run_id"],)).fetchone()[0] if run else 0
            approval_seconds=None
            if (value.get("decision") or {}).get("action") == "approve" and value.get("candidate"):
                approval_seconds=max(0,(datetime.fromisoformat(value["decision"]["at"])-datetime.fromisoformat(value["candidate"]["captured_at"])).total_seconds())
            usage=[]
            for report in (run or {}).get("usage",{}).get("reports",[]):
                usage.append({k:report[k] for k in ("provider","input_tokens","output_tokens","total_tokens","cost_usd") if k in report})
            rows.append({"workflow":value["id"],"status":value["status"],"requester":value.get("requester"),"revision":bool(value.get("revision")),
                "interventions":int(bool(value.get("revision")))+len(value.get("comments",[]))+interventions,
                "execution_seconds":(run or {}).get("artifacts",{}).get("runtime_seconds"),"approval_seconds":approval_seconds,
                "local_delivery":value.get("delivery",{}).get("local","legacy"),"publication":value.get("delivery",{}).get("github","pending"),
                "checks_passed":sum(c["ok"] for c in (run or {}).get("checks",[])),"checks_total":len((run or {}).get("checks",[])),
                "provider_usage":usage,"provider_cost_usd":None,"cost_status":"unknown"})
        scope=(authority.context() or {}).get("workspace", "local")
        import json
        with self.store.connect() as db:
            setup=[dict(r) for r in db.execute("SELECT actor,ready_at FROM pilot_setup WHERE workspace=?",(scope,))]
            benchmarks=[json.loads(r[0]) for r in db.execute("SELECT body FROM pilot_benchmarks WHERE workspace=?",(scope,))]
        ids={r["workflow"] for r in rows}
        return {"schema_version":"1.0","scope":"selected worker, latest 100 authorized workflows","setup":setup,"outcomes":rows,
            "benchmarks":[b for b in benchmarks if b["workflow_id"] in ids],"pricing":"manual agreement before enrollment","launch_status":"requires live acceptance"}

    def benchmark(self, request):
        import json
        value=self.workflows.get(str(request.workflow_id))
        self.workflows.check_workspace(value["spec"]["workspace"])
        body={**request.model_dump(mode="json"),"acceptance":value.get("original_goal",value["prompt"]),"required_checks":value["spec"]["checks"],"actor":authority.actor(),"at":now()}
        scope=(authority.context() or {}).get("workspace", "local")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT body FROM pilot_benchmarks WHERE id=?",(str(request.request_id),)).fetchone()
            if row:
                old=json.loads(row[0]); body['at']=old['at']
                if old != body: raise ValueError("Benchmark request ID was reused")
                return old
            db.execute("INSERT INTO pilot_benchmarks VALUES(?,?,?,?)",(str(request.request_id),scope,authority.actor(),json.dumps(body)))
        return body
