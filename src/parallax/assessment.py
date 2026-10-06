"""Bounded read-only project discovery. Discovery never runs project code."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from .models import CheckSpec, ProjectAssessment
from .store import now

IGNORED = {'.git', '.venv', 'venv', 'node_modules', 'dist', 'build', '__pycache__', '.next', '.tox'}
MANIFESTS = ('package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', 'requirements.txt', 'pyproject.toml')

def execution_capability() -> dict:
    backend = 'seatbelt' if sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file() else 'bubblewrap' if sys.platform.startswith('linux') and shutil.which('bwrap') else None
    available = backend is not None
    if backend == 'bubblewrap':
        try:
            probe = subprocess.run(['bwrap', '--unshare-net', '--ro-bind', '/', '/', '--', '/bin/true'], capture_output=True, timeout=5)
            available = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired): available = False
    return {'backend': backend, 'enforced': available, 'dependency_network': 'install only', 'workspace': 'private Git snapshot',
            'message': 'Project commands are isolated.' if available else 'An enforceable command sandbox is required: macOS sandbox-exec or Linux bubblewrap with user namespaces.'}

def package_directory(workspace: Path, relative: str) -> Path:
    relative = CheckSpec.relative_root(relative)
    root = workspace.resolve()
    path = root / relative
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink(): raise ValueError('Package roots cannot contain symlinks')
    if not path.is_dir() or not path.resolve().is_relative_to(root):
        raise ValueError('Package root is missing or outside the project: ' + relative)
    return path

def _read(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError('Manifests must be regular files below 1 MB')
    return path.read_text()

def assess_project(workspace: str | Path, roots: list[str] | None = None, checks: list[CheckSpec] | None = None,
                   *, execution: dict | None = None, providers: list[dict] | None = None) -> ProjectAssessment:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir(): raise ValueError('Workspace does not exist')
    try:
        probe = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=5)
        git = probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == root
    except (OSError, subprocess.TimeoutExpired): git = False
    directories = []
    instructions = []
    bounded = False
    for directory, dirs, files in os.walk(root, followlinks=False):
        path = Path(directory)
        depth = len(path.relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if d not in IGNORED and not d.startswith('.') and not (path / d).is_symlink()) if depth < 4 else []
        if len(directories) >= 128:
            bounded = True; break
        directories.append(path)
        for name in ('AGENTS.md', 'CLAUDE.md'):
            if name in files and not (path / name).is_symlink(): instructions.append(str((path / name).relative_to(root)))
    selected = [package_directory(root, value) for value in roots] if roots else [p for p in directories if any((p / m).exists() for m in ('package.json', 'pyproject.toml', 'requirements.txt')) or (p / 'tests').is_dir()]
    packages, proposed, issues = [], [], []
    for path in dict.fromkeys(selected):
        relative = str(path.relative_to(root))
        manifests = [name for name in MANIFESTS if (path / name).exists() or (path / name).is_symlink()]
        item = {'root': relative, 'kind': 'unknown', 'manifests': manifests, 'manager': None, 'setup': 'none', 'check_source': 'manifest discovery'}
        try:
            for name in manifests: _read(path / name)
            if 'package.json' in manifests:
                item.update(kind='typescript' if (path / 'tsconfig.json').is_file() else 'javascript', manager='pnpm' if 'pnpm-lock.yaml' in manifests else 'yarn' if 'yarn.lock' in manifests else 'npm')
                package = json.loads(_read(path / 'package.json'))
                if not isinstance(package, dict) or not isinstance(package.get('scripts', {}), dict): raise ValueError('package.json must contain an object and scripts map')
                if package.get('workspaces'):
                    issues.append({'category':'configuration','severity':'blocker','root':relative,'message':'npm workspaces require explicit package roots with per-package lockfiles and check commands for this release.'})
                item['setup'] = 'private npm ci, lifecycle scripts disabled' if item['manager'] == 'npm' and any(m in manifests for m in ('package-lock.json', 'npm-shrinkwrap.json')) else 'unsupported'
                scripts = package.get('scripts', {})
                keys = ['test:ci' if 'test:ci' in scripts else 'test', 'typecheck', 'lint', 'build']
                for key in keys:
                    if isinstance(scripts.get(key), str): proposed.append(CheckSpec(name=f'{relative} · {key}', argv=[item['manager'], 'run', key], timeout=180, cwd=relative))
                if item['setup'] == 'unsupported': issues.append({'category': 'environment', 'severity': 'blocker', 'root': relative, 'message': 'Node setup requires a committed npm lockfile. pnpm and Yarn setup are not supported yet.'})
                if item['manager'] == 'npm' and item['setup'] != 'unsupported' and git:
                    ignored = subprocess.run(['git', '-C', str(path), 'check-ignore', '--no-index', 'node_modules/.parallax-probe'], capture_output=True, timeout=5)
                    if ignored.returncode != 0: issues.append({'category': 'environment', 'severity': 'blocker', 'root': relative, 'message': 'Add node_modules/ to .gitignore before private dependency setup.'})
            if 'pyproject.toml' in manifests or 'requirements.txt' in manifests or (path / 'tests').is_dir():
                item['kind'] = 'mixed' if item['kind'] in {'typescript', 'javascript'} else 'python'
                if item['manager'] is None: item['manager'] = 'pip'
                dependencies = ''
                if 'pyproject.toml' in manifests:
                    try: import tomllib
                    except ImportError: import tomli as tomllib
                    config = tomllib.loads(_read(path / 'pyproject.toml'))
                    dependencies = json.dumps(config.get('project', {}).get('dependencies', []))
                    if config.get('tool', {}).get('poetry') or config.get('project', {}).get('dynamic', []) and not (path / 'requirements.txt').is_file():
                        issues.append({'category': 'environment', 'severity': 'blocker', 'root': relative, 'message': 'Dynamic or Poetry dependencies need an explicit requirements.txt for private setup.'})
                if 'requirements.txt' in manifests: dependencies += _read(path / 'requirements.txt')
                if dependencies and dependencies != '[]': item['setup'] = 'private Python venv' if item['setup'] == 'none' else item['setup'] + ' + Python venv'
                if (path / 'tests').is_dir() and any((path / 'tests').rglob('test*.py')):
                    pytest = 'pytest' in dependencies.lower() or (path / 'pytest.ini').is_file()
                    proposed.append(CheckSpec(name=f'{relative} · Python tests', argv=['python3', '-m', 'pytest', '-q'] if pytest else ['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=relative))
            packages.append(item)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            issues.append({'category': 'environment', 'severity': 'blocker', 'root': relative, 'message': str(exc)})
    for check in checks or []: package_directory(root, check.cwd)
    if bounded: issues.append({'category': 'configuration', 'severity': 'warning', 'message': 'Discovery stopped at 128 directories. Select explicit package roots for this repository.'})
    capability = execution if execution is not None else execution_capability()
    if not git: issues.append({'category': 'configuration', 'severity': 'blocker', 'message': 'Build and Compare require a Git repository root. Review remains available.'})
    if not capability['enforced']: issues.append({'category': 'environment', 'severity': 'blocker', 'message': capability['message']})
    if not checks and not proposed: issues.append({'category': 'configuration', 'severity': 'blocker', 'message': 'No checks discovered. Configure meaningful check commands before Build.'})
    return ProjectAssessment(workspace=str(root), assessed_at=now(), git=git, status='blocked' if any(i['severity'] == 'blocker' for i in issues) else 'ready', packages=packages, instructions=instructions, proposed_checks=proposed, execution=capability, providers=providers or [], issues=issues)
