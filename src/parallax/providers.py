"""Bounded, subscription-authenticated adapters for the four native coding CLIs.

Discovery never sends a model prompt. Runs use argv arrays, bounded pipes and
process groups. Provider customizations are isolated inside engine-owned copies.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import uuid
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .models import Participant

PROVIDERS = ("codex", "claude", "grok", "antigravity")
LABELS = {"codex": "Codex", "claude": "Claude Code", "grok": "Grok Build", "antigravity": "Antigravity"}
BINARIES = {"codex": "codex", "claude": "claude", "grok": "grok", "antigravity": "agy"}
MAX_OUTPUT = 8 * 1024 * 1024
MAX_STDERR = 256 * 1024
MAX_EVENTS = 20000
MAX_PROMPT = 200000
AGY_READ_TOOLS = ("view_file", "list_dir", "find_by_name", "grep_search", "finish")
AGY_EDIT_TOOLS = AGY_READ_TOOLS + ("write_to_file", "replace_file_content", "multi_replace_file_content")
Callback = Callable[[dict], Awaitable[None] | None]


def _safe_error(value: Any) -> str:
    value = str(value)
    value = re.sub(r"(?i)(bearer\s+|(?:api[_ -]?key|token|secret)\s*[:=]\s*)[^\s,\"']+", r"\1[redacted]", value)
    return value[:2000]


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _codex_schema(schema: dict) -> dict:
    """OpenAI strict output schemas require every object property explicitly."""
    normalized = json.loads(json.dumps(schema))
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                if node.get("additionalProperties") not in (None, False):
                    raise ValueError("Codex structured output cannot enforce an open object schema")
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(normalized)
    return normalized


def _public_event(event: dict) -> dict | None:
    """Keep operational events while omitting provider private thinking blocks."""
    if event.get("type") in ("thought", "thinking") or str(event.get("type", "")).startswith("parallax.") or isinstance(event.get("item"), dict) and event["item"].get("type") in ("reasoning", "thinking"):
        return None
    event = dict(event)
    event.pop("thought", None)
    event.pop("thinking", None)
    event.pop("signature", None)
    if isinstance(event.get("message"), dict):
        event["message"] = dict(event["message"])
        content = event["message"].get("content")
        if isinstance(content, list):
            event["message"]["content"] = [b for b in content if not isinstance(b, dict) or b.get("type") not in ("thinking", "redacted_thinking")]
    return event


@dataclass
class Captured:
    exit_code: int | None
    stdout: str
    stderr: str
    events: list[dict]
    failure: str | None = None


async def process_identity(pid: int) -> dict | None:
    """A restart-safe process identity without exposing its command arguments."""
    executable = shutil.which("ps")
    if not executable or pid <= 0:
        return None
    process = None
    try:
        process = await asyncio.create_subprocess_exec(executable, "-p", str(pid), "-o", "lstart=", "-o", "command=", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=2)
        fields = stdout.decode("utf-8", "replace").strip().split(None, 5)
        if process.returncode != 0 or len(fields) != 6:
            return None
        return {"started_at": " ".join(fields[:5]), "command_sha256": hashlib.sha256(fields[5].encode()).hexdigest()}
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        return
    for sig, seconds in ((signal.SIGINT, 1.5), (signal.SIGTERM, 1.5), (signal.SIGKILL, 1)):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            else:
                process.kill() if sig == signal.SIGKILL else process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), seconds)
            if os.name == "posix":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            return
        except asyncio.TimeoutError:
            pass


async def _capture(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float,
                   stdin: str = "", cancel_event: asyncio.Event | None = None,
                   on_event: Callback | None = None, guard: Callable[[dict], None] | None = None,
                   max_output: int = MAX_OUTPUT) -> Captured:
    """Drain both pipes continuously; cancellation cannot strand a child process."""
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name == "posix"), limit=MAX_OUTPUT,
    )
    output, errors, events = bytearray(), bytearray(), []
    failures: list[str] = []
    failure_signal = asyncio.Event()

    def fail(code: str) -> None:
        if not failures:
            failures.append(code)
        failure_signal.set()

    async def publish(event: dict) -> None:
        if on_event:
            try:
                returned = on_event(event)
                if inspect.isawaitable(returned):
                    await returned
            except Exception as exc:
                fail("event_callback:" + _safe_error(exc))

    async def emit(line: bytes) -> None:
        event = _json(line.decode("utf-8", "replace"))
        if not isinstance(event, dict):
            return
        if guard:
            try:
                guard(event)
            except ValueError as exc:
                fail("unsafe_configuration:" + str(exc))
                return
        if len(events) >= MAX_EVENTS:
            fail("output_limit")
            return
        events.append(event)
        public = _public_event(event)
        if public is not None:
            await publish(public)

    async def drain_stdout() -> None:
        pending = bytearray()
        while chunk := await process.stdout.read(65536):
            if len(output) + len(chunk) > max_output:
                fail("output_limit")
            else:
                output.extend(chunk)
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                await emit(line)
            if len(pending) > max_output:
                fail("output_limit")
                pending.clear()
        if pending:
            await emit(pending)

    async def drain_stderr() -> None:
        while chunk := await process.stderr.read(65536):
            remaining = MAX_STDERR - len(errors)
            if remaining > 0:
                errors.extend(chunk[:remaining])
            if len(chunk) > remaining:
                fail("output_limit")

    async def write_prompt() -> None:
        try:
            process.stdin.write(stdin.encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    readers = [asyncio.create_task(drain_stdout()), asyncio.create_task(drain_stderr()), asyncio.create_task(write_prompt())]
    completion = asyncio.create_task(process.wait())
    watches = [asyncio.create_task(failure_signal.wait())]
    if cancel_event is not None:
        watches.append(asyncio.create_task(cancel_event.wait()))
    stopped = False
    externally_cancelled = False

    async def terminate() -> None:
        nonlocal stopped
        if not stopped:
            stopped = True
            await _stop(process)
        if process.returncode is None:
            # Some macOS sandbox failures leave a child in an uninterruptible
            # kernel wait. Preserve its durable started identity for recovery.
            failures[:] = ["process_termination_failed"]

    async def close_readers() -> None:
        for task in readers:
            if not task.done():
                task.cancel()
        process.stdin.close()
        # StreamReader has no public close operation; its pipe transport must
        # close even when the unreaped subprocess keeps both descriptors open.
        for stream in (process.stdout, process.stderr):
            transport = getattr(stream, "_transport", None)
            if transport is not None:
                transport.close()
        done, _ = await asyncio.wait(readers, timeout=0.5)
        for task in done:
            if not task.cancelled():
                with contextlib.suppress(Exception):
                    task.result()

    try:
        if on_event:
            await publish({"type": "parallax.process_started", "pid": process.pid, "process_group": process.pid if os.name == "posix" else None, "cwd": str(cwd), "identity": await process_identity(process.pid)})
        done, _ = await asyncio.wait([completion, *watches], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            fail("timeout")
        elif cancel_event is not None and cancel_event.is_set():
            fail("cancelled")
        if failures:
            await terminate()
        if process.returncode is not None:
            _, pending = await asyncio.wait(readers, timeout=3)
            if pending:
                fail("unclosed_output")
                await terminate()
            else:
                await asyncio.gather(*readers)
    except asyncio.CancelledError:
        externally_cancelled = True
        await terminate()
    finally:
        for watch in [*watches, completion]:
            watch.cancel()
        await asyncio.wait([*watches, completion], timeout=0.5)
        # Finish the entire owned group, including helpers that closed stdout
        # but remained alive after their native CLI exited.
        await terminate()
        await close_readers()
        if process.returncode is not None:
            await publish({"type": "parallax.process_finished", "pid": process.pid, "exit_code": process.returncode})
        else:
            await publish({"type": "parallax.process_termination_failed", "pid": process.pid, "cwd": str(cwd), "message": "Owned subprocess did not exit after bounded termination; identity retained for recovery."})
    if externally_cancelled and process.returncode is not None:
        raise asyncio.CancelledError()
    return Captured(process.returncode, output.decode("utf-8", "replace"), errors.decode("utf-8", "replace"), events, failures[0] if failures else None)


def _model_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # Grok caches a map of model IDs to {info, api_key, ...}; expose
        # only the public info row, never its credential-bearing wrapper.
        if isinstance(payload.get("info"), dict):
            return [payload["info"]]
        if any(isinstance(payload.get(key), str) for key in ("slug", "id", "model")):
            return [payload]
        for key in ("models", "data", "command"):
            if key in payload:
                rows = _model_rows(payload[key])
                if rows:
                    return rows
        rows = []
        for value in payload.values():
            if isinstance(value, dict):
                rows.extend(_model_rows(value))
        return rows
    return []


def _catalog_models(rows: list[dict], provider: str) -> list[dict]:
    models = []
    for row in rows:
        model_id = row.get("slug") or row.get("id") or row.get("model")
        if not isinstance(model_id, str) or row.get("visibility") == "hide" or row.get("hidden") is True:
            continue
        options = row.get("supported_reasoning_levels") or row.get("reasoning_efforts") or row.get("supportedReasoningEfforts") or []
        efforts = [o.get("effort") or o.get("id") or o.get("reasoningEffort") for o in options if isinstance(o, dict)]
        default = row.get("default_reasoning_level") or row.get("defaultReasoningEffort")
        if not default:
            default = next((o.get("id") for o in options if isinstance(o, dict) and o.get("default")), None)
        label = row.get("display_name") or row.get("displayName") or row.get("name") or row.get("label") or model_id
        if provider == "antigravity":
            # Native Gemini effort variants are model IDs, not interchangeable
            # CLI effort levels. Passing a conflicting --effort is a native error.
            suffix = re.search(r"-(low|medium|high|xhigh|max)$", model_id)
            if suffix:
                efforts = [suffix.group(1)]
                default = suffix.group(1)
            elif "claude" in model_id:
                efforts, default = ["low", "medium", "high", "xhigh", "max"], "high"
        models.append({"id": model_id, "name": model_id, "label": label,
                       "is_default": row.get("isDefault") is True or row.get("is_default") is True,
                       "efforts": [e for e in efforts if isinstance(e, str)],
                       "default_effort": default, "context_window": row.get("context_window"),
                       "effort_selection": "model_variant" if provider == "antigravity" and suffix else "flag"})
    return models


class ProviderRegistry:
    def __init__(self, binaries: dict[str, str] | None = None, *, home: Path | None = None,
                 cache_seconds: int = 60, max_output: int = MAX_OUTPUT) -> None:
        self.binaries = {**BINARIES, **(binaries or {})}
        self.home = Path(home) if home is not None else Path.home()
        self.codex_home = Path(os.environ.get("CODEX_HOME") or self.home / ".codex").expanduser()
        self.cache_seconds = cache_seconds
        self.max_output = max_output
        self._catalogs: dict[str, dict] = {}
        self._help: dict[str, str] = {}
        self._times: dict[str, float] = {}
        self._locks = {name: asyncio.Lock() for name in PROVIDERS}

    async def discover(self, *, refresh: bool = False) -> list[dict]:
        return list(await asyncio.gather(*(self.catalog(provider, refresh=refresh) for provider in PROVIDERS)))

    async def _metadata(self, executable: str, args: list[str], *, timeout: int = 20) -> Captured:
        env = os.environ.copy()
        env.pop("PARALLAX_ACCESS_TOKEN", None)
        env["GROK_DISABLE_AUTOUPDATER"] = "1"
        return await _capture([executable, *args], cwd=self.home, env=env, timeout=timeout,
                              max_output=self.max_output)

    def _cache_file(self, provider: str) -> dict:
        folder = self.codex_home if provider == "codex" else self.home / ".grok"
        path = folder / "models_cache.json"
        try:
            if path.stat().st_size > self.max_output:
                return {}
            payload = _json(path.read_text())
            return payload if isinstance(payload, dict) else {}
        except OSError:
            return {}

    def _codex_default(self, info: dict) -> None:
        """Resolve the CLI selection without modifying or exposing user config."""
        path = self.codex_home / "config.toml"
        config = {}
        info["default_model_source"] = "native catalog default"
        info["default_model_error"] = None
        try:
            if path.exists():
                if path.stat().st_size > self.max_output:
                    raise ValueError("Configuration exceeds the discovery size limit")
                config = tomllib.loads(path.read_text())
            model = config.get("model")
            profile = config.get("profile")
            source = "Codex configuration"
            if profile is not None:
                profiles = config.get("profiles", {})
                if not isinstance(profile, str) or not profile.strip() or not isinstance(profiles, dict) or not isinstance(profiles.get(profile), dict):
                    raise ValueError("Configured Codex profile is unavailable")
                settings = profiles[profile]
                if "model" in settings:
                    model = settings["model"]
                    source = "Codex profile " + profile
            if model is not None and (not isinstance(model, str) or not model.strip()):
                raise ValueError("Configured Codex model must be a nonempty string")
            if model:
                info["default_model"] = model
                info["default_model_source"] = source
                if not any(m["id"] == model for m in info["models"]):
                    info["default_model_error"] = "Configured Codex default is absent from the discovered catalog. Select an available model explicitly or update your CLI configuration."
            else:
                info["default_model"] = next((m["id"] for m in info["models"] if m.get("is_default")), None)
        except (OSError, ValueError):
            info["default_model"] = None
            info["default_model_source"] = "Codex configuration"
            info["default_model_error"] = "Cannot resolve the configured Codex default. Select a model explicitly or repair your CLI configuration."

    async def catalog(self, provider: str, *, refresh: bool = False) -> dict:
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        async with self._locks[provider]:
            if not refresh and provider in self._catalogs and time.monotonic() - self._times[provider] < self.cache_seconds:
                return self._catalogs[provider]
            executable = shutil.which(self.binaries[provider])
            info = {"provider": provider, "id": provider, "name": provider, "label": LABELS[provider],
                    "executable": executable, "version": None, "authenticated": None,
                    "status": "missing", "error": None, "capabilities": {}, "models": [],
                    "default_model": None, "catalog_source": "unavailable"}
            if not executable:
                info["error"] = f"Install {LABELS[provider]} and sign in using its native CLI."
                return self._remember(provider, info)
            try:
                version, help_result = await asyncio.gather(self._metadata(executable, ["--version"]), self._metadata(executable, ["--help"]))
                info["version"] = version.stdout.strip().splitlines()[0] if version.stdout.strip() else "unknown"
                self._help[provider] = help_result.stdout + help_result.stderr
                if help_result.exit_code != 0 or help_result.failure:
                    raise ValueError("Could not inspect the installed CLI capabilities")
                if provider == "codex":
                    auth, catalog = await asyncio.gather(self._metadata(executable, ["login", "status"]), self._metadata(executable, ["debug", "models"]))
                    info["authenticated"] = auth.exit_code == 0 and "logged in" in (auth.stdout + auth.stderr).lower()
                    rows = _model_rows(_json(catalog.stdout))
                    info["catalog_source"] = "native CLI model discovery"
                    if not rows:
                        cache = self._cache_file(provider)
                        rows = _model_rows(cache)
                        info["catalog_source"] = "cached native catalog; client=" + str(cache.get("client_version", "unknown")) + "; fetched=" + str(cache.get("fetched_at", "unknown"))
                    if not rows:
                        bundled = await self._metadata(executable, ["debug", "models", "--bundled"])
                        rows = _model_rows(_json(bundled.stdout))
                        info["catalog_source"] = "bundled CLI catalog; account access unverified"
                    info["models"] = _catalog_models(rows, provider)
                    self._codex_default(info)
                elif provider == "claude":
                    auth = await self._metadata(executable, ["auth", "status"])
                    payload = _json(auth.stdout)
                    info["authenticated"] = auth.exit_code == 0 and isinstance(payload, dict) and bool(payload.get("loggedIn"))
                    # Claude exposes aliases in CLI help, rather than an
                    # account-scoped no-inference models endpoint.
                    aliases = [name for name in ("sonnet", "opus", "fable") if re.search(r"\b" + name + r"\b", self._help[provider])]
                    info["models"] = [{"id": a, "name": a, "label": a.title(), "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high", "effort_selection": "flag"} for a in aliases]
                    info["default_model"] = "sonnet" if "sonnet" in aliases else (aliases[0] if aliases else None)
                    info["catalog_source"] = "installed CLI aliases; account/model access checked by native invocation"
                elif provider == "grok":
                    catalog = await self._metadata(executable, ["models"])
                    combined = catalog.stdout + catalog.stderr
                    # Grok lists public models even when the account is signed
                    # out. A catalog is not evidence of authentication.
                    info["authenticated"] = (catalog.exit_code == 0
                        and "logged in" in combined.lower()
                        and not re.search(r"(?i)(not authenticated|not logged in|authentication required)", combined))
                    cache = self._cache_file(provider)
                    available = re.findall(r"^\s*[-*]\s+([a-zA-Z0-9_.:/-]+)", catalog.stdout, re.M)
                    rows = _model_rows(cache)
                    if available:
                        rows = [r for r in rows if (r.get("id") or r.get("model")) in available]
                        found = {r.get("id") or r.get("model") for r in rows}
                        rows += [{"id": m, "name": m} for m in available if m not in found]
                    info["models"] = _catalog_models(rows, provider)
                    default = re.search(r"Default model:\s*(\S+)", catalog.stdout)
                    info["default_model"] = default.group(1) if default else None
                    info["catalog_source"] = "native CLI IDs + cached native effort menus; fetched=" + str(cache.get("fetched_at", "unknown"))
                else:
                    catalog = await self._metadata(executable, ["--output-format", "json", "models"])
                    rows = _model_rows(_json(catalog.stdout))
                    info["models"] = _catalog_models(rows, provider)
                    info["authenticated"] = catalog.exit_code == 0 and bool(rows)
                    info["catalog_source"] = "native account model catalog; effort variants derived from model IDs"
                    info["default_model"] = next((m["id"] for m in info["models"] if m["id"].endswith("-high") and m["id"].startswith("gemini-")), None)
                if not info["default_model"] and info["models"] and not info.get("default_model_error"):
                    info["default_model"] = info["models"][0]["id"]
                info["capabilities"] = {"headless": True, "streaming": True, "resume": True,
                    "structured_output": True, "effort": True, "consult": True, "edit": True,
                    "coordinate": True, "native_recursion": False,
                    "edit_shell": provider in ("codex", "grok") and os.name == "posix" or provider == "claude" and self._claude_shell_available(),
                    "authentication": "existing native sign-in", "requires_owned_workspace": True}
                info["status"] = "ready" if info["authenticated"] and info["models"] else "sign_in_required" if not info["authenticated"] else "catalog_unavailable"
                if info["status"] != "ready":
                    info["error"] = "Sign in with the native CLI." if not info["authenticated"] else "No selectable models were discovered."
            except (OSError, ValueError, KeyError) as exc:
                info["status"], info["error"] = "unavailable", _safe_error(exc)
            return self._remember(provider, info)

    def _remember(self, provider: str, info: dict) -> dict:
        self._catalogs[provider], self._times[provider] = info, time.monotonic()
        return info

    def validate(self, participant: Participant) -> dict:
        provider = participant.provider
        catalog = self._catalogs.get(provider)
        if not catalog:
            raise ValueError(f"Discover {provider} before validating settings")
        if catalog["status"] != "ready":
            raise ValueError(f"{LABELS[provider]} is unavailable: {catalog.get('error')}")
        if not participant.model and catalog.get("default_model_error"):
            raise ValueError(catalog["default_model_error"])
        model = participant.model or catalog["default_model"]
        choice = next((m for m in catalog["models"] if m["id"] == model), None)
        if not choice:
            raise ValueError(f"Model {model!r} is not in the discovered {provider} catalog")
        effort = participant.effort
        if effort is not None and effort not in choice.get("efforts", []):
            raise ValueError(f"Effort {effort!r} is unsupported for {model}; choose {', '.join(choice.get('efforts', [])) or 'provider default'}")
        return {"provider": provider, "model": model, "effort": effort or choice.get("default_effort"),
                "effort_source": "requested" if effort else "provider default",
                "effort_selection": choice.get("effort_selection", "flag"),
                "catalog_source": catalog["catalog_source"]}

    async def run(self, provider: str, *, workspace: Path, prompt: str, model: str | None,
                  effort: str | None, mode: str = "consult", session_id: str | None = None,
                  timeout: int = 600, schema: dict | None = None, on_event: Callback | None = None,
                  cancel_event: asyncio.Event | None = None) -> dict:
        started = time.monotonic()
        requested = {"provider": provider, "model": model, "effort": effort, "mode": mode}
        result = {"ok": False, "answer": "", "structured_output": None, "session_id": session_id,
                  "provider": provider, "requested_settings": requested, "effective_settings": {},
                  "usage": {}, "error": None, "exit_code": None, "partial_output": ""}
        workspace = Path(workspace).expanduser().resolve()
        try:
            if provider not in PROVIDERS:
                raise ValueError(f"Unknown provider: {provider}")
            if mode not in ("consult", "edit", "coordinate"):
                raise ValueError("Mode must be consult, edit, or coordinate")
            if not workspace.is_dir() or not (workspace / ".parallax-owned").is_file():
                raise ValueError("Provider runs require an engine-owned workspace marked .parallax-owned")
            if not prompt.strip() or len(prompt) > MAX_PROMPT:
                raise ValueError("Prompt must contain 1 to 200000 characters")
            if timeout <= 0:
                raise ValueError("Timeout must be positive")
            if session_id:
                uuid.UUID(session_id)
            if cancel_event and cancel_event.is_set():
                return {**result, "error": {"code": "cancelled", "message": "Run was cancelled before launch"}}
            catalog = await self.catalog(provider)
            effective = self.validate(Participant(provider=provider, model=model, effort=effort))
            result["effective_settings"] = effective
            with tempfile.TemporaryDirectory(prefix="parallax-provider-") as scratch:
                scratch_path = Path(scratch)
                with self._customizations(provider, workspace, scratch_path, mode) as customization:
                    argv, stdin, env, allowed = self._command(provider, catalog["executable"], workspace, prompt, effective, mode, session_id, timeout, schema, scratch_path, customization)
                    # Sandboxing the entire native client breaks its auth or
                    # its own sandbox initialization. Contain shell subprocesses
                    # with native fail-closed sandboxing instead.
                    effective["shell"] = mode == "edit" and (provider in ("codex", "grok") or provider == "claude" and self._claude_shell_available())
                    effective["sandbox"] = "native " + ("workspace-write" if mode == "edit" else "read-only") if provider in ("codex", "grok") else "native restricted file tools" + (" + strict shell sandbox" if effective["shell"] else "")
                    captured = await _capture(argv, cwd=workspace, env=env, timeout=timeout, stdin=stdin,
                                              cancel_event=cancel_event, on_event=on_event,
                                              guard=lambda event: self._guard(provider, event, allowed, mode), max_output=self.max_output)
                    parsed = self._parse(provider, captured, schema)
                    if provider == "antigravity":
                        audit = customization["gate_audit"]
                        gates = [_json(line) for line in audit.read_text().splitlines()] if audit.exists() else []
                        gates = [row for row in gates if isinstance(row, dict)]
                        result["boundary_evidence"] = {"pre_tool_gate": gates}
                        attempted = any(event.get("event") == "step_update" and event.get("step_update", {}).get("tool_name") for event in captured.events)
                        if attempted and not gates and not captured.failure:
                            parsed.update(ok=False, error={"code": "unsafe_configuration", "message": "Antigravity invoked tools without the required scope gate audit"})
                        elif any(row.get("decision") != "allow" for row in gates):
                            parsed.update(ok=False, error={"code": "permission_denied", "message": "Parallax scope gate denied an Antigravity tool"})
                    if parsed.get("session_id") is None:
                        parsed["session_id"] = session_id
                    result.update(parsed)
                    result["effective_settings"] = effective
                    result["exit_code"] = captured.exit_code
                    failure = captured.failure
                    if failure:
                        code, _, detail = failure.partition(":")
                        result["ok"] = False
                        result["error"] = {"code": code, "message": detail or {"timeout": f"Provider exceeded {timeout} seconds", "cancelled": "Provider run was cancelled", "output_limit": "Provider exceeded the bounded output limit", "process_termination_failed": "Owned subprocess did not exit after bounded termination; run requires process reconciliation before reuse."}.get(code, code)}
                    if captured.stderr:
                        result["diagnostics"] = _safe_error(captured.stderr)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            result["ok"] = False
            result["error"] = {"code": "invalid_settings" if isinstance(exc, ValueError) else "provider_error", "message": _safe_error(exc)}
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return result

    @contextlib.contextmanager
    def _customizations(self, provider: str, workspace: Path, scratch: Path, mode: str):
        """Mask copied customization files, never the user's original settings."""
        names = {"codex": [".codex/config.toml"], "claude": [],
                 "grok": [".grok/config.toml", ".grok/sandbox.toml"],
                 "antigravity": [".agents/hooks.json"]}[provider]
        moved, created, directories = [], [], []
        def save(path: Path) -> None:
            if path.is_symlink():
                raise ValueError(f"Customization path must not be a symlink: {path}")
            if path.exists():
                destination = scratch / ("saved-" + str(len(moved)))
                shutil.move(str(path), destination)
                moved.append((path, destination))
        def create(path: Path, content: str) -> None:
            for parent in [path.parent, *path.parent.parents]:
                if parent == workspace:
                    break
                if parent.is_symlink():
                    raise ValueError("Native customization directory must not be a symlink")
            missing = []
            parent = path.parent
            while not parent.exists() and parent != workspace:
                missing.append(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            directories.extend(reversed(missing))
            path.write_text(content)
            created.append(path)
        try:
            for name in names:
                save(workspace / name)
            customization = {}
            if provider == "grok":
                profile = "parallax-edit" if mode == "edit" else "parallax-read"
                create(workspace / ".grok/sandbox.toml", f'[profiles.{profile}]\nextends = "{"workspace" if mode == "edit" else "read-only"}"\n')
                customization["profile"] = profile
            if provider == "antigravity":
                agent = "parallax-" + uuid.uuid4().hex
                tools = AGY_EDIT_TOOLS if mode == "edit" else AGY_READ_TOOLS
                create(workspace / ".agents/agents" / (agent + ".md"),
                       "---\nname: " + agent + "\ndescription: Bounded Parallax participant.\nmainAgent: true\nsubagent: false\nmodel: inherit\ncommandExecutionPolicy: off\nmcpServers: []\nskills: []\nplugins: []\ntools:\n" + "".join("  - " + tool + "\n" for tool in tools) + "---\nComplete only the delegated task. Do not spawn agents, schedule work, use MCP, or alter configuration.\n")
                gate = scratch / "agy_gate.py"
                gate.write_text(_AGY_GATE)
                audit = scratch / "agy_gate_audit.jsonl"
                command = " ".join(_shell_quote(s) for s in (sys.executable, str(gate), str(workspace), mode, str(audit)))
                create(workspace / ".agents/hooks.json", json.dumps({"parallax-gate": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 10}]}]}}))
                customization["agent"] = agent
                customization["gate_audit"] = audit
            yield customization
        finally:
            changed_configuration = False
            for path in reversed(created):
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            for path, source in reversed(moved):
                if path.exists() or path.is_symlink():
                    changed_configuration = True
                    # The provider owns a disposable checkout, but preserve its
                    # original copied settings even when the run misbehaves.
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                shutil.move(str(source), path)
            for directory in reversed(directories):
                with contextlib.suppress(OSError):
                    directory.rmdir()
            if changed_configuration:
                raise RuntimeError("Provider modified isolated native configuration; copied settings restored")

    def _command(self, provider: str, executable: str, workspace: Path, prompt: str,
                 settings: dict, mode: str, session: str | None, timeout: int,
                 schema: dict | None, scratch: Path, customization: dict) -> tuple[list[str], str, dict, set[str]]:
        env = os.environ.copy()
        env.pop("PARALLAX_ACCESS_TOKEN", None)
        env["PARALLAX_OWNED_WORKSPACE"] = str(workspace)
        env["GROK_DISABLE_AUTOUPDATER"] = "1"
        env["GROK_MEMORY"] = "0"
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("XAI_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        instruction = ("You are a bounded Parallax participant. The Parallax runtime owns delegation, validation and integration. Do not spawn other agents, call team tools, create background jobs, change agent configuration, commit, push, or publish. "
                       + ("Inspect files and return the requested response without changing files.\n\n" if mode != "edit" else "Implement only the delegated task in this isolated workspace. Preserve unrelated files. Root runtime will execute final checks.\n\n") + prompt)
        if schema:
            instruction += "\n\nUse the supplied response schema directly. Populate its fields with the requested values; do not nest or quote the entire payload inside one field."
        model, effort = settings["model"], settings["effort"]
        native_help = self._help.get(provider, "")
        def require(*flags: str) -> None:
            absent = [flag for flag in flags if flag not in native_help]
            if absent:
                raise ValueError("Installed CLI cannot enforce this adapter's boundaries; missing " + ", ".join(absent))
        if provider == "codex":
            require("--config", "--sandbox")
            args = [executable, "-a", "never", "exec", "--ignore-user-config", "--json", "--color", "never", "--skip-git-repo-check", "--sandbox", "workspace-write" if mode == "edit" else "read-only", "--cd", str(workspace), "--model", model,
                    "-c", 'features.apps=false', "-c", 'features.plugins=false', "-c", 'features.hooks=false', "-c", 'features.memories=false', "-c", 'features.multi_agent=false', "-c", 'web_search="disabled"']
            if effort:
                args += ["-c", 'model_reasoning_effort=' + json.dumps(effort)]
            if schema:
                path = scratch / "schema.json"
                path.write_text(json.dumps(_codex_schema(schema)))
                args += ["--output-schema", str(path)]
            if session:
                args += ["resume", session]
            args += ["-"]
            return args, instruction, env, set()
        if provider == "claude":
            require("--safe-mode", "--restricted", "--strict-mcp-config", "--permission-prompts", "--tools", "--settings")
            tools = "Read,Glob,Grep,Edit,Write" if mode == "edit" else "Read,Glob,Grep"
            shell = mode == "edit" and self._claude_shell_available()
            if shell:
                tools += ",Bash"
            args = [executable, "--safe-mode", "--restricted", "--no-chrome", "-p", "--output-format", "stream-json", "--verbose", "--tools", tools, "--permission-mode", "acceptEdits" if mode == "edit" else "dontAsk", "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--disallowedTools", "Agent,Task,SendMessage,TeamCreate,TeamDelete,WebFetch,WebSearch", "--model", model]
            if shell:
                settings = {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False, "autoAllowBashIfSandboxed": True, "excludedCommands": [], "enableWeakerNestedSandbox": False, "filesystem": {"disabled": False, "allowWrite": [str(workspace)]}, "network": {"allowedDomains": []}}}
                args += ["--settings", json.dumps(settings), "--allowedTools", "Bash"]
            if effort:
                args += ["--effort", effort]
            if schema:
                args += ["--json-schema", json.dumps(schema)]
            if session:
                args += ["--resume", session]
            # Native structured output is a formatting tool with no file or
            # delegation capabilities. Claude advertises it only with a schema.
            allowed = set(tools.split(",")) | ({"StructuredOutput"} if schema else set())
            return args, instruction, env, allowed
        if provider == "grok":
            require("--tools", "--deny", "--sandbox", "--no-subagents", "--permission-mode")
            tools = "read_file,grep,list_dir,search_replace" if mode == "edit" else "read_file,grep,list_dir"
            if mode == "edit":
                tools += ",run_terminal_cmd"
            prompt_path = scratch / "prompt.txt"
            prompt_path.write_text(instruction)
            args = [executable, "--prompt-file", str(prompt_path), "--output-format", "json" if schema else "streaming-json", "--cwd", str(workspace), "--model", model, "--tools", tools, "--no-subagents", "--no-plan", "--disable-web-search", "--permission-mode", "dontAsk", "--sandbox", customization["profile"], "--max-turns", "40", "--deny", "MCPTool", "--deny", "WebFetch", "--deny", "WebSearch"]
            if mode == "edit":
                args += ["--allow", "Edit", "--allow", "Write", "--allow", "Bash"]
            else:
                args += ["--deny", "Bash", "--deny", "Edit", "--deny", "Write"]
            if effort:
                args += ["--reasoning-effort", effort]
            if schema:
                args += ["--json-schema", json.dumps(schema)]
            if session:
                args += ["--resume", session]
            return args, "", env, set(tools.split(","))
        require("--agent", "--sandbox", "--disable-slash-commands", "--print")
        # v1.3.0 streaming stdin does not honor terminal schema enforcement;
        # a one-shot print call does, and still emits progress NDJSON.
        args = [executable, "--add-dir", str(workspace), "--print", instruction, "--output-format", "stream-json", "--disable-slash-commands", "--sandbox", "--agent", customization["agent"], "--model", model, "--mode", "accept-edits" if mode == "edit" else "plan", "--print-timeout", str(timeout) + "s"]
        if effort and settings.get("effort_selection") != "model_variant":
            args += ["--effort", effort]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        if session:
            args += ["--conversation", session]
        return args, "", env, set(AGY_EDIT_TOOLS if mode == "edit" else AGY_READ_TOOLS)

    @staticmethod
    def _claude_shell_available() -> bool:
        return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file() or sys.platform.startswith("linux") and bool(shutil.which("bwrap") and shutil.which("socat"))

    @staticmethod
    def _guard(provider: str, event: dict, allowed: set[str], mode: str) -> None:
        # AGY init.tools lists its entire built-in registry even with a custom
        # primary agent. Enforce the finite list on actual calls and via the
        # native PreToolUse gate, rather than treating that registry as policy.
        if provider == "antigravity" and event.get("event") == "step_update":
            step = event.get("step_update", {})
            if step.get("subagent_info") or (step.get("tool_name") and step["tool_name"] not in allowed):
                raise ValueError("Antigravity attempted prohibited delegation or tool: " + str(step.get("tool_name", "nested agent")))
        if provider == "claude" and event.get("type") == "system" and event.get("subtype") == "init":
            advertised = set(event.get("tools", []))
            if advertised - allowed:
                raise ValueError("Claude exposed tools outside its finite allowlist: " + ", ".join(sorted(advertised - allowed)))
        if provider == "grok" and event.get("type") == "tool_call":
            # The CLI picker accepts run_terminal_cmd; ACP uses its canonical
            # run_terminal_command name. v1.0.46 may place the name in _meta.
            tool = event.get("toolName") or event.get("_meta", {}).get("x.ai/tool", {}).get("name")
            canonical = allowed | ({"run_terminal_command"} if "run_terminal_cmd" in allowed else set())
            tool = tool or (event.get("title") if event.get("title") in canonical else None)
            if tool not in canonical:
                raise ValueError("Grok attempted a tool outside its finite allowlist: " + str(tool or "unidentified"))
        if provider == "codex" and isinstance(event.get("item"), dict):
            item = event["item"]
            if item.get("type") in ("mcp_tool_call", "collab_tool_call"):
                raise ValueError("Codex attempted MCP or nested-agent delegation")
            if mode != "edit" and item.get("type") == "file_change":
                raise ValueError("Read-only Codex attempted file changes")

    @staticmethod
    def _parse(provider: str, captured: Captured, schema: dict | None) -> dict:
        whole = _json(captured.stdout)
        events = captured.events or ([whole] if isinstance(whole, dict) else [])
        answer, session, usage, structured, error = "", None, {}, None, None
        terminal = None
        for event in events:
            if provider == "codex":
                if event.get("type") == "thread.started":
                    session = event.get("thread_id")
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    answer = item.get("text", "")
                if event.get("type") in ("turn.completed", "turn.failed", "error"):
                    terminal = event
                    usage = event.get("usage", usage)
                    if event.get("type") != "turn.completed":
                        error = event.get("error") or event.get("message") or "Codex turn failed"
            elif provider == "claude":
                session = event.get("session_id") or session
                if event.get("type") == "assistant":
                    content = event.get("message", {}).get("content", [])
                    text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                    if text:
                        answer = text
                if event.get("type") == "result":
                    terminal = event
                    answer = event.get("result") or answer
                    structured = event.get("structured_output")
                    usage = event.get("usage", {})
                    if event.get("is_error") or event.get("subtype") not in (None, "success"):
                        error = event.get("errors") or answer or "Claude run failed"
                    if event.get("permission_denials"):
                        error = "Native permission policy denied requested tools"
            elif provider == "grok":
                session = event.get("sessionId") or session
                if event.get("type") == "text":
                    answer += event.get("data", "")
                if event.get("type") in ("end", "error") or "stopReason" in event and "text" in event:
                    terminal = event
                    answer = event.get("text", answer)
                    structured = event.get("structured_output", event.get("structuredOutput"))
                    usage = event.get("usage", {})
                    if event.get("type") == "error" or event.get("stopReason") not in ("end_turn", "stop", None):
                        error = event.get("message") or "Grok stopped: " + str(event.get("stopReason"))
            else:
                session = event.get("conversation_id") or session
                if event.get("event") == "step_update":
                    step = event.get("step_update", {})
                    if step.get("step_type") == "agent_response":
                        answer += step.get("text_delta", "")
                    tool_error = step.get("tool_info", {}).get("error")
                    if tool_error and "permission" in str(tool_error).lower():
                        error = "Native permission policy denied a requested tool"
                if event.get("event") == "result" or "response" in event and "status" in event:
                    terminal = event.get("result", event)
                    session = terminal.get("conversation_id") or session
                    answer = terminal.get("response") or answer
                    structured = terminal.get("structured_output")
                    usage = terminal.get("usage", {})
                    if terminal.get("status") != "SUCCESS":
                        error = terminal.get("error") or "Antigravity stopped: " + str(terminal.get("status"))
        if provider == "antigravity" and re.search(r"(?i)(soft.denied|permission.{0,80}denied|requires? approval|approval.{0,40}(?:denied|unavailable))", captured.stderr):
            error = "Antigravity soft-denied a requested tool; the task is incomplete"
        if re.search(r"(?i)(unsupported.{0,30}effort|effort.{0,30}(?:ignored|unsupported)|ignoring.{0,30}effort)", captured.stderr):
            error = "Provider could not honor the requested effort"
        if schema and structured is None and answer:
            structured = _json(answer)
            if structured is None:
                error = "Provider did not return valid structured output"
        if provider == "antigravity" and schema and structured is not None:
            # The native finish response includes toolAction/toolSummary;
            # structured_output contains only the requested schema payload.
            answer = json.dumps(structured, ensure_ascii=False)
        elif provider == "antigravity" and not schema and structured == {}:
            structured = None
        if not terminal and not captured.failure:
            error = "Provider returned no valid terminal event"
            if re.search(r"(?i)(not authenticated|not logged in|authentication required|silent auth failed)", captured.stdout + captured.stderr):
                error = "Authentication required; sign in to the provider on this runtime"
        if captured.exit_code != 0 and not captured.failure:
            error = error or captured.stderr.strip() or f"Provider exited {captured.exit_code}"
        return {"ok": error is None and terminal is not None and captured.exit_code == 0,
                "answer": answer, "structured_output": structured, "session_id": session,
                "usage": usage, "partial_output": answer,
                "error": {"code": "permission_denied" if "denied" in str(error).lower() else "cancelled" if "cancelled" in str(error).lower() else "authentication_required" if re.search(r"(?i)(authentication required|not logged in|silent auth failed)", str(error)) else "provider_error", "message": _safe_error(error)} if error else None}


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


_AGY_GATE = '''import json, pathlib, sys
name = ""
try:
    event = json.load(sys.stdin)
    root = pathlib.Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    call = event.get("toolCall", {})
    name, args = call.get("name", ""), call.get("args", {})
    readers = {"view_file", "list_dir", "find_by_name", "grep_search", "finish"}
    writers = {"write_to_file", "replace_file_content", "multi_replace_file_content"}
    allowed = readers | (writers if mode == "edit" else set())
    if name not in allowed:
        raise ValueError("Tool is outside the finite Parallax allowlist")
    paths = [] if name == "finish" else [v for k,v in args.items() if isinstance(v,str) and any(t in k.lower() for t in ("path", "directory", "targetfile"))]
    if not paths and name != "finish":
        raise ValueError("Cannot establish tool filesystem scope")
    for value in paths:
        path = pathlib.Path(value)
        path = (root/path).resolve() if not path.is_absolute() else path.resolve()
        path.relative_to(root)
        if name in writers and any(part in (".agents", ".grok", ".codex", ".claude", ".git", ".parallax-owned") for part in path.relative_to(root).parts):
            raise ValueError("Agent configuration and repository metadata are protected")
    response = {"decision":"allow"}
except Exception as exc:
    response = {"decision":"deny", "reason":str(exc)}
if len(sys.argv) > 3:
    try:
        with open(sys.argv[3], "a") as audit:
            audit.write(json.dumps({"tool":name, "decision":response["decision"]}) + "\\n")
    except Exception:
        response = {"decision":"deny", "reason":"Cannot establish Parallax hook audit"}
print(json.dumps(response))
'''
