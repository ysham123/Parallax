import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from parallax.models import RunSpec
from parallax.receipt import build_receipt, get_receipt, save_receipt
from parallax.server import create_app
from parallax.store import Store


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        directory = self.store.home / "runs" / "run-1"
        directory.mkdir(parents=True)
        self.result = {"run_id": "run-1", "status": "completed",
                       "spec": RunSpec(workspace="/private/project", prompt="private request").model_dump(),
                       "diff": "diff --git a/app.py b/app.py\n", "changed_files": ["app.py"],
                       "tasks": [{"id": "implementation", "provider": "claude", "status": "completed"}],
                       "checks": [{"ok": True, "exit_code": 0, "elapsed_seconds": 0.1,
                                   "argv": ["/private/interpreter", "--api-key", "credential"], "output": "private output"}],
                       "reviews": [{"task_id": "integration", "provider": "grok", "ok": True,
                                    "summary": "private review"}],
                       "sessions": [{"provider": "claude", "session_id": "private-session",
                                     "effective_settings": {"model": "sonnet", "effort": "high", "endpoint": "private endpoint"}}],
                       "artifacts": {"directory": str(directory), "integration_applied": True,
                                     "validated_fingerprint": "diff --git a/app.py b/app.py\n",
                                     "preservation": {key: True for key in ("staging", "head", "branch", "unrelated_files")}}}

    def test_recorded_gates_and_safe_export(self):
        receipt = build_receipt(self.result)
        self.assertTrue(all(g["status"] == "passed" for g in receipt["gates"]))
        data = json.dumps(receipt)
        for secret in ("/private", "private request", "private output", "private review", "private-session", "credential", "private endpoint"):
            self.assertNotIn(secret, data)
        self.assertEqual(receipt["artifacts"]["patch_sha256"], hashlib.sha256(self.result["diff"].encode()).hexdigest())

    def test_missing_preservation_or_stale_approval_is_never_passed(self):
        result = copy.deepcopy(self.result)
        result["artifacts"].pop("preservation")
        result["diff"] += "changed"
        gates = {gate["id"]: gate["status"] for gate in build_receipt(result)["gates"]}
        self.assertEqual(gates["preservation"], "unknown")
        self.assertEqual(gates["current_verification"], "unknown")
        self.assertEqual(gates["independent_review"], "unknown")
        self.assertEqual(gates["project_checks"], "unknown")

    def test_self_review_and_failed_checks_are_visible(self):
        result = copy.deepcopy(self.result)
        result["reviews"][-1]["provider"] = "claude"
        result["checks"][0]["ok"] = False
        gates = {gate["id"]: gate["status"] for gate in build_receipt(result)["gates"]}
        self.assertEqual(gates["independent_review"], "unknown")
        self.assertEqual(gates["project_checks"], "failed")

    def test_saved_record_is_stable_and_tampering_is_detected(self):
        receipt = save_receipt(self.result)
        self.store.save(self.result)
        self.assertEqual(get_receipt(self.store, "run-1"), receipt)
        Path(self.result["artifacts"]["verification_record"]).write_text("{}")
        with self.assertRaisesRegex(ValueError, "changed"):
            get_receipt(self.store, "run-1")

    def test_record_detects_a_changed_run_specification(self):
        save_receipt(self.result)
        self.result["spec"]["prompt"]="different requirements"
        self.store.save(self.result)
        with self.assertRaisesRegex(ValueError,"specification"):
            get_receipt(self.store,"run-1")

    def test_downloads_require_auth_and_use_saved_patch(self):
        self.store.save(self.result)
        class Registry: pass
        with TestClient(create_app(self.store, Registry(), token="private-token")) as client:
            self.assertEqual(client.get("/api/runs/run-1/receipt").status_code, 401)
            headers = {"Authorization": "Bearer private-token"}
            response = client.get("/api/runs/run-1/receipt", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertEqual(client.get("/api/runs/run-1/patch", headers=headers).text, self.result["diff"])

if __name__ == "__main__": unittest.main()
