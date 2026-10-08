"""Runtime-owned scheduling and verification. Agents propose; the engine enforces."""
from __future__ import annotations
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path
from .models import CheckEvidence, CoordinatorAction, Participant, RunResult, RunSpec, TaskSpec, CheckSpec
from .store import Store
from .assessment import assess_project, execution_capability, package_directory
from .recovery import classify, recovery_options
from .context import (PROMPT_LIMIT, REQUEST_LIMIT, Packet, consultant_packet, coordinator_packet, distiller_packet,
                      filter_patch, memory_scrubber, review_packet, synthesis_packet, worker_packet)

TERMINAL = {"completed", "failed", "cancelled", "needs_attention"}
TASK_DONE = {"completed", "resolved"}
INTEGRABLE = {"completed", "resolved", "discarded"}
VARIANT_LIVE = {"pending", "running", "interrupted"}
RESERVED_IDS = {"coordinator", "baseline", "integration", "distill", "synthesis"}
MAX_TASKS = 40

class RunProblem(Exception):
    pass

class Engine:
    def __init__(self, store: Store, registry=None, *, memory: bool | None = None):
        from .connections import ConnectionRegistry
        self.store = store
        # Project memory is on for real providers unless PARALLAX_MEMORY=off; injected registries opt in explicitly.
        self.memory = (registry is None and os.environ.get("PARALLAX_MEMORY", "on").lower() != "off") if memory is None else memory
        self._memory_failed: set[str] = set()
        self.registry = registry or ConnectionRegistry(store)
        self.jobs: dict[str, asyncio.Task] = {}
        self.cancel_flags: dict[str, asyncio.Event] = {}
        self.pause_flags: set[str] = set()
        self.wakeup: dict[str, asyncio.Event] = {}
        self.shutting_down = False
        self._clocks: dict[str, tuple[float, float]] = {}

    async def shutdown(self):
        """Stop children while preserving resumable state for a server restart."""
        self.shutting_down = True
        jobs = list(self.jobs.items())
        for run_id, job in jobs:
            self.cancel_flags[run_id].set()
            self.wakeup.setdefault(run_id, asyncio.Event()).set()
            job.cancel()
        if jobs:
            await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        self.store.close()

    def _interrupt_tasks(self, result: dict):
        for task in result["tasks"]:
            if task["status"] == "running":
                task["status"] = "interrupted"

    def _action_state(self, run_id: str, action_id: str, state: str, **details):
        saved = self.store.action(run_id, action_id)
        if saved is None:
            return
        saved.update({"state": state, **details})
        with self.store.connect() as db:
            db.execute("UPDATE actions SET result=? WHERE run_id=? AND id=?",
                       (json.dumps(saved), run_id, action_id))

    def _normalize_tasks(self, run_id: str):
        """No job for this run is alive here, so a task saved as running was interrupted."""
        result = self.store.get(run_id)
        if any(task["status"] == "running" for task in result["tasks"]):
            self._interrupt_tasks(result)
            self.store.save(result)
        for task in result["tasks"]:
            if task["status"] == "exploring":
                self._close_round(run_id, task["id"])

    def _reconcile_actions(self, run_id: str):
        """Recognize durable effects; interrupted actions require a new decision."""
        result = self.store.get(run_id)
        with self.store.connect() as db:
            records = [(row[0], json.loads(row[1])) for row in db.execute(
                "SELECT id,result FROM actions WHERE run_id=?", (run_id,))]
        unresolved = []
        for identifier, saved in records:
            if saved.get("state") != "issued":
                continue
            action = saved.get("action", {})
            kind = action.get("action")
            complete = False
            persisted = {task["id"]: task for task in result["tasks"]}
            if kind == "plan":
                complete = bool(action.get("tasks")) and all(
                    task["id"] in persisted and all(persisted[task["id"]].get(key) == value
                                                   for key, value in task.items())
                    for task in action["tasks"])
            elif kind == "dispatch":
                ids = action.get("task_ids") or saved.get("task_ids", [])
                complete = bool(ids) and all(identifier in persisted and persisted[identifier]["status"]
                    in {"completed", "failed", "candidate", "discarded"} for identifier in ids)
            elif kind == "explore":
                variants = [v.get("id") for v in action.get("variants", [])]
                complete = bool(variants) and all(v in persisted and persisted[v]["status"] not in VARIANT_LIVE for v in variants)
            elif kind == "select_variant":
                parent = persisted.get((action.get("task_ids") or [None])[0]) or {}
                complete = parent.get("status") == "resolved" and parent.get("resolved_by") == action.get("selected_task")
            elif kind == "request_integration":
                complete = bool(result["artifacts"].get("integration_applied")
                                or result["artifacts"].get("verified_only"))
            elif kind == "finish":
                complete = result["status"] == "completed"
            elif kind in {"inspect_results", "search_ideas"}:
                complete = True
            state = "completed" if complete else "interrupted"
            self._action_state(run_id, identifier, state, recovered=True)
            if not complete:
                unresolved.append({"id": identifier, "action": kind,
                                   "message": "Interrupted action was not replayed; inspect saved effects and issue a new action ID."})
            self.store.event(run_id, "action_reconciled", {"id": identifier, "state": state})
        if unresolved:
            result["artifacts"].setdefault("interrupted_actions", []).extend(unresolved)
            self.store.save(result)

    def _persist_budget(self, run_id: str):
        clock = self._clocks.get(run_id)
        if clock is not None:
            started, previously_used = clock
            result = self.store.get(run_id)
            result["artifacts"]["runtime_seconds"] = round(previously_used + time.monotonic() - started, 3)
            self.store.save(result)

    async def _workspace_call(self, operation, *args):
        """Keep Studio responsive without abandoning an in-flight Git mutation."""
        call = asyncio.create_task(asyncio.to_thread(operation, *args))
        try:
            return await asyncio.shield(call)
        except asyncio.CancelledError:
            await asyncio.gather(call, return_exceptions=True)
            raise

    async def _worker_batch(self, run_id, spec, manager, tasks):
        jobs = [asyncio.create_task(self._worker(run_id, spec, manager, task)) for task in tasks]
        try:
            outcomes = await asyncio.gather(*jobs, return_exceptions=True)
        except BaseException:
            for job in jobs:
                if not job.done():
                    job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            raise
        if self.cancel_flags[run_id].is_set():
            raise asyncio.CancelledError()
        return [{"ok": False, "error": str(outcome) or type(outcome).__name__,
                 "code": "worker_exception"} if isinstance(outcome, BaseException) else outcome
                for outcome in outcomes]

    async def _reconcile_processes(self, run_id: str):
        """Stop a prior daemon's proven child identity before reusing its files."""
        from .providers import process_identity
        with self.store.connect() as db:
            events = [(row[0], json.loads(row[1])) for row in db.execute(
                "SELECT kind,data FROM events WHERE run_id=? AND (kind='process_reconciled' "
                "OR data LIKE '%parallax.process_started%' OR data LIKE '%parallax.process_finished%') ORDER BY sequence", (run_id,))]
        active = {}
        for kind, event in events:
            event_type = event.get("type")
            pid = event.get("pid")
            if event_type == "parallax.process_started":
                active[pid] = event
            elif event_type == "parallax.process_finished" or kind == "process_reconciled":
                active.pop(pid, None)
        private = Path(self.store.get(run_id)["artifacts"]["directory"]).resolve()
        for pid, event in active.items():
            if not isinstance(pid, int) or pid <= 1:
                raise RunProblem("Saved provider process identity is invalid")
            identity = await process_identity(pid)
            if identity is None:
                try: os.kill(pid,0)
                except ProcessLookupError: pass
                except PermissionError: raise RunProblem("An interrupted process exists but its identity cannot be inspected")
                else: raise RunProblem("An interrupted process exists but its identity cannot be inspected")
                disposition = "already_exited"
            elif not isinstance(event.get("identity"),dict) or not event["identity"].get("started_at") or not event["identity"].get("command_sha256"):
                raise RunProblem("An interrupted process has no durable identity; inspect it before resuming")
            elif identity != event.get("identity"):
                disposition = "pid_reused"
            else:
                if (os.name != "posix" or event.get("process_group") != pid
                        or not Path(event.get("cwd", "")).resolve().is_relative_to(private)):
                    raise RunProblem("An interrupted provider process cannot be safely reconciled")
                try:
                    if os.getpgid(pid)!=pid: raise RunProblem("Interrupted process no longer owns its saved process group")
                except ProcessLookupError:
                    self.store.event(run_id,"process_reconciled",{"pid":pid,"disposition":"already_exited"});continue
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                for _ in range(10):
                    if await process_identity(pid) != identity:
                        break
                    await asyncio.sleep(.1)
                if await process_identity(pid) == identity:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    for _ in range(10):
                        if await process_identity(pid)!=identity: break
                        await asyncio.sleep(.1)
                    if await process_identity(pid)==identity:
                        raise RunProblem("An owned process survived bounded termination; its workspace cannot be reused yet")
                disposition = "terminated_previous_attempt"
            self.store.event(run_id, "process_reconciled", {"pid": pid, "disposition": disposition})

    async def reconcile_children(self):
        """Reap proven orphaned children at startup, before waiting for Resume."""
        with self.store.connect() as db:
            runs = [json.loads(row[0]) for row in db.execute("SELECT result FROM runs")]
        for result in runs:
            try:
                await self._reconcile_processes(result["run_id"])
            except (RunProblem, OSError) as exc:
                result = self.store.get(result["run_id"])
                result["status"] = "needs_attention"
                result["errors"].append({"code":"process_reconciliation_failed","message":str(exc)})
                self.store.save(result)
                self.store.event(result["run_id"], "needs_attention", {"message":str(exc)})

    @staticmethod
    def _bound_session(result: dict, task_id: str, workspace: Path, participant: Participant,
                       mode: str, *, attempt: int | None = None) -> dict | None:
        for session in reversed(result["sessions"]):
            # Repairs share a checkout, so only the same attempt's conversation may be continued.
            if attempt is not None and session.get("attempt", 1) != attempt:
                continue
            if (session.get("task_id") == task_id and session.get("provider") == participant.provider
                    and Path(session.get("workspace", "")).resolve() == workspace.resolve()
                    and session.get("transport", "cli") == participant.transport
                    and session.get("connection_id") == participant.connection_id
                    and session.get("mode", mode) == mode and session.get("session_id")):
                requested = session.get("requested_settings") or {}
                if any(getattr(participant, key) is not None and key in requested and requested[key] != getattr(participant, key)
                       for key in ("model", "effort")):
                    continue
                return session
        return None

    @staticmethod
    def _session_participant(participant: Participant, session: dict | None) -> Participant:
        effective = (session or {}).get("effective_settings") or {}
        settings = {key: value for key, value in effective.items()
                    if key in {"model", "effort"} and (value is None or isinstance(value, str))}
        return participant.model_copy(update=settings)

    def _resume_session(self, run_id: str, task_id: str, workspace: Path,
                        participant: Participant, mode: str, *, attempt: int | None = None) -> dict | None:
        completed = self._bound_session(self.store.get(run_id), task_id, workspace, participant, mode, attempt=attempt)
        if completed is not None:
            return completed
        with self.store.connect() as db:
            events = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM events WHERE run_id=? AND kind='provider' AND task_id=? ORDER BY sequence DESC",
                (run_id, task_id))]
        for event in events:
            if attempt is not None and event.get("attempt", 1) != attempt:
                continue
            if (event.get("provider") != participant.provider or event.get("mode") != mode
                    or event.get("transport", "cli") != participant.transport
                    or event.get("connection_id") != participant.connection_id
                    or Path(event.get("workspace", "")).resolve() != workspace.resolve()):
                continue
            session = next((event.get(key) for key in ("session_id", "sessionId", "thread_id", "conversation_id")
                            if isinstance(event.get(key), str)), None)
            if session is None:
                continue
            try:
                uuid.UUID(session.removeprefix("api-") if participant.transport == "api" else session)
            except ValueError:
                continue
            if participant.transport == "api" and (event.get("type") != "api.session" or not session.startswith("api-")):
                continue
            effective = event.get("effective_settings") or {}
            if not effective and isinstance(event.get("model"), str):
                effective = {"model": event["model"]}
            return {"session_id": session, "effective_settings": effective}
        return None

    def recover(self):
        # Recovery must include old active runs beyond the history page limit.
        with self.store.connect() as db:
            saved = [json.loads(row[0]) for row in db.execute("SELECT result FROM runs")]
        for result in saved:
            if result["status"] not in TERMINAL | {"paused", "interrupted"}:
                result["status"] = "interrupted"
                self._interrupt_tasks(result)
                self.store.save(result)
                self.store.event(result["run_id"], "interrupted", {"message":"Runtime restarted. Resume reconciles saved work before continuing."})
            self._reconcile_actions(result["run_id"])

    async def validate_settings(self, spec: RunSpec):
        if len({p.provider for p in spec.team}) != len(spec.team):
            raise ValueError("Each provider can occupy one worker slot; select its model and connection in that slot")
        await self.registry.discover()
        for participant in [spec.coordinator, *spec.team]:
            self.registry.validate(participant)
        if not spec.team:
            raise ValueError("Choose at least one team member")
        if spec.mode != "review" and not any(p.role != "reviewer" for p in spec.team):
            raise ValueError("Build and Compare need at least one implementer")
        if spec.mode != "review" and not any(p.provider != spec.coordinator.provider for p in spec.team):
            raise ValueError("An independent reviewer from another provider is required")

    async def assess(self, workspace: str, roots=None, checks=None, participants=None) -> dict:
        providers = await self.registry.discover()
        result = await asyncio.to_thread(assess_project, workspace, roots, checks, providers=providers)
        for member in participants or []:
            try: self.registry.validate(member)
            except ValueError as exc:
                result.issues.append({"category": "provider_permission", "severity": "blocker", "provider": member.provider, "message": str(exc)})
                result.status = "blocked"
            if member.transport == "api":
                result.issues.append({"category": "configuration", "severity": "warning", "provider": member.provider, "message": "API execution is experimental; native CLI smoke tests do not validate this connection."})
        return result.model_dump()

    def recover_run(self, run_id: str, action: str) -> dict:
        result = self.store.get(run_id)
        if run_id in self.jobs and result["status"] != "paused":
            raise ValueError("Run is finishing post-run memory work; retry shortly")
        choices = recovery_options(result)
        if action not in {item["id"] for item in choices["actions"]} or action not in {"repair_candidate", "retry_interrupted"}:
            raise ValueError("This recovery action is not available for the recorded failure")
        message = "Reconcile interrupted work and inspect saved evidence before dispatching."
        if action == "repair_candidate":
            message = "Repair the candidate against the original acceptance criteria. Use independent findings and actual failed check output. Keep every required check."
        self.steer(run_id, message)
        self.store.event(run_id, "recovery_requested", {"action": action, "category": choices["category"]})
        return self.control(run_id, "resume")

    async def start(self, spec: RunSpec) -> dict:
        workspace = Path(spec.workspace).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError("Workspace does not exist")
        spec.workspace = str(workspace)
        # Every role packet carries the full request, so it must leave room for the rest of the packet.
        if spec.mode != "review" and len(spec.prompt) > REQUEST_LIMIT:
            raise ValueError(f"Build and Compare requests are limited to {REQUEST_LIMIT:,} characters")
        if spec.mode == "review" and len(spec.prompt) > PROMPT_LIMIT - 9000:
            raise ValueError(f"Review requests are limited to {PROMPT_LIMIT - 9000:,} characters")
        await self.validate_settings(spec)
        assessment = None
        if spec.mode != "review":
            assessment = await self.assess(str(workspace), spec.package_roots, spec.checks, [spec.coordinator, *spec.team])
            blockers = [item["message"] for item in assessment["issues"] if item["severity"] == "blocker"]
            if blockers: raise ValueError("Project assessment blocked: " + "; ".join(blockers))
            if not spec.checks: spec.checks = [CheckSpec.model_validate(c) for c in assessment["proposed_checks"]]
        run_id = str(uuid.uuid4())
        if spec.mode != "review":
            self.store.claim(str(workspace), run_id)
        result = RunResult(run_id=run_id, status="queued", spec=spec).model_dump()
        result["artifacts"] = {"directory":str(self.store.home / "runs" / run_id), "started_at":time.time(), "user_checks":[c.model_dump() for c in spec.checks]}
        if assessment:
            result["artifacts"]["assessment"] = assessment
            result["artifacts"]["required_checks"] = [c.model_dump() for c in spec.checks]
        self.store.save(result)
        self.store.event(run_id,"queued",{"mode":spec.mode})
        self._launch(run_id)
        return self.store.get(run_id)

    def _launch(self, run_id: str):
        self.cancel_flags[run_id] = asyncio.Event()
        self.wakeup[run_id] = asyncio.Event()
        job = asyncio.create_task(self._run(run_id))
        self.jobs[run_id] = job
        job.add_done_callback(lambda _: self.jobs.pop(run_id, None))

    def control(self, run_id: str, operation: str) -> dict:
        result = self.store.get(run_id)
        if operation == "pause":
            if result["status"] in TERMINAL | {"interrupted","paused"}:
                raise ValueError("Only an active run can pause")
            self.pause_flags.add(run_id)
            self.store.event(run_id,"pause_requested",{"message":"Active attempts finish; new work waits."})
        elif operation == "cancel":
            if result["status"] == "completed":
                raise ValueError("A completed run cannot be stopped")
            self.cancel_flags.setdefault(run_id,asyncio.Event()).set()
            self.wakeup.setdefault(run_id,asyncio.Event()).set()
            # A settled run whose job is still recording memory stops now; the in-flight distiller sees the flag.
            if run_id not in self.jobs or result["status"] in TERMINAL - {"completed"}:
                result["status"] = "cancelled"
                self.store.save(result)
                self.store.release(run_id)
            self.store.event(run_id,"cancel_requested")
        elif operation == "resume":
            if result["status"] not in {"paused","interrupted","needs_attention"}:
                raise ValueError("Only paused, interrupted, or needs-attention runs can resume")
            if result["artifacts"].get("integration_applied"):
                raise ValueError("Integration was already applied; start a new run")
            if run_id in self.jobs and result["status"] != "paused":
                # The run has settled but its job is still recording project memory; a resume now would be dropped.
                raise ValueError("Run is finishing post-run memory work; retry shortly")
            if result["spec"]["mode"] != "review":
                self.store.claim(result["spec"]["workspace"],run_id)
            self.pause_flags.discard(run_id)
            self.wakeup.setdefault(run_id,asyncio.Event()).set()
            if run_id not in self.jobs:
                result["status"] = "queued"
                self.store.save(result)
                self._launch(run_id)
            self.store.event(run_id,"resumed")
        else:
            raise ValueError("Unknown control operation")
        return self.store.get(run_id)

    def steer(self, run_id: str, message: str) -> dict:
        if not message.strip() or len(message)>20000:
            raise ValueError("Steering message must contain 1–20000 characters")
        result = self.store.get(run_id)
        if result["status"] in {"completed","failed","cancelled"}:
            raise ValueError("Start a new run to change a finished task")
        result["artifacts"].setdefault("steering",[]).append(message)
        self.store.save(result)
        return self.store.event(run_id,"steering",{"message":message,"applies":"next checkpoint"})

    async def checkpoint(self, run_id: str):
        self._persist_budget(run_id)
        if self.cancel_flags[run_id].is_set():
            raise asyncio.CancelledError()
        if run_id in self.pause_flags:
            previous = self.store.get(run_id)["status"]
            self._status(run_id,"paused")
            self.wakeup[run_id].clear()
            await self.wakeup[run_id].wait()
            if self.cancel_flags[run_id].is_set():
                raise asyncio.CancelledError()
            self._status(run_id, previous)

    def _status(self, run_id: str, status: str):
        result = self.store.get(run_id)
        result["status"] = status
        self.store.save(result)
        self.store.event(run_id,"status",{"status":status})

    def _task_update(self, run_id: str, task_id: str, **updates):
        result = self.store.get(run_id)
        for task in result["tasks"]:
            if task["id"] == task_id:
                task.update(updates)
                outcome=updates.get("result",{})
                if outcome and outcome.get("ok") is False:
                    task["failure_category"]=classify(str(outcome.get("error", "")))
        self.store.save(result)
        self.store.event(run_id,"task",updates,task_id)

    async def _provider(self, run_id: str, participant: Participant, workspace: Path, prompt,
                        *, mode="consult", task_id=None, schema=None, session_id=None, attempt=None,
                        role=None, timeout=None, quiet=False) -> dict:
        spec = RunSpec.model_validate(self.store.get(run_id)["spec"])
        tagged = {"attempt": attempt} if attempt is not None else {}
        manifest = None
        if isinstance(prompt, Packet):
            # Record what this agent is given (section names, sizes, hashes; never content) before it runs.
            manifest = prompt.manifest()
            role = role or manifest["role"]
            prompt = prompt.render()
            self.store.event(run_id, "context", {**manifest, "provider": participant.provider, "mode": mode,
                                                 "fresh_session": session_id is None, **tagged}, task_id)
        async def emit(event):
            if quiet and not (str(event.get("type", "")).startswith("parallax.") or event.get("type") == "api.session"):
                return  # Quiet calls keep only process and session bookkeeping, never streamed text.
            self.store.event(run_id,"provider",{**event,"provider":participant.provider,"workspace":str(workspace),"mode":mode,
                "transport":participant.transport,"connection_id":participant.connection_id,**tagged},task_id)
        extra={}
        from .connections import ConnectionRegistry
        if isinstance(self.registry,ConnectionRegistry):
            extra={"transport":participant.transport,"connection_id":participant.connection_id}
            if participant.transport=="api":
                task=next((t for t in self.store.get(run_id)["tasks"] if t["id"]==task_id),None)
                extra["allowed_files"]=task["files"] if task else []
        outcome = await self.registry.run(participant.provider, workspace=workspace, prompt=prompt,
            model=participant.model,effort=participant.effort,mode=mode,session_id=session_id,
            timeout=timeout or spec.limits.attempt_seconds,schema=schema,on_event=emit,cancel_event=self.cancel_flags[run_id],**extra)
        result = self.store.get(run_id)
        result["sessions"].append({"provider":participant.provider,"task_id":task_id,"transport":participant.transport,"connection_id":participant.connection_id,"mode":mode,
            "workspace":str(workspace),"session_id":outcome.get("session_id"),
            "requested_settings":outcome.get("requested_settings",{}),"effective_settings":outcome.get("effective_settings",{}),**tagged,
            **({"role":role} if role else {}),
            **({"context_sha256":manifest["sha256"],"context_chars":manifest["chars"]} if manifest else {})})
        usage = outcome.get("usage") or {}
        if usage:
            result["usage"].setdefault("reports",[]).append({"provider":participant.provider,"task_id":task_id,**usage,
                **({"role":role} if role else {}),**({"context_sha256":manifest["sha256"]} if manifest else {})})
        self.store.save(result)
        return outcome

    async def _run(self, run_id: str):
        from .workspaces import WorkspaceManager
        spec = RunSpec.model_validate(self.store.get(run_id)["spec"])
        run_dir = Path(self.store.get(run_id)["artifacts"]["directory"])
        manager = None
        used = self.store.get(run_id)["artifacts"].get("runtime_seconds", 0)
        self._clocks[run_id] = (time.monotonic(), used)
        try:
            run_dir.mkdir(parents=True,exist_ok=True)
            manager = WorkspaceManager(Path(spec.workspace),run_dir)
            self._normalize_tasks(run_id)
            self._reconcile_actions(run_id)
            await self._reconcile_processes(run_id)
            self._status(run_id,"planning")
            remaining = spec.limits.minutes * 60 - used
            if remaining <= 0:
                raise asyncio.TimeoutError()
            async with asyncio.timeout(remaining) if hasattr(asyncio,"timeout") else _timeout(remaining):
                if spec.mode == "review":
                    await self._review_run(run_id,spec,manager,run_dir)
                else:
                    metadata=await self._workspace_call(manager.prepare)
                    if metadata.get("applied"):
                        result=self.store.get(run_id)
                        result["status"]="completed"
                        result["artifacts"]["integration_applied"]=True
                        result["changed_files"]=metadata.get("applied_changed_files",[])
                        result["artifacts"]["preservation"]=metadata.get("preservation",{})
                        if not result["artifacts"].get("verification_record"):
                            from .receipt import save_receipt
                            save_receipt(result)
                        result["summary"] = result["summary"] or "Recovered an already verified integration."
                        self.store.save(result)
                        self.store.event(run_id,"completed",{"recovered":True})
                    else:
                        await self._baseline(run_id, spec, manager)
                        await self._build_run(run_id,spec,manager)
        except asyncio.CancelledError:
            result = self.store.get(run_id)
            self._interrupt_tasks(result)
            result["status"] = "interrupted" if self.shutting_down else "cancelled"
            self.store.save(result)
            self.store.event(run_id, result["status"], {"message": "Partial work and sessions were preserved."})
        except (RunProblem, ValueError, RuntimeError) as exc:
            result = self.store.get(run_id)
            result["status"] = "needs_attention"
            self._interrupt_tasks(result)
            result["errors"].append({"code":"run_blocked","category":classify(str(exc)),"message":str(exc)})
            try:
                result["diff"] = manager.diff()
            except Exception:
                pass
            self.store.save(result)
            self.store.event(run_id,"needs_attention",{"message":str(exc)})
        except (TimeoutError, asyncio.TimeoutError):
            self.cancel_flags[run_id].set()
            result = self.store.get(run_id)
            result["status"] = "needs_attention"
            self._interrupt_tasks(result)
            result["errors"].append({"code":"budget_exceeded","message":"Run time limit reached. Partial work is preserved."})
            self.store.save(result)
            self.store.event(run_id,"budget_exceeded")
        except Exception as exc:
            result = self.store.get(run_id)
            result["status"] = "failed"
            self._interrupt_tasks(result)
            result["errors"].append({"code":"runtime_error","message":str(exc)})
            self.store.save(result)
            self.store.event(run_id,"failed",{"message":str(exc)})
        finally:
            self._persist_budget(run_id)
            self._clocks.pop(run_id, None)
            if self.store.get(run_id)["status"] in TERMINAL:
                self.store.release(run_id)
        if not self.shutting_down and self.store.get(run_id)["status"] in TERMINAL:
            await self._after_run(run_id, spec)

    async def _review_run(self, run_id, spec, manager, run_dir):
        try:
            manager.prepare()
            root = manager.integration_path
        except (ValueError, RuntimeError):
            root = run_dir / "review-source"
            if not root.exists():
                shutil.copytree(spec.workspace,root,symlinks=True,ignore=shutil.ignore_patterns(".git","node_modules",".venv","__pycache__"))
            (root / ".parallax-owned").write_text(run_id)
        self._status(run_id,"reviewing")
        semaphore = asyncio.Semaphore(spec.limits.workers)
        async def review(index, member):
            async with semaphore:
                await self.checkpoint(run_id)
                target = run_dir / f"review-{index}"
                if not target.exists():
                    shutil.copytree(root,target,symlinks=True,ignore=shutil.ignore_patterns(".git"))
                (target / ".parallax-owned").write_text(run_id)
                from .workspaces import fingerprint
                before=fingerprint(target)
                outcome = await self._provider(run_id,member,target,consultant_packet(spec.prompt,task_id=f"review-{index}"),task_id=f"review-{index}",role="consultant")
                if fingerprint(target)!=before:
                    outcome={**outcome,"ok":False,"error":{"code":"readonly_changed","message":"Consultation changed its isolated workspace"}}
                return {"provider":member.provider,"ok":outcome.get("ok",False),"answer":outcome.get("answer"),"error":outcome.get("error")}
        reviews = await asyncio.gather(*(review(i,p) for i,p in enumerate(spec.team)))
        result = self.store.get(run_id)
        result["reviews"] = reviews
        self.store.save(result)
        if not any(r["ok"] for r in reviews):
            raise RunProblem("Every independent assessment failed; inspect provider diagnostics")
        await self.checkpoint(run_id)
        # Blind synthesis: assessments are lettered; the legend is attached only after the synthesis.
        packet, legend = synthesis_packet(spec.prompt, reviews, str(run_dir))
        outcome = await self._provider(run_id,spec.coordinator,root,packet,task_id="synthesis",role="synthesizer")
        if not outcome.get("ok"):
            raise RunProblem(str(outcome.get("error")))
        result = self.store.get(run_id)
        result["summary"] = (outcome.get("answer") or "") + "\n\nAssessment labels: " + ", ".join(f"{label} = {provider}" for label, provider in legend.items())
        result["status"] = "completed"
        self.store.save(result)
        self.store.event(run_id,"completed",{"summary":result["summary"]})

    def _validate_tasks(self,spec:RunSpec,tasks:list[TaskSpec],existing:list[dict]):
        implementers = {p.provider for p in spec.team if p.role != "reviewer"}
        ids = {t["id"] for t in existing}
        if len({t.id for t in tasks})!=len(tasks) or ids & {t.id for t in tasks}:
            raise ValueError("Task IDs must be unique")
        all_ids = ids | {t.id for t in tasks}
        graph = {t["id"]:t["dependencies"] for t in existing}
        graph.update({t.id:t.dependencies for t in tasks})
        variant_ids = {t["id"] for t in existing if t.get("variant_of")}
        if len(ids - variant_ids) + len(tasks) > MAX_TASKS:
            raise ValueError(f"A run holds at most {MAX_TASKS} planned tasks; extend or resolve existing tasks instead")
        for task in tasks:
            if len(task.title) > 200 or len(task.acceptance) > 20 or any(len(a) > 500 for a in task.acceptance) or len(task.files) > 100 or any(len(f) > 200 for f in task.files):
                raise ValueError(f"Task {task.id} is too large: titles are limited to 200 characters, acceptance to 20 items of 500 characters, and ownership to 100 paths of 200 characters")
            if task.id in RESERVED_IDS:
                raise ValueError(f"Task id {task.id} is reserved")
            if set(task.dependencies) & variant_ids:
                raise ValueError("Tasks cannot depend on an exploration variant; depend on the explored task instead")
            if task.provider not in implementers:
                raise ValueError(f"{task.provider} is not an enabled implementer")
            if not task.files:
                raise ValueError(f"Task {task.id} needs explicit relative file or directory ownership")
            for name in task.files:
                if not name or Path(name).is_absolute() or ".." in Path(name).parts or ".git" in Path(name).parts or name.startswith(".parallax"):
                    raise ValueError("Task ownership must stay inside project files")
            if not set(task.dependencies)<=all_ids:
                raise ValueError("Unknown task dependency")
        visiting, visited = set(), set()
        def visit(task):
            if task in visiting:
                raise ValueError("Task dependency cycle")
            if task in visited:
                return
            visiting.add(task)
            for dep in graph[task]: visit(dep)
            visiting.remove(task); visited.add(task)
        for task in graph: visit(task)

    async def _build_run(self,run_id,spec,manager):
        coordinator_dir = await self._workspace_call(manager.create_worker, "coordinator")
        # Saved sessions only pin the model and effort; every turn starts a fresh session from a compiled packet.
        bound = self._resume_session(run_id, "coordinator", coordinator_dir, spec.coordinator, "coordinate")
        coordinator = self._session_participant(spec.coordinator, bound)
        ideas = await self._ideas(run_id, spec)
        while self.store.get(run_id)["artifacts"].get("coordinator_turns", 0) < spec.limits.coordinator_turns:
            await self.checkpoint(run_id)
            result = self.store.get(run_id)
            turn = result["artifacts"].get("coordinator_turns", 0) + 1
            actions = self.store.actions(run_id)
            memory, search = await self._memory_context(run_id, ideas, result, actions, coordinator_dir)
            prompt = coordinator_packet(result, actions, turn=turn, memory=memory, search=search)
            self._status(run_id,"planning")
            result = self.store.get(run_id)
            result["artifacts"]["coordinator_turns"] = result["artifacts"].get("coordinator_turns", 0) + 1
            self.store.save(result)
            outcome = await self._provider(run_id,coordinator,coordinator_dir,prompt,mode="coordinate",task_id="coordinator",
                                           schema=CoordinatorAction.model_json_schema(),session_id=None,role="coordinator")
            if outcome.get("effective_settings"):
                coordinator = self._session_participant(coordinator, outcome)
            if not outcome.get("ok"):
                raise RunProblem(f"Coordinator failed: {outcome.get('error')}")
            try:
                raw = outcome.get("structured_output") or json.loads(outcome.get("answer") or "{}")
                action = CoordinatorAction.model_validate(raw)
            except (ValueError,TypeError) as exc:
                self.store.event(run_id,"action_rejected",{"message":str(exc)})
                self._coordinator_feedback(run_id, turn, "invalid_schema", None, str(exc))
                continue
            prior = self.store.action(run_id,action.id)
            if prior is not None:
                self.store.event(run_id,"action_rejected",{"message":"Duplicate action ID; saved result retained","id":action.id,"state":prior.get("state")})
                self._coordinator_feedback(run_id, turn, "duplicate_id", action.id, "This action id was already used; the saved result was kept. Use next_id.")
                continue
            tasks = action.task_ids or [t["id"] for t in self.store.get(run_id)["tasks"]
                if t["status"] in {"pending", "interrupted"} and not t.get("variant_of")]
            self.store.save_action(run_id,action.id,{"state":"issued","action":action.model_dump(), "task_ids":tasks})
            try:
                await self._action(run_id,spec,manager,action)
            except ValueError as exc:
                self._action_state(run_id, action.id, "failed", error=str(exc))
                self.store.event(run_id,"action_rejected",{"message":str(exc),"id":action.id})
                result=self.store.get(run_id)
                result["errors"].append({"code":"invalid_action","category":classify(str(exc)),"message":str(exc)})
                self.store.save(result)
            except asyncio.CancelledError:
                self._action_state(run_id, action.id, "interrupted", error="Run stopped before the action completed")
                raise
            except Exception as exc:
                self._action_state(run_id, action.id, "failed", error=str(exc))
                raise
            else:
                self._action_state(run_id, action.id, "completed")
            if self.store.get(run_id)["status"]=="completed":
                return
        raise RunProblem("Coordinator decision limit reached; work and evidence are preserved")

    def _coordinator_feedback(self, run_id, turn, kind, identifier, message):
        """Rejections that never reach the action journal are shown on the next fresh turn."""
        result = self.store.get(run_id)
        feedback = result["artifacts"].setdefault("coordinator_feedback", [])
        feedback.append({"turn": turn, "kind": kind, "id": identifier, "message": str(message)[:500]})
        del feedback[:-5]
        self.store.save(result)

    async def _action(self,run_id,spec,manager,action):
        result=self.store.get(run_id)
        if (result["artifacts"].get("integration_applied") or result["artifacts"].get("verified_only")) and action.action not in {"inspect_results","finish","search_ideas"}:
            raise ValueError("This candidate is finalized; only inspect_results or finish is allowed. Start a new run for further changes")
        self.store.event(run_id,"action",action.model_dump())
        if action.action=="plan":
            if not action.tasks: raise ValueError("A plan requires tasks")
            self._validate_tasks(spec,action.tasks,result["tasks"])
            for task in action.tasks:
                result["tasks"].append({**task.model_dump(),"status":"pending","attempts":0})
            if action.checks:
                spec.checks=action.checks
                result["spec"]=spec.model_dump()
            result["summary"]=action.summary
            result["artifacts"].pop("validated_fingerprint",None)
            self.store.save(result)
        elif action.action=="dispatch":
            ids=action.task_ids or [t["id"] for t in result["tasks"] if t["status"] in {"pending", "interrupted"} and not t.get("variant_of")]
            selected=[t for t in result["tasks"] if t["id"] in ids]
            if len(selected)!=len(set(ids)) or not selected: raise ValueError("Choose known pending tasks")
            if any(t.get("variant_of") for t in selected):
                parents={t.get("variant_of") for t in selected}
                parent=next((t for t in result["tasks"] if t["id"] in parents),None)
                if (len(parents)!=1 or not all(t.get("variant_of") for t in selected) or parent is None or parent["status"]!="exploring"
                        or parent.get("selecting") or any(t["status"] not in {"pending","interrupted","failed"} or t.get("variant_round")!=parent.get("explore_round") for t in selected)):
                    raise ValueError("Variants can be dispatched only to continue or repair variants of one task in its current exploration round")
                # A failed variant is repaired within its round, so one weak candidate does not cost a whole new round.
                if any(t["status"]=="failed" and t["attempts"]>spec.limits.repairs for t in selected):
                    raise ValueError("Variant repair limit reached; explore a new round instead")
                await self._run_variants(run_id,spec,manager,parent["id"],[t["id"] for t in selected])
                return
            done={t["id"] for t in result["tasks"] if t["status"] in {"completed","resolved"}}
            for task in selected:
                if task["status"] not in {"pending","failed","interrupted"}: raise ValueError("Task is not pending or repairable")
                if not set(task["dependencies"])<=done: raise ValueError("Task dependencies are not complete")
                # Only an attempt that was still in progress may continue past the budget; a finished failure may not.
                continuing=task["status"]=="interrupted" and (task.get("active_attempt") or {}).get("state","running") in {"running","implemented","interrupted","reviewed"}
                if not continuing and task["attempts"]>spec.limits.repairs: raise ValueError("Task repair limit reached")
            # The dispatch summary is the coordinator's brief to these workers.
            for task in selected:
                task["coordinator_note"]=(action.summary or "")[:2000]
            self.store.save(result)
            self._status(run_id,"running")
            # Overlapping ownership runs serially; disjoint tasks share a bounded batch.
            batches=[]
            for task in selected:
                placed=False
                for batch in batches:
                    if len(batch)<spec.limits.workers and all(not _overlap(task["files"],other["files"]) for other in batch):
                        batch.append(task);placed=True;break
                if not placed: batches.append([task])
            for batch in batches:
                await self.checkpoint(run_id)
                outcomes=await self._worker_batch(run_id,spec,manager,batch)
                for task,outcome in zip(batch,outcomes):
                    if not outcome["ok"]:
                        self._task_update(run_id,task["id"],status="failed",result=outcome)
                    elif spec.mode=="compare":
                        self._task_update(run_id,task["id"],status="completed",result=outcome)
                    else:
                        merged=await self._workspace_call(manager.merge, Path(outcome["workspace"]))
                        if merged["ok"]:
                            self._task_update(run_id,task["id"],status="completed",result={**outcome,"merge":merged})
                        else:
                            # A conflicting attempt must not be reused: the next dispatch counts against the
                            # repair budget and starts from the current integration candidate.
                            saved=next(t for t in self.store.get(run_id)["tasks"] if t["id"]==task["id"])
                            self._task_update(run_id,task["id"],status="failed",
                                result={**outcome,"ok":False,"error":"Merge conflict with the integration candidate: "+str(merged.get("error") or "")[:1000],"merge":merged},
                                active_attempt={**(saved.get("active_attempt") or {}),"state":"merge_failed","resume_safe":False})
                result=self.store.get(run_id)
                result["diff"]=manager.diff()
                result["artifacts"].pop("validated_fingerprint",None)
                self.store.save(result)
        elif action.action=="inspect_results":
            pass
        elif action.action=="explore":
            parent_id,variant_ids=self._prepare_exploration(run_id,spec,action)
            await self._run_variants(run_id,spec,manager,parent_id,variant_ids)
        elif action.action=="select_variant":
            await self._select_variant(run_id,manager,action)
        elif action.action=="search_ideas":
            ideas=await self._ideas(run_id,spec)
            if ideas is None: raise ValueError("Project memory is not available for this run")
            files=sorted({f for t in result["tasks"] if t["id"] in action.task_ids for f in t["files"]})
            hits=await asyncio.to_thread(ideas.search,action.query or spec.prompt,files,6,run_id)
            # Results stay in the local action journal (never mirrored) and appear in the next packet only.
            self._action_state(run_id,action.id,"issued",memory_results=hits)
            await asyncio.to_thread(ideas.expose,run_id,[h["id"] for h in hits],"search")
        elif action.action=="validate":
            checks=action.checks or spec.checks or _discover_checks(manager.integration_path)
            if not checks: raise ValueError("No meaningful checks configured. Supply project check argv commands")
            if spec.mode=="compare":
                for task in result["tasks"]:
                    if task["status"]=="completed":
                        evidence=await self._checks(run_id,Path(task["result"]["workspace"]),checks,task["id"],phase="alternative")
                        self._task_update(run_id,task["id"],checks=evidence)
            else:
                await self._verify(run_id,spec,manager,checks)
        elif action.action=="resolve_task":
            replacement=next((t for t in result["tasks"] if t["id"]==action.selected_task and t["status"]=="completed"),None)
            if spec.mode!="build" or not replacement or not action.task_ids:
                raise ValueError("Resolve requires failed tasks and a completed replacement in Build")
            if result["artifacts"].get("validated_fingerprint")!=manager.diff() or not result["checks"] or not all(c["ok"] for c in result["checks"]):
                raise ValueError("Resolve requires current combined verification")
            failed=[t for t in result["tasks"] if t["id"] in action.task_ids]
            if len(failed)!=len(set(action.task_ids)) or any(t["status"]!="failed" for t in failed):
                raise ValueError("Only known failed tasks can be resolved")
            for task in failed:
                if not all(any(_owned(path,scope) for scope in replacement["files"]) for path in task["files"]):
                    raise ValueError("Replacement does not cover the failed task's ownership")
                if task["attempts"]+replacement["attempts"]>spec.limits.repairs+1:
                    raise ValueError("Replacement exceeds the failed task's repair budget")
                candidates=[p for p in spec.team if p.role=="reviewer"]+[*spec.team,spec.coordinator]
                reviewer=next((p for p in candidates if p.provider not in {task["provider"],replacement["provider"]}),None)
                if reviewer is None: raise ValueError("Resolve needs an independent reviewer")
                owned=filter_patch(manager.diff(),lambda path,scopes=task["files"]:any(_owned(path,scope) for scope in scopes))
                review=await self._assess_patch(run_id,reviewer,manager.integration_path,spec.prompt,task,"resolution-"+task["id"],
                    evidence=result["checks"],patch=owned)
                if not review["ok"]: raise ValueError("Replacement does not satisfy the failed task's original requirements")
                self._task_update(run_id,task["id"],status="resolved",resolved_by=replacement["id"],resolution_review=review)
        elif action.action=="request_integration":
            if any(t["status"] not in INTEGRABLE for t in result["tasks"]):
                raise ValueError("Unfinished tasks block integration")
            if not result["tasks"]: raise ValueError("No implementation tasks")
            if spec.mode=="compare":
                chosen=next((t for t in result["tasks"] if t["id"]==action.selected_task),None)
                if not chosen or not chosen.get("checks") or not all(c["ok"] for c in chosen["checks"]):
                    raise ValueError("Choose an alternative with passing checks")
                merged=manager.merge(Path(chosen["result"]["workspace"]))
                if not merged["ok"]: raise RunProblem(merged["error"])
                result=self.store.get(run_id)
                result["artifacts"]["selected_task"]=chosen["id"]
                self.store.save(result)
                await self._verify(run_id,spec,manager,action.checks or spec.checks or _discover_checks(manager.integration_path))
            await self._integrate(run_id,spec,manager)
        elif action.action=="finish":
            if not result["artifacts"].get("integration_applied") and not result["artifacts"].get("verified_only"):
                raise ValueError("Verification and request_integration are required before finishing")
            result["status"]="completed"
            result["summary"]=action.summary or result["summary"]
            self.store.save(result)
            self.store.event(run_id,"completed",{"summary":result["summary"]})

    async def _ideas(self, run_id, spec):
        """The project's idea graph, or None when memory is off, in review mode, or unavailable."""
        if not self.memory or spec.mode == "review":
            return None
        try:
            from .ideas import IdeaStore
            return await asyncio.to_thread(IdeaStore, self.store.home, spec.workspace)
        except Exception as exc:
            self._memory_unavailable(run_id, exc)
            return None

    def _memory_unavailable(self, run_id, exc):
        if run_id not in self._memory_failed:
            self._memory_failed.add(run_id)
            self.store.event(run_id, "memory_unavailable", {"reason": type(exc).__name__})

    async def _memory_context(self, run_id, ideas, result, actions, workspace):
        """Primer (computed once per run, ids only in the run) and the latest search, rendered fresh from local memory."""
        if ideas is None:
            return [], []
        try:
            primer = (result["artifacts"].get("memory") or {}).get("primer")
            if primer is None:
                text = " ".join([result["spec"]["prompt"], *(t.get("title", "") for t in result["tasks"])])
                files = sorted({f for t in result["tasks"] for f in t.get("files", [])})
                primer = [hit["id"] for hit in await asyncio.to_thread(ideas.search, text, files, 6, run_id)]
                saved = self.store.get(run_id)
                saved["artifacts"]["memory"] = {**(saved["artifacts"].get("memory") or {}), "primer": primer}
                self.store.save(saved)
                await asyncio.to_thread(ideas.expose, run_id, primer, "primer")
            memory = await asyncio.to_thread(ideas.render, primer, str(workspace))
            newest = actions[-1] if actions else {}
            search = []
            if (newest.get("action") or {}).get("action") == "search_ideas":
                search = await asyncio.to_thread(ideas.render, [h["id"] for h in newest.get("memory_results", [])], str(workspace))
            return memory, search
        except Exception as exc:
            self._memory_unavailable(run_id, exc)
            return [], []

    async def _after_run(self, run_id, spec):
        """Project the finished run's facts into project memory. Never changes the run's status."""
        ideas = await self._ideas(run_id, spec)
        if ideas is None:
            return
        try:
            with self.store.connect() as db:
                checks = [{"sequence": row[0], "task_id": row[1], "data": json.loads(row[2])} for row in db.execute(
                    "SELECT sequence,task_id,data FROM events WHERE run_id=? AND kind='check' ORDER BY sequence", (run_id,))]
            await asyncio.to_thread(ideas.project, self.store.get(run_id), checks)
        except Exception as exc:
            self._memory_unavailable(run_id, exc)
            return
        await self._distill(run_id, spec, ideas)

    async def _distill(self, run_id, spec, ideas):
        """Meta-agent distillation: one fresh, quiet session turns this run's facts into at most three grounded lessons."""
        result = self.store.get(run_id)
        errors = result.get("errors") or []
        if (spec.mode not in {"build", "compare"} or result["status"] not in {"completed", "failed", "needs_attention"}
                or (errors and errors[-1].get("code") == "budget_exceeded") or self.cancel_flags.get(run_id, asyncio.Event()).is_set()
                or not any(t.get("attempts") for t in result["tasks"])):
            return
        try:
            digest = await asyncio.to_thread(ideas.digest, run_id)
            if not digest or not digest["evidence"] or digest["sha256"] == await asyncio.to_thread(ideas.distilled, run_id):
                return
            directory = Path(result["artifacts"]["directory"]) / "distill"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / ".parallax-owned").write_text(run_id)
            candidates = [p for p in spec.team if p.role == "reviewer"] + [p for p in spec.team if p.role != "reviewer"]
            distiller = next((p for p in candidates if p.provider != spec.coordinator.provider), spec.coordinator)
            from .ideas import DISTILL_SCHEMA
            outcome = await self._provider(run_id, distiller, directory, distiller_packet(digest, memory_scrubber(result["artifacts"]["directory"], spec.workspace)), mode="consult", task_id="distill",
                                           role="distiller", schema=DISTILL_SCHEMA, timeout=min(spec.limits.attempt_seconds, 180), quiet=True)
            if not outcome.get("ok"):
                raise RunProblem("distiller_failed")
            payload = outcome.get("structured_output")
            if payload is None:
                payload = json.loads(outcome.get("answer") or "{}")
            applied = await asyncio.to_thread(ideas.apply_distillation, run_id, payload, digest, distiller.provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, RunProblem) else type(exc).__name__
            self.store.event(run_id, "memory_distill_failed", {"code": code[:80]})
            return
        saved = self.store.get(run_id)
        saved["artifacts"]["memory"] = {**(saved["artifacts"].get("memory") or {}), "distilled": len(applied["accepted"]),
                                        "rejected": len(applied["rejected"])}
        self.store.save(saved)
        # Counts and reason codes only: lesson text stays in local memory.
        self.store.event(run_id, "memory_distilled", {"accepted": len(applied["accepted"]),
                                                      "rejected": [r["reason"] for r in applied["rejected"]]})

    def _prepare_exploration(self, run_id, spec, action):
        """Validate an explore action and persist its variants in one write. No engine loop decides what to try."""
        result = self.store.get(run_id)
        tasks = {t["id"]: t for t in result["tasks"]}
        if spec.mode != "build":
            raise ValueError("Exploration is available in Build runs")
        if len(action.task_ids) != 1 or action.task_ids[0] not in tasks:
            raise ValueError("Explore exactly one known task")
        parent = tasks[action.task_ids[0]]
        if parent.get("variant_of"):
            raise ValueError("Variants cannot be explored further; explore their task")
        live = [t for t in result["tasks"] if t.get("variant_of") == parent["id"] and t["status"] in VARIANT_LIVE]
        if not (parent["status"] in {"pending", "failed"} or (parent["status"] == "exploring" and not live and not parent.get("selecting"))):
            raise ValueError("Only a pending or failed task, or a finished exploration round, can be explored")
        if not all(tasks.get(d, {}).get("status") in TASK_DONE for d in parent["dependencies"]):
            raise ValueError("Task dependencies are not complete")
        if parent["attempts"] > spec.limits.repairs:
            raise ValueError("Task repair limit reached")
        if spec.limits.workers < 2 or not 2 <= len(action.variants) <= spec.limits.workers:
            raise ValueError(f"Explore between 2 and {spec.limits.workers} variants; it needs at least 2 concurrent workers")
        ids = [v.id for v in action.variants]
        if len(set(ids)) != len(ids) or set(ids) & set(tasks) or set(ids) & RESERVED_IDS:
            raise ValueError("Variant ids must be new, unique, and not reserved")
        tokens = []
        for variant in action.variants:
            if len(variant.directive) > 4000:
                raise ValueError("A variant directive is limited to 4,000 characters")
            words = set(re.findall(r"[a-z0-9]+", variant.directive.lower()))
            if any(not words or len(words & other) / len(words | other) >= 0.8 for other in tokens):
                raise ValueError("Variant directives must describe substantially different approaches")
            tokens.append(words)
        implementers = {p.provider for p in spec.team if p.role != "reviewer"}
        reviewers = [p.provider for p in spec.team if p.role == "reviewer"] + [spec.coordinator.provider, *[p.provider for p in spec.team]]
        for variant in action.variants:
            provider = variant.provider or parent["provider"]
            if provider not in implementers:
                raise ValueError(f"{provider} is not an enabled implementer")
            if not any(r != provider for r in reviewers):
                raise ValueError(f"No independent reviewer is available for {provider}")
        required = result["artifacts"].get("required_checks", [])
        keys = {(tuple(c.argv), c.cwd, c.timeout) for c in spec.checks}
        if not spec.checks or any((tuple(c["argv"]), c.get("cwd", "."), c.get("timeout", 120)) not in keys for c in required):
            raise ValueError("Exploration needs the configured project checks to compare variants")
        round_number = parent.get("explore_round", 0) + 1
        for task in result["tasks"]:
            if task.get("variant_of") == parent["id"] and task["status"] != "completed":
                task.update(status="discarded", discarded_reason="superseded")
        spec_fields = {key: parent[key] for key in ("title", "prompt", "files", "acceptance", "dependencies")}
        for variant in action.variants:
            result["tasks"].append({**spec_fields, "id": variant.id, "provider": variant.provider or parent["provider"],
                                    "variant_of": parent["id"], "variant_round": round_number, "directive": variant.directive,
                                    "status": "pending", "attempts": 0})
        parent.update(status="exploring", attempts=parent["attempts"] + 1, explore_round=round_number)
        parent.pop("selecting", None)
        self.store.save(result)
        for variant in action.variants:
            self.store.event(run_id, "task", {"status": "pending", "variant_of": parent["id"], "variant_round": round_number}, variant.id)
        self.store.event(run_id, "task", {"status": "exploring", "explore_round": round_number}, parent["id"])
        return parent["id"], ids

    async def _run_variants(self, run_id, spec, manager, parent_id, ids):
        """Run variants in parallel isolated checkouts, then check each in its own sandbox. Nothing is merged."""
        self._status(run_id, "running")
        await self.checkpoint(run_id)
        records = [t for t in self.store.get(run_id)["tasks"] if t["id"] in ids]
        try:
            outcomes = await self._worker_batch(run_id, spec, manager, records)
            for record, outcome in zip(records, outcomes):
                if not outcome["ok"]:
                    self._task_update(run_id, record["id"], status="failed", result=outcome)
                    continue
                await self.checkpoint(run_id)
                try:
                    evidence = await self._checks(run_id, Path(outcome["workspace"]), spec.checks, record["id"], phase="alternative")
                except ValueError as exc:
                    # A variant that breaks its own check environment fails alone; its siblings keep their results.
                    self._task_update(run_id, record["id"], status="failed",
                                      result={**outcome, "ok": False, "error": "Variant checks could not run: " + str(exc)[:1000]})
                    continue
                failing = [c["name"] for c in evidence if not c["ok"]]
                if failing:
                    self._task_update(run_id, record["id"], status="failed", checks=evidence,
                                      result={**outcome, "ok": False, "error": "Variant checks failed: " + ", ".join(failing)})
                else:
                    self._task_update(run_id, record["id"], status="candidate", checks=evidence, result=outcome)
        finally:
            result = self.store.get(run_id)
            stranded = [t for t in result["tasks"] if t["id"] in ids and t["status"] == "running"]
            if stranded:
                for task in stranded:
                    task["status"] = "interrupted"
                self.store.save(result)
            self._close_round(run_id, parent_id)

    def _close_round(self, run_id, parent_id):
        """A round with no candidate and nothing still running returns its task to failed."""
        result = self.store.get(run_id)
        parent = next((t for t in result["tasks"] if t["id"] == parent_id), None)
        if parent is None or parent["status"] != "exploring":
            return
        current = [t for t in result["tasks"] if t.get("variant_of") == parent_id and t.get("variant_round") == parent.get("explore_round")]
        if any(t["status"] in VARIANT_LIVE | {"candidate"} for t in current):
            return
        for task in current:
            task.update(status="discarded", discarded_reason="round_failed")
        parent.update(status="failed", result={"ok": False, "error": f"Exploration round {parent.get('explore_round')} produced no selectable candidate"})
        parent.pop("selecting", None)
        self.store.save(result)
        self.store.event(run_id, "task", {"status": "failed", "explore_round": parent.get("explore_round")}, parent_id)

    async def _select_variant(self, run_id, manager, action):
        result = self.store.get(run_id)
        tasks = {t["id"]: t for t in result["tasks"]}
        parent = tasks.get((action.task_ids or [None])[0])
        chosen = tasks.get(action.selected_task or "")
        if parent is None or parent["status"] != "exploring" or len(action.task_ids) != 1:
            raise ValueError("Select a variant of a task that is being explored")
        if (chosen is None or chosen.get("variant_of") != parent["id"] or chosen["status"] != "candidate"
                or chosen.get("variant_round") != parent.get("explore_round")):
            raise ValueError("Choose a candidate variant from the current exploration round")
        if parent.get("selecting") not in (None, chosen["id"]):
            raise ValueError(f"Variant {parent['selecting']} is already being selected; select it again to finish")
        parent["selecting"] = chosen["id"]
        self.store.save(result)
        merged = await self._workspace_call(manager.merge, Path(chosen["result"]["workspace"]))
        result = self.store.get(run_id)
        tasks = {t["id"]: t for t in result["tasks"]}
        parent, chosen = tasks[parent["id"]], tasks[chosen["id"]]
        if not merged["ok"]:
            parent.pop("selecting", None)
            self.store.save(result)
            raise ValueError("The selected variant conflicts with the integration candidate: " + str(merged.get("error") or "")[:500])
        chosen.update(status="completed", result={**chosen["result"], "merge": merged})
        parent.update(status="resolved", resolved_by=chosen["id"], resolution="variant_selection")
        parent.pop("selecting", None)
        for task in result["tasks"]:
            if task.get("variant_of") == parent["id"] and task["id"] != chosen["id"] and task["status"] != "discarded":
                task.update(status="discarded", discarded_reason="not_selected")
        result["diff"] = manager.diff()
        result["artifacts"].pop("validated_fingerprint", None)
        self.store.save(result)
        self.store.event(run_id, "task", {"status": "resolved", "resolved_by": chosen["id"]}, parent["id"])

    async def _worker(self,run_id,spec,manager,task):
        member=next(p for p in spec.team if p.provider==task["provider"] and p.role!="reviewer")
        previous = task.get("active_attempt") or {}
        if (task["status"] == "interrupted" and previous.get("state") in {"failed", "merge_failed"}
                and task.get("result", {}).get("ok") is False):
            # The attempt already finished and failed before the crash; report it instead of re-running it.
            self._task_update(run_id, task["id"], status="running", active_attempt=previous)
            return task["result"]
        reuse = bool(previous.get("workspace") and previous.get("worker_id")
                     and previous.get("participant") == member.model_dump()
                     and previous.get("resume_safe", True)
                     and task["status"] in {"interrupted", "failed"})
        attempt = task["attempts"] if reuse and task["status"] == "interrupted" else task["attempts"] + 1
        worker_id = previous["worker_id"] if reuse else f"{task['id']}-{attempt}"
        target = await self._workspace_call(manager.create_worker, worker_id)
        active = {"number": attempt, "worker_id": worker_id, "workspace": str(target),
                  "participant": member.model_dump(), "state": "running", "resume_safe": True}
        if reuse:
            if Path(previous["workspace"]).resolve() != target.resolve():
                raise ValueError("Saved attempt workspace does not match its owned checkout")
            if (previous.get("state") == "reviewed" and task.get("result", {}).get("ok")
                    and previous.get("reviewed_fingerprint") == manager.fingerprint(target)):
                self._task_update(run_id, task["id"], status="running", active_attempt=previous)
                return task["result"]
            partial = await self._workspace_call(manager.collect, target)
            outside = [name for name in partial["changed_files"]
                       if not any(_owned(name, pattern) for pattern in task["files"])]
            if not partial["ok"] or outside:
                active.update({"state": "failed", "resume_safe": False})
                failed = {"ok": False, "workspace": str(target), "changed_files": partial["changed_files"],
                          "error": partial["error"] or "Interrupted attempt changed files outside ownership: " + ", ".join(outside)}
                self._task_update(run_id, task["id"], status="running", attempts=attempt,
                                  active_attempt=active, result=failed)
                return failed
        self._task_update(run_id,task["id"],status="running",attempts=attempt,active_attempt=active)
        saved = self.store.get(run_id)
        # Only a crash continuation of the same interrupted attempt resumes its conversation. Repairs keep
        # the code state (or start from a fresh checkout) but begin a new session from the repair brief.
        continuing = reuse and task["status"] == "interrupted"
        bound = self._resume_session(run_id, task["id"], target, member, "edit", attempt=attempt) if continuing else None
        session = bound["session_id"] if bound else None
        if bound is None and previous.get("participant") == member.model_dump() and previous.get("effective_settings"):
            # Keep the model and effort the earlier attempt actually ran with.
            bound_settings = {"effective_settings": previous["effective_settings"]}
        else:
            bound_settings = bound
        resumed_member = self._session_participant(member, bound_settings)
        instructions={}
        for name in saved["artifacts"].get("assessment",{}).get("instructions",[])[:32]:
            path=target/name
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(target.resolve()):
                instructions[name]=path.read_text(errors="replace")[:8000]
        prompt=worker_packet(saved, task, continuing=continuing, fresh_checkout=(not reuse and bool(task.get("result"))),
                             instructions=instructions, limits=spec.limits)
        try:
            outcome=await self._provider(run_id,resumed_member,target,prompt,mode="edit",task_id=task["id"],session_id=session,
                                         attempt=attempt,role="worker")
        except asyncio.CancelledError:
            active["state"] = "interrupted"
            self._task_update(run_id, task["id"], active_attempt=active)
            raise
        active.update({"state":"implemented", "session_id":outcome.get("session_id"),
                       "effective_settings":outcome.get("effective_settings",{})})
        self._task_update(run_id, task["id"], active_attempt=active)
        collected=await self._workspace_call(manager.collect, target)
        def finish(value, state="failed", resume_safe=True):
            active.update({"state":state,"resume_safe":resume_safe})
            self._task_update(run_id,task["id"],active_attempt=active,result=value)
            return value
        if self.cancel_flags[run_id].is_set():
            finish({**collected,"ok":False,"error":"Run stopped; partial work was preserved", "workspace":str(target)}, "interrupted")
            raise asyncio.CancelledError()
        if not collected["ok"]: return finish({"ok":False,"error":collected["error"],"workspace":str(target),"provider_result":_handoff(outcome)}, resume_safe=False)
        outside=[name for name in collected["changed_files"] if not any(_owned(name,pattern) for pattern in task["files"])]
        if outside: return finish({"ok":False,"error":"Changed files outside ownership: "+", ".join(outside),"workspace":str(target),"provider_result":_handoff(outcome),"changed_files":collected["changed_files"]}, resume_safe=False)
        if not outcome.get("ok"): return finish({**collected,"ok":False,"error":outcome.get("error"),"workspace":str(target),"provider_result":_handoff(outcome)})
        if not collected["changed_files"]: return finish({"ok":False,"error":"Implementation produced no changes","workspace":str(target),"provider_result":_handoff(outcome)})
        reviewer=next((p for p in spec.team if p.provider!=member.provider and p.role=="reviewer"),None) or next((p for p in [spec.coordinator,*spec.team] if p.provider!=member.provider),None)
        if reviewer is None: return finish({"ok":False,"error":"No independent reviewer","workspace":str(target)})
        requirements={**task,"id":task.get("variant_of") or task["id"]}
        review=await self._assess_patch(run_id,reviewer,target,spec.prompt,requirements,task["id"],patch=collected.get("patch") or "")
        if not review["ok"]: return finish({**collected,"ok":False,"error":"Independent review rejected the change","workspace":str(target),"review":review,"provider_result":_handoff(outcome)})
        active["reviewed_fingerprint"] = manager.fingerprint(target)
        return finish({**collected,"ok":True,"workspace":str(target),"review":review,"provider_result":_handoff(outcome)}, "reviewed")

    async def _assess_patch(self,run_id,reviewer,target,request,task,task_id,*,evidence=None,patch="",patch_budget=40000):
        from .workspaces import fingerprint
        before=fingerprint(target)
        schema={"type":"object","properties":{"approved":{"type":"boolean"},"findings":{"type":"array","items":{"type":"string"}},"summary":{"type":"string"}},"required":["approved","findings","summary"],"additionalProperties":False}
        # The evaluator sees the request, the original requirements, this candidate's patch, and this candidate's
        # evidence only: never the implementer's identity or narrative, prior reviews, or other candidates.
        packet=review_packet(request,task,patch=patch,evidence=evidence,patch_budget=patch_budget,task_id="review-"+task_id,
                             run_dir=self.store.get(run_id)["artifacts"].get("directory"))
        for attempt in range(2):
            outcome=await self._provider(run_id,reviewer,target,packet,task_id="review-"+task_id,schema=schema,role="reviewer")
            try:
                structured=outcome.get("structured_output") or json.loads(outcome.get("answer") or "{}")
            except ValueError:
                structured={}
            if not isinstance(structured,dict):
                structured={}
            verdict=isinstance(structured.get("approved"),bool)
            # A reply without a verdict (prose instead of the schema) is not a rejection; ask once more, freshly.
            if verdict or not outcome.get("ok") or fingerprint(target)!=before:
                break
        unchanged=fingerprint(target)==before
        error=outcome.get("error")
        if not unchanged:
            error={"code":"readonly_changed","message":"Reviewer changed its isolated workspace"}
        elif outcome.get("ok") and not verdict:
            error={"code":"no_verdict","message":"The reviewer returned no verdict"}
        review={"provider":reviewer.provider,"task_id":task_id,"ok":bool(unchanged and outcome.get("ok") and structured.get("approved") is True),"findings":structured.get("findings",[]) if isinstance(structured.get("findings"),list) else [],"summary":structured.get("summary",outcome.get("answer") or ""),"error":error}
        result=self.store.get(run_id);result["reviews"].append(review);self.store.save(result)
        self.store.event(run_id,"review",review,task_id)
        return review

    def _validate_checks(self,run_id,workspace,checks):
        if not checks: raise ValueError("No meaningful check commands configured")
        explicit=[(c["argv"], c.get("cwd", ".")) for c in self.store.get(run_id)["artifacts"].get("user_checks",[])]
        for check in checks:
            if not check.argv or any(not isinstance(a,str) or not a or "\x00" in a for a in check.argv): raise ValueError("Invalid check argv")
            root = package_directory(workspace, check.cwd)
            if (check.argv, check.cwd) not in explicit and not _project_check(check.argv,root):
                raise ValueError("Coordinator proposed a command outside project verification. Configure an explicit check in Studio: "+check.name)

    async def _command(self,run_id,argv,workspace,env,timeout,*,writable=(),readable=(),network=False,task_id=None):
        from .providers import _capture
        async def event(data):
            if data.get("type") in {"parallax.process_started","parallax.process_finished","parallax.process_termination_failed"}:
                self.store.event(run_id,"process",data,task_id)
        return await _capture(_sandbox_check(argv,workspace,writable=writable,readable=readable,network=network),
            cwd=workspace,env=env,timeout=timeout,cancel_event=self.cancel_flags[run_id],on_event=event,max_output=8*1024*1024)

    async def _ensure_environment(self,run_id,workspace,checks):
        """Resolve declared dependencies only into this run's private environment."""
        wants_node={Path(c.argv[0]).name for c in checks}&{"npm","pnpm","yarn"}
        wants_python=any(Path(c.argv[0]).name.startswith("python") for c in checks)
        lock=next((p for p in (workspace/"package-lock.json",workspace/"npm-shrinkwrap.json") if p.is_file()),None)
        requirements=workspace/"requirements.txt";pyproject=workspace/"pyproject.toml"
        dependencies=[];package={}
        for path in (requirements,pyproject,lock,workspace/"package.json"):
            if path and path.exists() and (not path.is_file() or path.is_symlink() or path.stat().st_size>1_000_000):
                raise ValueError("Dependency manifests must be regular files below the 1 MB limit")
        if wants_node and (workspace/"package.json").is_file():
            try: package=json.loads((workspace/"package.json").read_text())
            except (OSError,ValueError): raise ValueError("Cannot parse project package.json")
            if not isinstance(package,dict): raise ValueError("Project package.json must contain an object")
        if wants_python and pyproject.is_file():
            try:
                try: import tomllib
                except ImportError: import tomli as tomllib
                project=tomllib.loads(pyproject.read_text()).get("project",{})
                dependencies=project.get("dependencies",[])
                if not isinstance(dependencies,list) or len(dependencies)>1000 or any(not isinstance(d,str) or not d.strip() or len(d)>2048 for d in dependencies): raise ValueError
            except (ImportError,ValueError,OSError,AttributeError):
                raise ValueError("Cannot parse declared Python dependencies; use a valid pyproject.toml or requirements.txt")
        node_needed=bool(wants_node and (lock or package.get("dependencies") or package.get("devDependencies")))
        if node_needed:
            if wants_node!={"npm"} or not lock:
                raise ValueError("Automatic Node provisioning requires npm checks and package-lock.json or npm-shrinkwrap.json; configure the project environment before using other package managers")
            ignored=await asyncio.create_subprocess_exec("git","-C",str(workspace),"check-ignore","--no-index","node_modules/.parallax-probe",stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            try: status=await asyncio.wait_for(ignored.wait(),10)
            except asyncio.TimeoutError:
                ignored.kill();await ignored.wait();raise ValueError("Cannot verify that node_modules is ignored")
            if status!=0: raise ValueError("Private npm provisioning requires node_modules to be gitignored so verification preserves source")
        python_needed=bool(wants_python and (requirements.is_file() or dependencies))
        if not node_needed and not python_needed: return {},None
        run_dir=Path(self.store.get(run_id)["artifacts"]["directory"]).resolve()
        digest=hashlib.sha256(str(workspace.resolve()).encode())
        for path in (requirements,pyproject,lock,workspace/"package.json"):
            if path and path.is_file(): digest.update(path.read_bytes())
        environment=run_dir/"environments"/digest.hexdigest()[:16]
        environment.mkdir(parents=True,exist_ok=True)
        private_home=environment/"home";private_home.mkdir(exist_ok=True)
        env={"PATH":os.environ.get("PATH","/usr/bin:/bin"),"HOME":str(private_home),"TMPDIR":str(environment),"TMP":str(environment),"TEMP":str(environment),"CI":"true","PYTHONDONTWRITEBYTECODE":"1"}
        steps=[];python=None
        if node_needed:
            steps.append(("npm dependencies",["npm","ci","--ignore-scripts","--no-audit","--no-fund","--cache",str(environment/"npm-cache")]))
        if python_needed:
            python=environment/"venv"/"bin"/"python"
            if not (environment/"python-ready").is_file() or not python.is_file():
                steps.append(("Python environment",[sys.executable,"-m","venv",str(environment/"venv")]))
                args=[str(python),"-m","pip","install","--disable-pip-version-check","--no-cache-dir"]
                args+=(["-r",str(requirements)] if requirements.is_file() else dependencies)
                steps.append(("Python dependencies",args))
        for name,argv in steps:
            await self.checkpoint(run_id)
            try: outcome=await self._command(run_id,argv,workspace,env,300,writable=[environment],readable=[environment],network=True)
            except OSError as exc: raise ValueError(name+" could not start; private environment preserved") from exc
            output=(outcome.stdout+outcome.stderr)[-4000:]
            self.store.event(run_id,"environment",{"name":name,"ok":outcome.exit_code==0 and not outcome.failure,"output":output,"error":outcome.failure})
            if outcome.failure=="process_termination_failed": raise RunProblem(name+" process survived termination; private environment preserved for inspection")
            if outcome.failure=="cancelled": raise asyncio.CancelledError()
            if outcome.failure or outcome.exit_code!=0: raise ValueError(name+" failed; private environment preserved: "+output)
        if python: (environment/"python-ready").write_text("installed")
        return ({"VIRTUAL_ENV":str(python.parent.parent),"PATH":str(python.parent)+os.pathsep+os.environ.get("PATH","")} if python else {}),python

    async def _checks(self,run_id,workspace,checks,task_id=None,phase="final"):
        required=self.store.get(run_id)["artifacts"].get("required_checks",[])
        if required and phase!="baseline":
            keys={(tuple(c.argv),c.cwd,c.timeout) for c in checks}
            if any((tuple(c["argv"]),c.get("cwd","."),c.get("timeout",120)) not in keys for c in required):
                raise ValueError("Every configured check remains required; a coordinator cannot remove or weaken a check")
        self._validate_checks(run_id,workspace,checks)
        self._status(run_id,"validating")
        evidence=[]
        environments={}
        for relative in dict.fromkeys(c.cwd for c in checks):
            root=package_directory(workspace,relative)
            group=[c.model_copy(update={"cwd":"."}) for c in checks if c.cwd==relative]
            environments[relative]=await self._ensure_environment(run_id,root,group)
        for check in checks:
            root=package_directory(workspace,check.cwd)
            environment,project_python=environments[check.cwd]
            await self.checkpoint(run_id)
            started=time.monotonic()
            temporary=Path(self.store.get(run_id)["artifacts"]["directory"])/"tmp"/str(uuid.uuid4());temporary.mkdir(parents=True)
            env={k:os.environ[k] for k in ("PATH","LANG","LC_ALL") if k in os.environ}
            env.update(environment)
            env.update(HOME=str(temporary),TMPDIR=str(temporary),TMP=str(temporary),TEMP=str(temporary),CI="true",PYTHONDONTWRITEBYTECODE="1",PARALLAX_OWNED_WORKSPACE=str(workspace))
            if (root/"src").is_dir() and (root/"pyproject.toml").is_file():
                env["PYTHONPATH"]=str(root/"src")+os.pathsep+str(root)
            command=list(check.argv)
            if project_python and Path(command[0]).name.startswith("python"): command[0]=str(project_python)
            try:
                outcome=await self._command(run_id,command,root,env,check.timeout,writable=[temporary],
                    readable=[project_python.parent.parent] if project_python else [],task_id=task_id)
                output=(outcome.stdout+outcome.stderr)[-64000:]
                ok=outcome.exit_code==0 and not outcome.failure and "Ran 0 tests" not in output and "no tests ran" not in output.lower()
                code=None if ok else outcome.failure or "check_failed"
                item={"name":check.name,"argv":check.argv,"ok":ok,"exit_code":outcome.exit_code,"output":output,"elapsed_seconds":round(time.monotonic()-started,2),"error":code,"task_id":task_id}
            except OSError as exc:
                item={"name":check.name,"argv":check.argv,"ok":False,"exit_code":None,"output":str(exc),"elapsed_seconds":0,"error":"check_unavailable","task_id":task_id}
            manifests={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ("requirements.txt","pyproject.toml","package-lock.json","npm-shrinkwrap.json","package.json") if (root/name).is_file() and not (root/name).is_symlink()}
            item.update(schema_version="1.1",cwd=check.cwd,phase=phase,environment={"private":True,"python_venv":project_python is not None,"manifest_sha256":manifests,"sandbox":execution_capability()["backend"]})
            item=CheckEvidence.model_validate(item).model_dump()
            evidence.append(item);self.store.event(run_id,"check",item,task_id)
            if item["error"]=="process_termination_failed": raise RunProblem("A check process survived termination; its workspace cannot be reused yet")
            if item["error"]=="cancelled": raise asyncio.CancelledError()
        return evidence

    async def _baseline(self,run_id,spec,manager):
        result=self.store.get(run_id)
        if result["artifacts"].get("baseline_complete"): return
        checks=[CheckSpec.model_validate(c) for c in result["artifacts"].get("required_checks", [])] or spec.checks
        target=await self._workspace_call(manager.create_worker,"baseline")
        if not checks:
            assessment=await asyncio.to_thread(assess_project,target,spec.package_roots)
            if assessment.status!="ready": raise ValueError("Configure meaningful checks before resuming this legacy run")
            checks=assessment.proposed_checks
            spec.checks=checks
            result["spec"]["checks"]=[c.model_dump() for c in checks]
            result["artifacts"]["required_checks"]=result["spec"]["checks"]
            self.store.save(result)
        before=manager.fingerprint(target)
        evidence=await self._checks(run_id,target,checks,"baseline",phase="baseline")
        if before!=manager.fingerprint(target): raise ValueError("Baseline checks modified source; configure non-mutating verification")
        result=self.store.get(run_id)
        result["artifacts"].update(baseline_checks=evidence,baseline_complete=True,baseline_snapshot_sha256=before)
        self.store.save(result)
        self.store.event(run_id,"baseline",{"checks":len(evidence),"passed":sum(c["ok"] for c in evidence),"snapshot_sha256":before})

    async def _verify(self,run_id,spec,manager,checks):
        result=self.store.get(run_id)
        required=[CheckSpec.model_validate(c) for c in result["artifacts"].get("required_checks", [])]
        keys={(tuple(c.argv),c.cwd,c.timeout) for c in checks}
        if any((tuple(c.argv),c.cwd,c.timeout) not in keys for c in required):
            raise ValueError("Every configured check remains required; a coordinator cannot remove or weaken a check")
        result["artifacts"].pop("validated_fingerprint",None)
        self.store.save(result)
        before=manager.diff()
        source_before=manager.fingerprint(manager.integration_path)
        evidence=await self._checks(run_id,manager.integration_path,checks)
        result=self.store.get(run_id)
        result["checks"]=evidence
        result["diff"]=manager.diff()
        if result["diff"]!=before or manager.fingerprint(manager.integration_path)!=source_before:
            result["artifacts"].pop("validated_fingerprint",None)
            self.store.save(result)
            raise ValueError("Check commands modified source; review the resulting changes before integration")
        if not all(c["ok"] for c in evidence):
            result["artifacts"].pop("validated_fingerprint",None)
            self.store.save(result)
            raise ValueError("Combined checks failed; repair and validate again")
        contributors={t["provider"] for t in result["tasks"] if t["status"]=="completed" and (spec.mode!="compare" or t["id"]==result["artifacts"].get("selected_task"))}
        candidates=[p for p in spec.team if p.role=="reviewer"]+[spec.coordinator,*spec.team]
        reviewer=next((p for p in candidates if p.provider not in contributors),None)
        if reviewer is None: raise ValueError("Combined verification needs a provider that did not implement this candidate")
        review=await self._assess_patch(run_id,reviewer,manager.integration_path,spec.prompt,self._integration_requirements(result,spec),"integration",
            evidence=evidence,patch=before,patch_budget=60000)
        if not review["ok"]: raise ValueError("Combined integration review failed")
        result=self.store.get(run_id)
        result["checks"]=evidence
        result["artifacts"]["validated_fingerprint"]=before
        result["spec"]["checks"]=[c.model_dump() for c in checks]
        self.store.save(result)

    @staticmethod
    def _integration_requirements(result,spec):
        """The combined review's contract: every completed task's acceptance criteria and owned files.
        These come from the coordinator's plan, never from an implementer, so evaluator isolation holds."""
        if spec.mode=="compare":
            tasks=[t for t in result["tasks"] if t["id"]==result["artifacts"].get("selected_task")]
        else:
            tasks=[t for t in result["tasks"] if t.get("status") in TASK_DONE and not t.get("variant_of")]
        acceptance=[]
        for task in tasks:
            for item in task.get("acceptance") or []:
                item=str(item)[:300]
                if item not in acceptance: acceptance.append(item)
        files=sorted({str(name) for task in tasks for name in (task.get("files") or [])})[:100]
        return {"title":"Combined integration of the completed tasks","acceptance":acceptance[:60],"files":files}

    async def _integrate(self,run_id,spec,manager):
        await self.checkpoint(run_id)
        result=self.store.get(run_id)
        if result["artifacts"].get("integration_applied"): raise ValueError("Changes already integrated")
        if "validated_fingerprint" not in result["artifacts"] or result["artifacts"]["validated_fingerprint"]!=manager.diff():
            raise ValueError("Current combined changes have not passed verification")
        destination=manager.check_destination()
        if not destination["ok"]: raise RunProblem("Destination conflict: " + destination.get("error","Destination changed"))
        if destination.get("revalidate"):
            refreshed=manager.refresh_candidate()
            if not refreshed["ok"]: raise RunProblem("Destination conflict: " + refreshed.get("error","Could not refresh candidate"))
            checks=[CheckSpec.model_validate(c) for c in result["spec"]["checks"]]
            await self._verify(run_id,spec,manager,checks)
        self._status(run_id,"integrating")
        diff=manager.diff()
        source_fingerprint=manager.fingerprint(manager.workspace)
        result=self.store.get(run_id)
        result["artifacts"]["source_snapshot_sha256"]=source_fingerprint
        self.store.save(result)
        if spec.integrate:
            applied=manager.apply()
            if not applied["ok"]: raise RunProblem("Destination conflict: " + applied.get("error","Integration failed"))
            result=self.store.get(run_id)
            result["changed_files"]=applied.get("changed_files",[])
            result["artifacts"]["integration_applied"]=True
            result["artifacts"]["preservation"]=applied.get("preservation",{})
        else:
            result=self.store.get(run_id)
            result["artifacts"]["verified_only"]=True
            result["changed_files"]=destination.get("changed_files",[])
        result["diff"]=diff
        patch=Path(result["artifacts"]["directory"])/"verified.patch"
        patch.write_text(diff)
        result["artifacts"]["patch"]=str(patch)
        from .receipt import save_receipt
        save_receipt(result)
        self.store.save(result)
        self.store.event(run_id,"integrated",{"applied":spec.integrate,"changed_files":result["changed_files"]})

def _handoff(outcome):
    """What a later repair may see of an attempt: its result and the tail of its own answer, nothing else."""
    return {key: outcome.get(key) for key in ("ok", "error", "exit_code", "elapsed_seconds", "effective_settings", "session_id") if key in outcome} | \
        {"answer": str(outcome.get("answer") or "")[-4000:]}

def _owned(name,pattern):
    return name==pattern.rstrip("/") or name.startswith(pattern.rstrip("/")+"/") or fnmatch.fnmatchcase(name,pattern)

def _overlap(left,right):
    return any(_owned(a,b) or _owned(b,a) for a in left for b in right)

def _project_check(argv,workspace):
    command=Path(argv[0]).name
    args=argv[1:]
    if command.startswith("python"):
        args=[a for a in args if a in {"-B","-I"} or not a.startswith("-") or a=="-m"]
        if "-c" in argv or not args: return False
        if "-m" in args:
            index=args.index("-m")
            return index+1<len(args) and args[index+1] in {"unittest","pytest","compileall"}
        script=next((a for a in args if not a.startswith("-")),"")
        path=(workspace/script).resolve()
        return path.is_relative_to(workspace.resolve()) and path.is_file() and ("test" in path.name or "check" in path.name)
    if command in {"npm","pnpm","yarn"}:
        script=args[1] if len(args)>1 and args[0]=="run" else args[0] if args else ""
        return script.split(":")[0] in {"test","check","lint","typecheck","build","verify"} and not any(a in {"exec","publish","deploy"} for a in args)
    if command=="cargo": return bool(args and args[0] in {"test","check","clippy","build"})
    if command=="go": return bool(args and args[0] in {"test","vet","build"})
    if command=="make": return bool(args and args[0] in {"test","check","lint","build"})
    return False

def _node_toolchain_reads(argv):
    """Expose selected Node/npm code, never a user toolchain's parent directory."""
    if not argv or Path(argv[0]).name not in {"node", "npm", "npm-cli.js"}:
        return set()
    executable = argv[0] if Path(argv[0]).is_absolute() else shutil.which(argv[0])
    if not executable:
        return set()
    launch = Path(executable).absolute()
    resolved = launch.resolve()
    if not resolved.is_file():
        return set()
    paths = {launch, resolved}
    if Path(argv[0]).name != "node":
        # Native npm installations have a fixed bin/npm-cli.js entry point.
        # Only its verified package contains npm's required bundled modules.
        packages = []
        if resolved.name == "npm-cli.js":
            packages.append(resolved.parent.parent)
        elif resolved.name == "npm" and resolved.parent.name == "bin":
            # mise's native npm launcher is a shell wrapper rather than a
            # symlink. Bind the fixed npm package it launches, not the whole
            # installation (which can contain other tools or user data).
            packages.append(resolved.parent.parent / "lib" / "node_modules" / "npm")
        for package in packages:
            manifest = package / "package.json"
            try:
                if (not manifest.is_symlink() and manifest.is_file()
                        and manifest.stat().st_size <= 1024 * 1024
                        and json.loads(manifest.read_text()).get("name") == "npm"
                        and (package / "bin" / "npm-cli.js").is_file()):
                    paths.add(package)
            except (OSError, ValueError, AttributeError):
                pass
        node = shutil.which("node")
        if node:
            node_launch = Path(node).absolute()
            if node_launch.resolve().is_file():
                paths.update({node_launch, node_launch.resolve()})
    return paths

def _sandbox_check(argv,workspace,*,writable=None,readable=None,network=False):
    writable=[workspace.resolve(),*(Path(p).resolve() for p in (writable or []))]
    toolchain = _node_toolchain_reads(argv)
    if sys.platform=="darwin" and Path("/usr/bin/sandbox-exec").exists():
        readable=[*writable,Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve(),*(Path(p).resolve() for p in (readable or [])),*sorted(toolchain)]
        userdata=["/Users","/Volumes","/private/var/folders","/private/tmp","/tmp","/System/Volumes/Data/Users","/System/Volumes/Data/private/var/folders","/System/Volumes/Data/private/tmp"]
        quoted=lambda value: json.dumps(str(value))
        writes=" ".join(f'(subpath {quoted(p)})' for p in writable)
        protected="(require-any "+" ".join(f'(subpath {quoted(p)})' for p in userdata)+")"
        permitted="(require-any "+" ".join(f'({"literal" if p.is_file() else "subpath"} {quoted(p)})' for p in readable)+")"
        profile=f'(version 1) (allow default) (deny file-write*) (allow file-write* {writes} (literal "/dev/null"))'
        profile+='(deny file-read-data (require-all '+protected+' (require-not '+permitted+')))'
        from .api_agent import BLOCKED
        import re
        insensitive=lambda name:"".join("["+c.lower()+c.upper()+"]" if c.isascii() and c.isalpha() else re.escape(c) for c in name)
        names="|".join(insensitive(name) for name in sorted(BLOCKED-{"node_modules",".venv","__pycache__"})+[".parallax-owned"])
        secret_pattern="^"+re.escape(str(workspace.resolve()))+r"/([^/]+/)*("+insensitive(".env")+"[^/]*|"+names+")(/.*)?$"
        profile+='(deny file-read* file-write* (regex '+json.dumps(secret_pattern)+'))'
        profile+=("" if network else " (deny network*)")
        resolved=shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
        if resolved:
            executable=Path(resolved)
            # Python detects its venv through the launch path. Resolving its
            # symlink would run pip/tests in the base interpreter instead.
            launch=executable.absolute() if (executable.parent.parent/"pyvenv.cfg").is_file() else executable.resolve()
            argv=[str(launch),*argv[1:]]
        return ["/usr/bin/sandbox-exec","-p",profile,*argv]
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        # Mounts are applied in order. Hide host user data first, then expose
        # only the private workspaces and runtime paths the command requires.
        command=["bwrap","--die-with-parent","--unshare-pid",*(["--unshare-net"] if not network else []),"--ro-bind","/","/","--proc","/proc","--dev","/dev"]
        protected={Path(p) for p in ("/home","/root","/tmp","/var/tmp","/run/user")}
        home=Path.home().resolve()
        if home != Path("/"): protected.add(home)
        for path in sorted(protected,key=lambda p:(len(p.parts),str(p))):
            if path.is_dir(): command.extend(["--tmpfs",str(path)])
        # Keep exact launcher aliases: masking a home hides ~/.local/bin/node,
        # which npm's /usr/bin/env shebang still locates through PATH. A file
        # bind restores that alias without exposing its directory or siblings.
        allowed={Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve(),*(Path(p).resolve() for p in (readable or [])),*toolchain}
        for path in sorted(allowed,key=lambda p:(len(p.parts),str(p))):
            if path.exists(): command.extend(["--ro-bind",str(path),str(path)])
        for path in sorted(set(writable),key=lambda p:(len(p.parts),str(p))):
            command.extend(["--bind",str(path),str(path)])
        from .api_agent import BLOCKED
        blocked={name.lower() for name in BLOCKED-{"node_modules",".venv","__pycache__"}} | {".parallax-owned"}
        for directory,dirs,files in os.walk(workspace,followlinks=False):
            for name in sorted(dirs+files):
                path=Path(directory)/name
                if name.lower() in blocked or name.lower().startswith(".env"):
                    command.extend(["--tmpfs",str(path)] if path.is_dir() else ["--ro-bind","/dev/null",str(path)])
            dirs[:]=[name for name in dirs if name.lower() not in blocked and name not in {"node_modules",".venv","__pycache__"} and not (Path(directory)/name).is_symlink()]
        if toolchain:
            executable=argv[0] if Path(argv[0]).is_absolute() else shutil.which(argv[0])
            if executable: argv=[str(Path(executable).resolve()),*argv[1:]]
        return [*command,"--chdir",str(workspace),"--",*argv]
    raise ValueError("No enforceable command sandbox is available; install bubblewrap with user namespaces before Build or Compare")

def _discover_checks(workspace):
    package=workspace/"package.json"
    if package.exists():
        try:
            scripts=json.loads(package.read_text()).get("scripts",{})
            keys=[key for key in ("test:ci","test","typecheck","lint","build") if key in scripts]
            return [CheckSpec(name=key,argv=["npm","run",key],timeout=180) for key in keys]
        except (OSError,ValueError): pass
    if (workspace/"tests").is_dir() and any((workspace/"tests").glob("test*.py")):
        return [CheckSpec(name="Python tests",argv=[sys.executable,"-m","unittest","discover","-s","tests","-v"])]
    return []

class _timeout:
    """Python 3.10 equivalent of asyncio.timeout."""
    def __init__(self,seconds): self.seconds=seconds
    async def __aenter__(self):
        self.task=asyncio.current_task();self.expired=False
        def expire(): self.expired=True;self.task.cancel()
        self.handle=asyncio.get_running_loop().call_later(self.seconds,expire)
    async def __aexit__(self,kind,exc,tb):
        self.handle.cancel()
        if self.expired and kind is asyncio.CancelledError: raise asyncio.TimeoutError()
