#!/usr/bin/env python3
"""Portable launcher with a content-versioned, privately installed runtime."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import venv
import fcntl

root=Path(__file__).resolve().parents[1]
if sys.version_info < (3,10):
    raise SystemExit("Parallax requires Python 3.10 or newer")
sys.path.insert(0,str(root/"src"))
from parallax.store import state_directory
home=state_directory();home.mkdir(parents=True,exist_ok=True,mode=0o700)
digest=hashlib.sha256()
sources=[root/"pyproject.toml",root/"requirements.lock",*sorted((root/"src/parallax").rglob("*.py")),*sorted((root/"src/parallax/static").rglob("*"))]
for path in sources:
    if path.is_file(): digest.update(str(path.relative_to(root)).encode());digest.update(path.read_bytes())
fingerprint=digest.hexdigest()
python_minor=f"py{sys.version_info.major}.{sys.version_info.minor}"
environment=home/"environments"/("1.0.0-"+python_minor+"-"+fingerprint[:12])
executable=environment/"bin"/"python"
ready=environment/"ready"
with (home/"bootstrap.lock").open("a") as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    installed=executable.is_file() and ready.is_file() and ready.read_text()==fingerprint
    if not installed:
        print("Preparing Parallax's local Python runtime…",file=sys.stderr)
        venv.EnvBuilder(with_pip=True,clear=True).create(environment)
        subprocess.run([str(executable),"-m","pip","install","--disable-pip-version-check","--require-hashes","--only-binary=:all:","-r",str(root/"requirements.lock")],check=True,stdout=sys.stderr)
        ready.write_text(fingerprint)
if Path(sys.prefix).resolve()!=environment.resolve():
    env={**os.environ,"PYTHONPATH":str(root/"src"),"PYTHONNOUSERSITE":"1"}
    os.execve(str(executable),[str(executable),str(Path(__file__).resolve()),*sys.argv[1:]],env)
from parallax.cli import main
main()
