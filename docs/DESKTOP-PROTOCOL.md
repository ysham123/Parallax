# Desktop runtime protocol

The desktop application launches its embedded, installed runtime in the foreground:

```text
python3 -I -B -m parallax.desktop --workspace PATH --state-directory PATH
```

Both paths must be absolute and have no symlink components. The selected project must already exist. Filesystem roots, the user's home, overlapping project/state roots, unrelated existing state and the CLI's own state directory are refused. A dedicated state directory is permanently bound to one canonical project. The app uses a separate directory for each selected project, such as `~/Library/Application Support/Parallax/Beta/projects/<sha256-of-canonical-path>`. A different project cannot reuse that directory.

`-I` ignores `PYTHONPATH`, so the module and locked dependencies must be installed in the embedded interpreter's import locations. The runtime neither bootstraps dependencies nor consults the CLI's running service. It binds an ephemeral port on `127.0.0.1`; it does not bind other interfaces or adopt an existing endpoint.

## Readiness and authentication

After the existing application lifespan completes and an actual HTTP health request succeeds, stdout emits exactly one UTF-8 JSON line, at most 16,384 bytes:

```json
{"event":"ready","url":"http://127.0.0.1:PORT/?token=SECRET&workspace=ENCODED_PATH","version":"VERSION","pid":12345}
```

The parent validates the event, expected version and child PID, literal loopback host, port and selected project before opening its default browser. The URL is a bearer capability: never log, persist in application preferences, copy into telemetry or print it. Existing Studio exchanges the launch token for an HttpOnly cookie and removes the token from the address bar. HTTP access and origin checks remain those of `create_app`; only the selected project is permitted. Desktop requests cannot supply relay authority headers or foreign workspace query values.

Authenticated `/api/context` includes `desktop_runtime: true`, set only by the internal desktop entry point. Other application entry points default to false, and request parameters cannot select this runtime mode. Desktop Connections uses explicit API keys stored by the existing macOS Keychain adapter; shell environment references are disabled in Studio and refused by the API. Metadata-only edits preserve an existing reference when no credential is supplied. Replacing it requires an explicit key. CLI, hosted and paired-worker credential behavior remains unchanged.

No error record or diagnostic is written to stdout. Startup errors use fixed, sanitized stderr text with no supplied paths, tokens or tracebacks. Exit status 2 means invalid arguments, unsafe paths/state, a project binding mismatch, an existing owner or invalid control input. Unexpected startup/runtime errors return 1. The parent must also handle exit without readiness and broken pipes. All other output goes to stderr; neither stdout nor stderr should be saved as telemetry.

## Ownership and shutdown

The parent keeps stdin open for the owned process. To stop it, write exactly this JSON line:

```json
{"command":"stop"}
```

Then close stdin. EOF also requests graceful shutdown, including when the parent terminates. SIGINT and SIGTERM request the same shutdown without requiring stdin to close. Other commands, extra fields, malformed UTF-8/JSON and control records over 1,024 bytes cause graceful shutdown with an invalid-control error. The control channel cannot change projects, start tasks or execute commands.

Shutdown first allows up to five seconds for the existing application lifespan, including workflow close and `Engine.shutdown()`. A hung lifespan still triggers Engine shutdown, with a further four seconds for owned work to stop and a bounded cancellation drain. Engine shutdown runs once. A broken or timed-out lifecycle returns status 1, including when stop or EOF arrives during a hung startup; it never emits readiness for that startup. Running cooperative work becomes resumable interrupted evidence, its managed subprocesses are reaped, and the durable execution budget retains consumed time. Restart does not automatically redispatch interrupted work. An uninterruptible operating-system child remains subject to existing recorded-identity recovery; a bounded GUI shutdown is not proof that every possible kernel hang has exited. The app should allow graceful shutdown before signalling its own child. A pipe inherited by unrelated processes could delay EOF, so the launcher must keep control descriptors private.

The state directory is mode 0700. `desktop-runtime.lock` and `desktop-runtime.json` are owned, non-symlink regular files with mode 0600. The lock stays held for the complete foreground server lifetime. A second instance fails without connecting to the first runtime. `desktop-runtime.json` stores only schema version, selected canonical project and a persistent launch token, allowing existing local sessions to reconnect after restart. It contains no endpoint URL. Before opening SQLite, existing state is checked for ownership, hardlinks, special files, public direct children and links that escape the dedicated state. This covers databases, WAL/SHM/journal sidecars and saved-state directories. Candidate-internal links and task venv aliases to the exact current interpreter remain valid. Existing SQLite and candidate evidence remain in this private directory. No CLI `server.json` is read or written. Refused or damaged state must be reviewed without automatically deleting its evidence.

A saved task venv may point to the embedded interpreter's previous location after moving or upgrading the app. Such obsolete or dangling external aliases fail closed before the database is opened. The runtime does not execute an old interpreter, replace its links or discard saved workflows and budgets. Restoring the original app location or a separately reviewed environment migration is required before reusing that state. Keep the installed beta app at the same path after provisioning task environments. Python private cache identity includes the canonical interpreter path, full Python version and implementation cache tag, so replacing a runtime at the same path creates a fresh cache without resetting workflows or consumed budgets. Existing-state relocation and native project dependency compatibility remain distribution gates; a fresh-state relocation test does not prove either one.

## Validation boundary

`tests/test_desktop_runtime.py` starts real foreground subprocesses with exact `-I -B -m` arguments through an isolated temporary installed-module harness. It verifies HTTP readiness/authentication, project/authority/origin refusal, private state, single ownership, explicit stop, EOF, signals, restart/session continuity, silent startup failure and bounded hung lifespans. Linked databases, SQLite sidecars, hardlinks and saved directories are refused while unrelated target bytes and write-related metadata remain unchanged. Actual Engine jobs spawn inert managed children; both stop and EOF reap them and preserve interruption/budget evidence. Current task interpreter aliases and internal candidate links restart successfully; obsolete interpreter aliases preserve evidence and fail closed. The tests perform no model inference and touch no user configuration. The harness is not proof of embedded application packaging, signing, notarization, clean-Mac launch or live-provider acceptance. The runtime preserves the existing native/command isolation gates; a desktop wrapper does not make unsupported providers or hosts supported.
