"""Trusted runtime context and credential editing without Keychain or providers."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from parallax.connections import ConnectionInput, ConnectionRegistry
from parallax.deployment import Deployment
from parallax.server import create_app
from parallax.store import Store


class MemoryVault:
    storage = "synthetic Keychain"

    def __init__(self):
        self.values = {}

    def get(self, identifier, env=None):
        return None if env else self.values.get(identifier)

    def set(self, identifier, value):
        self.values[identifier] = value

    def delete(self, identifier):
        self.values.pop(identifier, None)


class NoProviders:
    async def discover(self):
        return []

    async def run(self, *args, **kwargs):
        raise AssertionError("Credential setup must not call a model provider")


class DesktopConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="parallax-desktop-credentials-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.vault = MemoryVault()
        self.registry = ConnectionRegistry(self.store, NoProviders(), self.vault)
        self.token = "synthetic-desktop-token-with-more-than-32-characters"
        self.headers = {"Authorization": "Bearer " + self.token}

    def client(self, **options):
        return TestClient(create_app(self.store, self.registry, token=self.token,
            workspace=str(self.project), **options))

    def seed_environment_reference(self):
        return asyncio.run(self.registry.put("codex-api",
            ConnectionInput(provider="codex", api_key_env="SYNTHETIC_OLD_API_KEY")))

    def test_default_runtime_context_is_false_and_cannot_be_selected_by_browser(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/context").status_code, 401)
            for query in ("", "?desktop_runtime=true", "?desktop_runtime=false"):
                response = client.get("/api/context" + query,
                    headers={**self.headers, "X-Parallax-Desktop-Runtime": "true"})
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.json()["desktop_runtime"], False)
                self.assertEqual(response.json()["workspace"], str(self.project))
            result = client.put("/api/connections/codex-api", headers=self.headers,
                json={"provider": "codex", "api_key_env": "SYNTHETIC_API_KEY"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["api_key_env"], "SYNTHETIC_API_KEY")

    def test_desktop_flag_and_refusal_cannot_be_overridden_by_request(self):
        self.seed_environment_reference()
        before = self.registry.configs()
        with self.client(desktop_runtime=True) as client:
            result = client.get("/api/context?desktop_runtime=false",
                headers={**self.headers, "X-Parallax-Desktop-Runtime": "false"})
            self.assertIs(result.json()["desktop_runtime"], True)
            for identifier in ("new-api", "codex-api"):
                response = client.put("/api/connections/" + identifier + "?desktop_runtime=false",
                    headers=self.headers, json={"provider": "codex", "api_key_env": "SYNTHETIC_NEW_API_KEY"})
                self.assertEqual(response.status_code, 400)
                self.assertIn("macOS Keychain", response.json()["detail"])
                self.assertNotIn("SYNTHETIC_NEW_API_KEY", response.text)
            forged = client.put("/api/connections/new-api", headers=self.headers,
                json={"provider": "codex", "api_key_env": "SYNTHETIC_NEW_API_KEY", "desktop_runtime": False})
            self.assertEqual(forged.status_code, 422)
            self.assertEqual(self.registry.configs(), before)
            self.assertEqual(self.vault.values, {})

    def test_desktop_metadata_edit_preserves_old_reference_and_key_replacement_is_separate(self):
        old = self.seed_environment_reference()
        with self.client(desktop_runtime=True) as client:
            metadata = client.put("/api/connections/codex-api", headers=self.headers,
                json={"provider": "codex", "name": "Renamed connection"})
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["api_key_env"], old["api_key_env"])
            self.assertEqual(metadata.json()["credential_version"], old["credential_version"])
            self.assertEqual(self.vault.values, {})
            secret = "synthetic-key-never-stored-in-run-records"
            replaced = client.put("/api/connections/codex-api", headers=self.headers,
                json={"provider": "codex", "api_key": secret})
            self.assertEqual(replaced.status_code, 200)
            self.assertIsNone(replaced.json()["api_key_env"])
            self.assertTrue(replaced.json()["api_configured"])
            self.assertNotEqual(replaced.json()["credential_version"], old["credential_version"])
            self.assertEqual(self.vault.values, {"codex-api": secret})
            self.assertNotIn(secret, replaced.text)
            self.assertNotIn(secret.encode(), self.store.path.read_bytes())

    def test_hosted_runtime_keeps_environment_credentials_and_false_context_default(self):
        deployment = Deployment(self.token, frozenset({"https://studio.example.test"}),
            frozenset({"runtime.example.test"}), self.project)
        with TestClient(create_app(self.store, self.registry, token=self.token,
                workspace=str(self.project), deployment=deployment),
                base_url="https://runtime.example.test") as client:
            self.assertIs(client.get("/api/context", headers=self.headers).json()["desktop_runtime"], False)
            response = client.put("/api/connections/codex-api", headers=self.headers,
                json={"provider": "codex", "api_key_env": "SYNTHETIC_HOSTED_API_KEY"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["api_key_env"], "SYNTHETIC_HOSTED_API_KEY")


if __name__ == "__main__":
    unittest.main()
