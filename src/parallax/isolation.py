"""Private runtime paths shared by every project-command sandbox.

Registrations follow the live Store/agent, rather than inherited environment
variables: server credentials are removed from that environment during setup.
No credential contents enter this policy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from weakref import WeakKeyDictionary

_owners = WeakKeyDictionary()
_lock = threading.RLock()

# File-tool and shell policies share these names. Dependencies remain readable;
# authentication, repository control, and engine markers do not.
NATIVE_PRIVATE_NAMES = frozenset({
    '.git', '.parallax-home', '.parallax-api', '.ssh', '.aws', '.config',
    '.grok', '.claude', '.codex', '.agents', '.netrc', '.npmrc', '.pypirc',
    '.parallax-owned',
})


def native_scopes(workspace, *, extra_readable=()):
    """Resolve trusted grants and private denies for native participant tools.

    Native sign-in files are used by the client, never granted to model tools.
    A candidate may be a narrow child of runtime state; its siblings stay private.
    """
    workspace = Path(workspace).resolve()
    readable = {workspace, *(Path(path).resolve() for path in extra_readable)}
    roots, files = private_paths()
    validate_grants(roots, readable)
    if any(any(character in str(path) for character in '*?[]') for path in readable | roots | files):
        raise ValueError('Native filesystem scopes cannot contain glob metacharacters')
    if any(workspace == path or workspace.is_relative_to(path) for path in files):
        raise ValueError('Native workspace overlaps a private credential file')
    return readable, roots, files


def native_secret_globs():
    """Relative project patterns, including case-insensitive secret spellings."""
    insensitive = lambda value: ''.join(
        '[' + c.lower() + c.upper() + ']' if c.isascii() and c.isalpha() else c
        for c in value)
    return ['**/' + insensitive('.env') + '*', *(
        '**/' + insensitive(name) + '/**' for name in sorted(NATIVE_PRIVATE_NAMES)
    ), *('**/' + insensitive(name) for name in sorted(NATIVE_PRIVATE_NAMES))]


def register_private_paths(owner, *, state=(), files=()):
    """Remember server-owned state roots and exact credential files."""
    with _lock:
        roots, secrets = _owners.setdefault(owner, (set(), set()))
        roots.update(Path(path).expanduser().absolute() for path in state if path)
        secrets.update(Path(path).expanduser().absolute() for path in files if path)


def private_paths():
    with _lock:
        roots, files = set(), set()
        for state, secrets in list(_owners.values()):
            roots.update(state)
            files.update(secrets)
    if os.environ.get("PARALLAX_HOME"):
        roots.add(Path(os.environ["PARALLAX_HOME"]).expanduser().absolute())
    if os.environ.get("PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH"):
        files.add(Path(os.environ["PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH"]).expanduser().absolute())
    # State grants use canonical paths too, so native subpath exceptions must
    # compare canonical roots. Retain file aliases as well as current targets:
    # key rotation must not quietly unprotect the configured file location.
    roots = {path.resolve() for path in roots}
    files.update(path.resolve() for path in tuple(files))
    if Path("/") in roots:
        raise ValueError("Runtime state cannot use the filesystem root")
    return roots, files


def validate_grants(roots, grants):
    if Path("/") in grants or any(root == grant for root in roots for grant in grants):
        raise ValueError("Command scope cannot expose a complete runtime state directory")


def macos_private_rules(roots, files, *, readable, writable):
    """Hide state except narrowly granted candidate/check-environment children."""
    rules = []
    for root in sorted(roots):
        for operations, grants in (("file-read-data", readable), ("file-write*", writable)):
            children = [path for path in grants if path != root and path.is_relative_to(root)]
            scope = '(subpath ' + json.dumps(str(root)) + ')'
            if children:
                permitted = '(require-any ' + ' '.join(
                    '(' + ('literal' if path.is_file() else 'subpath') + ' ' + json.dumps(str(path)) + ')'
                    for path in sorted(set(children))) + ')'
                scope = '(require-all ' + scope + ' (require-not ' + permitted + '))'
            rules.append('(deny ' + operations + ' ' + scope + ')')
    for path in sorted(files):
        rules.append('(deny file-read* file-write* (literal ' + json.dumps(str(path)) + '))')
    return ''.join(rules)


def linux_runtime_reads():
    """OS code and public runtime configuration, never the whole host root."""
    return [Path(path) for path in (
        '/usr', '/bin', '/sbin', '/lib', '/lib64',
        '/etc/ld.so.cache', '/etc/ld.so.conf', '/etc/ld.so.conf.d',
        '/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf',
        '/etc/passwd', '/etc/group', '/etc/localtime',
        '/etc/ssl/certs', '/etc/ssl/openssl.cnf',
    ) if Path(path).exists()]


def linux_private_masks(roots):
    command = []
    for path in sorted(roots, key=lambda path: (len(path.parts), str(path))):
        command.extend(['--tmpfs', str(path)])
    return command
