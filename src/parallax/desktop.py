"""Foreground, project-bound runtime owned by the desktop application's pipes."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager, redirect_stdout
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import sys
from urllib.parse import parse_qs, urlencode

from . import __version__

CONTROL_LIMIT = 1024
READY_LIMIT = 16384
GRACEFUL_SECONDS = 5
ENGINE_STOP_SECONDS = 4
DRAIN_SECONDS = 0.25
IDENTITY = "desktop-runtime.json"
LOCK = "desktop-runtime.lock"

MESSAGES = {
    "invalid_arguments": "Supply an explicit project and dedicated state directory.",
    "invalid_project": "Choose an existing absolute project directory without symlinks.",
    "invalid_state": "Choose a private, dedicated state directory outside the project.",
    "project_mismatch": "This state belongs to another project. Use that project's state directory.",
    "already_running": "Another desktop runtime owns this state directory.",
    "invalid_control": "Unrecognized desktop control input; the runtime is stopping.",
    "startup_failed": "The desktop runtime could not start. Existing evidence is preserved.",
    "runtime_failed": "The desktop runtime stopped unexpectedly. Existing evidence is preserved.",
    "unsupported_platform": "The desktop runtime requires macOS or a compatible Linux host.",
}


class DesktopError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def _absolute_directory(value, code, *, existing):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or len(os.fsencode(path)) > 4096
            or any(ord(character) < 32 for character in str(path))):
        raise DesktopError(code)
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink():
            raise DesktopError(code)
    if existing and not path.is_dir():
        raise DesktopError(code)
    if path.exists() and not path.is_dir():
        raise DesktopError(code)
    return path.resolve()


def selected_paths(workspace, state_directory):
    project = _absolute_directory(workspace, "invalid_project", existing=True)
    state = _absolute_directory(state_directory, "invalid_state", existing=False)
    home = Path.home().resolve()
    from .store import state_directory as cli_state_directory
    cli_state = cli_state_directory().resolve()
    if project == Path("/") or project == home:
        raise DesktopError("invalid_project")
    if (home.is_relative_to(state) or cli_state.is_relative_to(state)
            or project.is_relative_to(state) or state.is_relative_to(project)):
        raise DesktopError("invalid_state")
    return project, state


def _private_regular(descriptor):
    details = os.fstat(descriptor)
    if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
            or details.st_nlink != 1 or details.st_mode & 0o077):
        raise DesktopError("invalid_state")


def _admit_state_tree(state):
    """SQLite sidecars and saved state cannot redirect writes outside this root.

    Candidate-internal links and the task venv's exact interpreter aliases are
    retained. Directory links out of state and hardlinked files are refused.
    """
    interpreter = Path(sys.executable).resolve()
    for directory, dirs, files in os.walk(state, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            details = path.lstat()
            if details.st_uid != os.getuid():
                raise DesktopError("invalid_state")
            if stat.S_ISLNK(details.st_mode):
                target = path.resolve()
                relative = path.relative_to(state)
                executable_alias = ("environments" in relative.parts
                    and path.parent.name == "bin" and path.parent.parent.name == "venv"
                    and bool(re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)?)?", name))
                    and target == interpreter and target.is_file())
                if not target.is_relative_to(state) and not executable_alias:
                    raise DesktopError("invalid_state")
                if path.parent == state:
                    raise DesktopError("invalid_state")
            elif stat.S_ISREG(details.st_mode):
                if details.st_nlink != 1 or (path.parent == state and details.st_mode & 0o077):
                    raise DesktopError("invalid_state")
            elif not stat.S_ISDIR(details.st_mode):
                raise DesktopError("invalid_state")
            elif path.parent == state and details.st_mode & 0o077:
                raise DesktopError("invalid_state")


@contextmanager
def desktop_state(project, state):
    """Never adopt an existing CLI/worker database or follow a lock/token symlink."""
    import fcntl
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        details = os.fstat(root)
        if details.st_uid != os.getuid():
            raise DesktopError("invalid_state")
        names = set(os.listdir(root))
        if not names:
            os.fchmod(root, 0o700)
        elif details.st_mode & 0o077:
            raise DesktopError("invalid_state")
        if IDENTITY not in names and names - {LOCK}:
            raise DesktopError("invalid_state")
        lock = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
        _private_regular(lock)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DesktopError("already_running") from exc
        if state.is_symlink() or state.stat().st_ino != details.st_ino:
            raise DesktopError("invalid_state")
        if IDENTITY in os.listdir(root):
            descriptor = os.open(IDENTITY, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
            try:
                _private_regular(descriptor)
                data = os.read(descriptor, READY_LIMIT + 1)
                if len(data) > READY_LIMIT:
                    raise DesktopError("invalid_state")
                identity = json.loads(data)
            finally:
                os.close(descriptor)
            if (not isinstance(identity, dict) or set(identity) != {"schema_version", "workspace", "token"}
                    or identity["schema_version"] != "1.0"
                    or not isinstance(identity["token"], str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43}", identity["token"])):
                raise DesktopError("invalid_state")
            if identity["workspace"] != str(project):
                raise DesktopError("project_mismatch")
        else:
            if set(os.listdir(root)) != {LOCK}:
                raise DesktopError("invalid_state")
            identity = {"schema_version": "1.0", "workspace": str(project), "token": secrets.token_urlsafe(32)}
            descriptor = os.open(IDENTITY, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
                    json.dump(identity, handle, separators=(",", ":"))
                    handle.flush()
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(root)
        _admit_state_tree(state)
        yield identity["token"]
    finally:
        if lock is not None:
            os.close(lock)
        os.close(root)


class DesktopBoundary:
    """A desktop session cannot impersonate a relay or select another project."""
    def __init__(self, app, project, stopping):
        self.app, self.project = app, str(project)
        self.stopping = stopping
        self.lifespan_task = None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            self.lifespan_task = asyncio.current_task()
        if scope["type"] == "http":
            from starlette.responses import JSONResponse
            if self.stopping.is_set():
                await JSONResponse({"detail": "Desktop runtime is stopping"}, status_code=503)(scope, receive, send)
                return
            try:
                query = parse_qs(scope.get("query_string", b"").decode("ascii"))
                invalid = (any(name.lower() == b"x-parallax-authority" for name, _ in scope["headers"])
                           or any(value != self.project for value in query.get("workspace", [])))
            except (ValueError, UnicodeError):
                invalid = True
            if invalid:
                await JSONResponse({"detail": "This desktop runtime permits only its selected project"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def _control(reader, stop, errors):
    try:
        value = await reader.readline()
        if value:
            if len(value) > CONTROL_LIMIT:
                raise ValueError()
            command = json.loads(value)
            if not isinstance(command, dict) or command != {"command": "stop"}:
                raise ValueError()
    except (ValueError, UnicodeError):
        errors.append("invalid_control")
    finally:
        stop()


async def _ready(server, task, port):
    while not server.started:
        if task.done():
            await task
            raise DesktopError("startup_failed")
        if server.should_exit:
            return False
        await asyncio.sleep(0.01)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = bytearray()
        while chunk := await reader.read(2048):
            response.extend(chunk)
            if len(response) > 2048:
                raise DesktopError("startup_failed")
        if not response.startswith(b"HTTP/1.1 200 ") or b'"ok":true' not in response:
            raise DesktopError("startup_failed")
    finally:
        writer.close()
        await writer.wait_closed()
    return not server.should_exit


async def run_server(project, state, token, output, *, registry=None):
    """The injected registry is internal test support, never a CLI option."""
    import uvicorn
    from .server import create_app
    from .store import Store

    class ForegroundServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield  # The pipe owner and our loop handlers request graceful shutdown.

    store = Store(state)
    application = create_app(store, registry, token=token, workspace=str(project), allowed_workspaces=(project,), desktop_runtime=True)
    stopping = asyncio.Event()
    boundary = DesktopBoundary(application, project, stopping)
    server = ForegroundServer(uvicorn.Config(boundary, host="127.0.0.1", port=0,
        access_log=False, log_config=None, log_level="critical", timeout_graceful_shutdown=2, lifespan="on"))
    engine_shutdown = application.state.engine.shutdown
    engine_stop = None

    async def close_engine_once():
        nonlocal engine_stop
        if engine_stop is None:
            engine_stop = asyncio.create_task(engine_shutdown())
        await asyncio.shield(engine_stop)

    application.state.engine.shutdown = close_engine_once

    def request_stop():
        application.state.engine.shutting_down = True
        server.should_exit = True
        stopping.set()
    # Startup errors are reported below without raw tracebacks, paths or credentials.
    logging.getLogger("uvicorn.error").disabled = True
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_transport = None
    control_task = serving = readiness = stop_wait = None
    loop = asyncio.get_running_loop()
    errors = []
    installed_signals = []
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        for kind in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(kind, request_stop)
            installed_signals.append(kind)
        reader = asyncio.StreamReader(limit=CONTROL_LIMIT)
        control_transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
        control_task = asyncio.create_task(_control(reader, request_stop, errors))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        readiness = asyncio.create_task(_ready(server, serving, port))
        stop_wait = asyncio.create_task(stopping.wait())
        done, _ = await asyncio.wait({readiness, stop_wait}, timeout=30, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise DesktopError("startup_failed")
        ready = readiness in done and readiness.result() and not stopping.is_set()
        if not ready and not stopping.is_set():
            raise DesktopError("startup_failed")
        if ready:
            url = "http://127.0.0.1:" + str(port) + "/?" + urlencode({"token": token, "workspace": str(project)})
            record = json.dumps({"event": "ready", "url": url, "version": __version__, "pid": os.getpid()}, separators=(",", ":")) + "\n"
            if len(record.encode()) > READY_LIMIT:
                raise DesktopError("startup_failed")
            output.write(record)
            output.flush()
        await asyncio.wait({serving, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
        if not stopping.is_set():
            raise DesktopError("runtime_failed")
    finally:
        request_stop()
        forced = False
        if serving is not None and not serving.done():
            done, _ = await asyncio.wait({serving}, timeout=GRACEFUL_SECONDS)
            forced = not done
        # A broken/hung ASGI lifespan must still stop Engine-owned processes.
        close = asyncio.create_task(close_engine_once())
        done, _ = await asyncio.wait({close}, timeout=ENGINE_STOP_SECONDS)
        forced = forced or not done
        pending = {task for task in (control_task, readiness, stop_wait, serving, boundary.lifespan_task, close)
                   if task is not None and not task.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=DRAIN_SECONDS)
        for task in (readiness, serving, close):
            if task is not None and task.done() and not task.cancelled():
                failure = task.exception()
                if failure is not None and not isinstance(failure, DesktopError):
                    forced = True
        if control_transport is not None:
            control_transport.close()
        for kind in installed_signals:
            loop.remove_signal_handler(kind)
        listener.close()
        store.close()
        if forced:
            raise DesktopError("runtime_failed")
    if errors:
        raise DesktopError(errors[0])


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise DesktopError("invalid_arguments")

    def _print_message(self, message, file=None):
        super()._print_message(message, sys.stderr)


def main(argv=None):
    output = sys.stdout
    os.umask(0o077)
    try:
        with redirect_stdout(sys.stderr):
            if os.name != "posix":
                raise DesktopError("unsupported_platform")
            parser = _Arguments(prog="parallax.desktop")
            parser.add_argument("--workspace", required=True)
            parser.add_argument("--state-directory", required=True)
            args = parser.parse_args(argv)
            project, state = selected_paths(args.workspace, args.state_directory)
            with desktop_state(project, state) as token:
                os.environ["PARALLAX_HOME"] = str(state)
                # Unlike asyncio.run's unbounded cancellation gather, this
                # foreground owner bounds cleanup of a broken ASGI lifespan.
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(run_server(project, state, token, output))
                finally:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.wait(pending, timeout=DRAIN_SECONDS))
                    loop.close()
                    asyncio.set_event_loop(None)
        return 0
    except DesktopError as exc:
        sys.stderr.write("Parallax desktop: " + MESSAGES[exc.code] + "\n")
        return 1 if exc.code in {"startup_failed", "runtime_failed"} else 2
    except Exception:
        sys.stderr.write("Parallax desktop: " + MESSAGES["startup_failed"] + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
