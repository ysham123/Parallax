"""Finite recovery choices and opt-in aggregate alpha metrics."""
from __future__ import annotations
import json
from collections import Counter
from typing import Literal
from pydantic import Field
from .models import Contract

CATEGORIES = ('environment', 'provider_permission', 'rejected_review', 'failed_checks', 'destination_conflict', 'interrupted', 'configuration', 'runtime')

def classify(message: str) -> str:
    text = message.lower()
    if any(word in text for word in ('destination', 'conflict', 'concurrent', 'index changed', 'staging')): return 'destination_conflict'
    if any(word in text for word in ('permission', 'authentication', 'unauthenticated', 'sandbox', 'denied', 'sign in', 'login')): return 'provider_permission'
    if any(word in text for word in ('environment', 'dependencies', 'dependency', 'provision', 'manifest', 'npm', 'venv', 'check_unavailable')): return 'environment'
    if 'review' in text and any(word in text for word in ('failed', 'rejected', 'reject')): return 'rejected_review'
    if 'check' in text or 'verification' in text: return 'failed_checks'
    if any(word in text for word in ('interrupted', 'termination', 'cancelled')): return 'interrupted'
    if any(word in text for word in ('limit', 'budget', 'configure', 'setting', 'model', 'effort')): return 'configuration'
    return 'runtime'

def recovery_options(result: dict) -> dict:
    artifacts = result.get('artifacts', {})
    if result['status'] not in {'needs_attention', 'interrupted'} or artifacts.get('integration_applied') or artifacts.get('verified_only'):
        return {'category': None, 'actions': []}
    error = (result.get('errors') or [{}])[-1]
    category = error.get('category') or classify(str(error.get('message', result['status'])))
    if result['status'] == 'interrupted': category = 'interrupted'
    choices = {
        'environment': [('fix_configuration', 'Fix project setup', 'Update a project profile and start a new run. The current snapshot is preserved.')],
        'provider_permission': [('retry_interrupted', 'Retry after fixing access', 'Repair CLI sign-in or permissions, then resume at a checkpoint.')],
        'rejected_review': [('repair_candidate', 'Repair with review findings', 'Resume coordination using original criteria and recorded independent findings.')],
        'failed_checks': [('repair_candidate', 'Repair failed checks', 'Resume coordination with the actual command output. Required checks remain unchanged.')],
        'destination_conflict': [('inspect_conflict', 'Inspect destination conflict', 'Inspect the retained diff and changed destination. Resolve edits before resuming.')],
        'interrupted': [('retry_interrupted', 'Reconcile and resume', 'Reconcile saved processes, actions and partial work before continuing.')],
        'configuration': [('fix_configuration', 'Adjust settings for a new run', 'Completed attempts and cumulative limits remain immutable in this run.')],
        'runtime': [('retry_interrupted', 'Inspect and resume', 'Preserved evidence is reconciled before a new coordinator decision.')],
    }
    return {'category': category, 'actions': [{'id': identifier, 'label': label, 'detail': detail} for identifier, label, detail in choices.get(category, choices['runtime'])], 'message': error.get('message', 'Interrupted work was preserved.')}

class RecoveryRequest(Contract):
    action: Literal['retry_interrupted', 'repair_candidate']

class AlphaFeedback(Contract):
    accepted: bool
    setup_unassisted: bool
    manual_interventions: int = Field(default=0, ge=0, le=1000)
    minutes: float = Field(ge=0, le=1440)
    comparison: Literal['parallax', 'single_codex'] = 'parallax'
    task_number: int = Field(ge=1, le=3)
    order: Literal['first', 'second'] = 'first'
    unintended_edits: bool = False
    staging_loss: bool = False

def save_feedback(store, run_id: str, feedback: AlphaFeedback) -> dict:
    if feedback.comparison != 'parallax': raise ValueError('Use the standalone baseline operation for single Codex metrics')
    result = store.get(run_id)
    if result['status'] not in {'completed', 'needs_attention', 'failed', 'cancelled'}: raise ValueError('Record feedback after a run finishes')
    categories = Counter(error.get('category') if error.get('category') in CATEGORIES else classify(str(error.get('message', ''))) for error in result.get('errors', []))
    # Only fixed enums and bounded numeric/bool values enter exportable storage.
    metrics = {**feedback.model_dump(), 'failure_categories': dict(categories), 'runtime_seconds': result.get('artifacts', {}).get('runtime_seconds', 0),
               'repair_attempts': sum(max(0, int(task.get('attempts', 0)) - 1) for task in result.get('tasks', []))}
    with store.connect() as db:
        db.execute('INSERT INTO feedback VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET metrics=excluded.metrics', (run_id, json.dumps(metrics)))
    return {'recorded': True, 'shared': False}

def save_baseline_feedback(store, feedback: AlphaFeedback) -> dict:
    import uuid
    if feedback.comparison != 'single_codex': raise ValueError('Standalone baseline metrics must describe single Codex')
    metrics={**feedback.model_dump(),'failure_categories':{},'runtime_seconds':None,'repair_attempts':0}
    with store.connect() as db:
        db.execute('INSERT INTO feedback VALUES(?,?)',(str(uuid.uuid4()),json.dumps(metrics)))
    return {'recorded':True,'shared':False}

def export_feedback(store) -> dict:
    with store.connect() as db: metrics = [json.loads(row[0]) for row in db.execute('SELECT metrics FROM feedback')]
    groups = []
    for comparison in ('parallax', 'single_codex'):
        rows = [row for row in metrics if row['comparison'] == comparison]
        categories = Counter()
        for row in rows: categories.update(row['failure_categories'])
        groups.append({'comparison': comparison, 'tasks': len(rows), 'accepted': sum(row['accepted'] for row in rows),
                       'setup_trials':sum(row['task_number']==1 for row in rows), 'setup_unassisted': sum(row['setup_unassisted'] for row in rows if row['task_number']==1),
                       'minutes': round(sum(row['minutes'] for row in rows), 2), 'manual_interventions': sum(row['manual_interventions'] for row in rows),
                       'repair_attempts': sum(row['repair_attempts'] for row in rows), 'failure_categories': dict(categories),
                       'unintended_edits': sum(row['unintended_edits'] for row in rows), 'staging_loss': sum(row['staging_loss'] for row in rows),
                       'first': sum(row['order'] == 'first' for row in rows), 'second': sum(row['order'] == 'second' for row in rows)})
    return {'schema_version': '1.1', 'opt_in_records': len(metrics), 'groups': groups, 'contains': 'Aggregate metrics only. No run IDs, prompts, code, keys, session data, paths or command output.', 'shared': False}
