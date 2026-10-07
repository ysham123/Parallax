"""Local project memory controls: list, disable, and forget lessons; never reachable through the relay."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from parallax.executors import permitted
from parallax.ideas import IdeaStore
from parallax.server import create_app
from parallax.store import Store
from test_engine import FakeRegistry
from test_ideas import add_lesson, make_repo


class MemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = make_repo(root / "project").resolve()
        (self.project / "billing").mkdir()
        self.store = Store(root / "state")
        self.ideas = IdeaStore(self.store.home, str(self.project))
        self.lesson = add_lesson(self.ideas, "Empty invoice lists must total zero", ["billing/invoice.py"])
        self.client = TestClient(create_app(self.store, FakeRegistry(), token="memory-token", allowed_workspaces=(self.project,)))
        self.addCleanup(self.client.close)
        self.auth = {"Authorization": "Bearer memory-token"}

    def test_list_disable_and_forget(self):
        listed = self.client.get("/api/memory", params={"workspace": str(self.project)}, headers=self.auth).json()
        self.assertEqual([l["id"] for l in listed["lessons"]], [self.lesson])
        self.assertEqual(listed["counts"]["lessons"], 1)
        update = self.client.patch(f"/api/memory/lessons/{self.lesson}", json={"workspace": str(self.project), "status": "disabled"}, headers=self.auth)
        self.assertEqual(update.status_code, 200)
        self.assertEqual(self.ideas.search("empty invoice totals", ["billing/invoice.py"]), [])
        self.assertEqual(self.client.patch("/api/memory/lessons/L-000000000000", json={"workspace": str(self.project), "status": "active"}, headers=self.auth).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/memory/lessons/{self.lesson}", json={"workspace": str(self.project), "status": "superseded"}, headers=self.auth).status_code, 422)
        with self.store.connect() as db:
            db.execute("INSERT INTO project_locks VALUES(?,?)", (str(self.project), "run-1"))
        self.assertEqual(self.client.delete("/api/memory", params={"workspace": str(self.project)}, headers=self.auth).status_code, 409)
        with self.store.connect() as db:
            db.execute("DELETE FROM project_locks")
        self.assertEqual(self.client.delete("/api/memory", params={"workspace": str(self.project)}, headers=self.auth).status_code, 200)
        self.assertFalse(self.ideas.path.exists())

    def test_unapproved_projects_and_the_relay_are_refused(self):
        other = make_repo(Path(self.temp.name) / "other")
        self.assertEqual(self.client.get("/api/memory", params={"workspace": str(other)}, headers=self.auth).status_code, 400)
        self.assertEqual(self.client.get("/api/memory", params={"workspace": str(self.project)}).status_code, 401)
        for method, path in (("GET", "/api/memory"), ("DELETE", "/api/memory"), ("PATCH", f"/api/memory/lessons/{self.lesson}")):
            self.assertFalse(permitted(method, path))


if __name__ == "__main__":
    unittest.main()
