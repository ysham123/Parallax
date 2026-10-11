import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from parallax.engine import Engine
from parallax.models import CheckSpec
from parallax.provisioning import locked_python_input
from parallax.store import Store


class ProvisioningPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.project = self.root / "project"; self.project.mkdir()
        self.stage = self.root / "stage"; self.stage.mkdir()
        self.manifest = self.project / "requirements.txt"

    def tearDown(self): self.directory.cleanup()

    def test_untrusted_inputs_are_refused_before_commands(self):
        for text in ("./dependency", "-e .", "git+https://example.invalid/repo", "thing>=1", "thing==1", "--index-url https://example.invalid", "-r another.txt", "thing @ https://example.invalid/pkg.whl"):
            with self.subTest(text=text):
                self.manifest.write_text(text)
                with self.assertRaisesRegex(ValueError, "wheels only"):
                    locked_python_input(self.project, self.manifest, [], self.stage)

    def test_locked_input_preserves_markers_and_sha256(self):
        self.manifest.write_text('thing==1.2 ; python_version >= "3.10" \\\n --hash=sha256:' + "a"*64 + "\n")
        result = locked_python_input(self.project, self.manifest, [], self.stage)
        self.assertIn('python_version >= "3.10"', result)
        self.assertIn("--hash=sha256:"+"a"*64, result)

    def test_symlinked_or_external_wheels_are_refused(self):
        external = self.root / "outside.whl"; external.write_bytes(b"public fixture")
        (self.project / "linked.whl").symlink_to(external)
        for name in ("linked.whl", "../outside.whl", str(external)):
            self.manifest.write_text(name)
            with self.assertRaises(ValueError): locked_python_input(self.project, self.manifest, [], self.stage)

    async def test_pep517_backend_is_never_launched_by_default(self):
        dep = self.project / "dependency"; dep.mkdir()
        marker = self.project / "backend-ran"
        (dep / "pyproject.toml").write_text('[build-system]\nrequires=[]\nbuild-backend="backend"\nbackend-path=["."]\n')
        (dep / "backend.py").write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("ran")\n')
        self.manifest.write_text("./dependency\n")
        store = Store(self.root / "state")
        try:
            engine = Engine(store, registry=object(), memory=False)
            identifier = str(uuid4()); run = store.home / "runs" / identifier; run.mkdir(parents=True)
            store.save({"run_id":identifier,"spec":{"workspace":str(self.project)},"status":"running","artifacts":{"directory":str(run)}})
            engine.cancel_flags[identifier] = asyncio.Event()
            engine._command = AsyncMock()
            with self.assertRaisesRegex(ValueError, "source builds"):
                await engine._ensure_environment(identifier, self.project, [CheckSpec(name="tests",argv=["python","-m","unittest"])])
            engine._command.assert_not_called()
            self.assertFalse(marker.exists())
        finally: store.close()
