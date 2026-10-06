"""Release enumeration must exclude caches and reject private artifacts."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from release_files import release_files


class ReleaseInputsTest(unittest.TestCase):
    def test_caches_are_pruned_and_sources_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for name in ('src/parallax/main.py','studio/node_modules/tool/index.js','studio/.playwright-cli/trace.log','studio/dist/app.js','tests/__pycache__/case.pyc'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            self.assertEqual([str(p.relative_to(root)) for p in release_files(root)],['src/parallax/main.py'])

    def test_private_inputs_fail_before_packaging(self):
        for name in ('docs/.env.local','src/state.sqlite3','studio/server.json','docs/api-sessions/request.json','scripts/.grok/config.toml'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_text('private fixture')
                with self.assertRaisesRegex(ValueError,'Private runtime or credential'):
                    release_files(root)

    def test_file_and_directory_symlinks_are_rejected(self):
        for directory in (False,True):
            with self.subTest(directory=directory),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'docs').mkdir();target=root/'outside'
                target.mkdir() if directory else target.write_text('fixture')
                (root/'docs/link').symlink_to(target,target_is_directory=directory)
                with self.assertRaisesRegex(ValueError,'symlinks'):
                    release_files(root)
