#!/usr/bin/env python3
"""Prepare matched disposable snapshots. Never run inference or apply changes."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from parallax.workspaces import WorkspaceManager
from parallax.models import RunSpec

def prepare(project: Path, destination: Path, spec: RunSpec, participant: int, task: int) -> dict:
    if not 1<=participant<=5 or not 1<=task<=3: raise ValueError('Alpha uses participants 1–5 and tasks 1–3')
    destination=destination.expanduser().resolve();project=project.expanduser().resolve()
    if destination.exists(): raise ValueError('Choose a fresh destination; existing study attempts are preserved')
    if destination.is_relative_to(project): raise ValueError('Study snapshots belong outside the source project')
    destination.mkdir(parents=True,mode=0o700)
    manager=WorkspaceManager(project,destination/'snapshot');manager.prepare()
    parallax=manager.create_worker('parallax');single=manager.create_worker('single-codex')
    if manager.fingerprint(parallax)!=manager.fingerprint(single): raise ValueError('Matched snapshots differ')
    spec=spec.model_copy(deep=True);spec.workspace=str(parallax);spec.integrate=True
    spec_file=destination/'parallax-spec.json';spec_file.write_text(spec.model_dump_json(indent=2));spec_file.chmod(0o600)
    order=['parallax','single_codex'] if (participant+task)%2==0 else ['single_codex','parallax']
    record={'schema_version':'1.1','participant':participant,'task_number':task,'order':order,
            'snapshot_sha256':manager.fingerprint(parallax),'parallax_workspace':str(parallax),'single_codex_workspace':str(single),
            'codex_settings':{'model':spec.coordinator.model,'effort':spec.coordinator.effort},'parallax_spec':str(spec_file),
            'prompt_sha256':hashlib.sha256(spec.prompt.encode()).hexdigest(),'inference_started':False,'shared':False}
    path=destination/'study.json';path.write_text(json.dumps(record,indent=2)+'\n');path.chmod(0o600)
    return record

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--participant',type=int,required=True);parser.add_argument('--task',type=int,required=True)
    args=parser.parse_args();record=prepare(args.project,args.destination,RunSpec.model_validate_json(args.spec.read_text()),args.participant,args.task)
    print(json.dumps(record,indent=2))
if __name__=='__main__': main()
