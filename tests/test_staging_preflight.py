"""Configuration diagnostics must fail closed without exposing supplied values."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

path = Path(__file__).resolve().parents[1] / "scripts" / "staging_preflight.py"
spec = importlib.util.spec_from_file_location("staging_preflight", path)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class StagingPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = {"PARALLAX_ACCESS_TOKEN": "public-synthetic-test-key-1234567890-ABCDEFG",
                       "PARALLAX_STUDIO_ORIGINS": "https://studio.example.com",
                       "PARALLAX_PUBLIC_ORIGIN": "https://studio.example.com",
                       "PARALLAX_ALLOWED_HOSTS": "studio.example.com,runtime.example.com",
                       "PARALLAX_HOME": str(self.root / "state"),
                       "PARALLAX_PROJECTS_ROOT": str(self.root / "projects"),
                       "PARALLAX_GITHUB_CLIENT_ID": "Iv1.publicclient",
                       "PARALLAX_GITHUB_CLIENT_SECRET": "PUBLIC_SYNTHETIC_SIGNIN_SECRET_123456789",
                       "PARALLAX_SIGNUP": "allowlist", "PARALLAX_ALLOWED_GITHUB_IDS": "101,102",
                       "PARALLAX_PILOT_ENABLED": "off"}

    def assess(self, **kwargs):
        with patch.dict(os.environ, self.values, clear=True):
            return preflight.assess(**kwargs)

    def test_missing_configuration_reports_names_without_defaults_passing(self):
        self.values = {}
        report = self.assess(delivery=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["check"] == "PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH present" and not item["ok"] for item in report["checks"]))

    def test_valid_restricted_runtime_is_configuration_only(self):
        report = self.assess()
        self.assertTrue(report["ok"], report)
        self.assertIn("no authentication", report["scope"])
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root / "projects").exists())

    def test_invalid_secret_shaped_inputs_are_never_rendered(self):
        self.values["PARALLAX_STUDIO_ORIGINS"] = "DO_NOT_RENDER_THIS_PRIVATE_CANARY"
        self.values["PARALLAX_GITHUB_APP_CLIENT_SECRET"] = "DO_NOT_RENDER_SECOND_PRIVATE_CANARY"
        report = self.assess(delivery=True)
        self.assertFalse(report["ok"])
        encoded = json.dumps(report)
        self.assertNotIn("DO_NOT_RENDER", encoded)
        self.assertNotIn(self.values["PARALLAX_ACCESS_TOKEN"], encoded)
        self.assertNotIn(self.values["PARALLAX_GITHUB_CLIENT_SECRET"], encoded)

    def test_safe_signing_key_passes_and_project_key_is_refused(self):
        key = self.root / "secrets" / "app.pem"
        key.parent.mkdir()
        key.write_bytes(rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key.chmod(0o600)
        self.values.update({"PARALLAX_GITHUB_APP_ID": "1234", "PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH": str(key),
                            "PARALLAX_GITHUB_APP_CLIENT_ID": "Iv1.deliverytest", "PARALLAX_GITHUB_APP_SLUG": "parallax-staging",
                            "PARALLAX_GITHUB_APP_CLIENT_SECRET": "PUBLIC_SYNTHETIC_DELIVERY_SECRET_12345678",
                            "PARALLAX_GITHUB_APP_WEBHOOK_SECRET": "PUBLIC_SYNTHETIC_WEBHOOK_SECRET_123456789"})
        self.assertTrue(self.assess(delivery=True)["ok"])
        self.values["PARALLAX_PROJECTS_ROOT"] = str(key.parent)
        self.assertFalse(self.assess(delivery=True)["ok"])
        self.values["PARALLAX_PROJECTS_ROOT"] = str(self.root / "projects")
        key.chmod(0o644)
        self.assertFalse(self.assess(delivery=True)["ok"])
