"""The configured App key remains protected after environment removal."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from parallax.engine import Engine, _sandbox_check
from parallax.assessment import execution_capability
from parallax.github_delivery import GitHubDelivery
from parallax.store import Store
from test_isolation_secrets import CANARY, fixture_directory, canary_script


class GitHubKeyIsolationTests(unittest.TestCase):
    def test_configured_key_is_retained_by_policy_after_env_is_popped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = Store(root / 'state')
            self.addCleanup(store.close)
            project = root / 'project'
            project.mkdir()
            key = root / 'external-key'
            key.write_text(CANARY)
            with patch.dict(os.environ, {'PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH': str(key)}):
                service = GitHubDelivery(store)
                self.assertNotIn('PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH', os.environ)
                self.assertEqual(service.config['private_key_path'], str(key))
                with patch('parallax.engine.sys.platform', 'linux'), patch('parallax.engine.shutil.which', return_value='/usr/bin/bwrap'):
                    command = _sandbox_check(['/bin/true'], project)
                self.assertIn(['--ro-bind', '/dev/null', str(key)], [command[i:i+3] for i in range(len(command))])

    @unittest.skipUnless(sys.platform == 'darwin' or sys.platform.startswith('linux'), 'requires native command sandbox')
    def test_actual_configured_external_key_is_unreadable_after_server_setup(self):
        self.assertTrue(execution_capability()['enforced'], 'Native host must enforce command isolation')
        with fixture_directory() as directory:
            root = Path(directory).resolve()
            store = Store(root / 'server-state')
            self.addCleanup(store.close)
            engine = Engine(store, registry=object())
            project = root / 'project'
            project.mkdir()
            (project / 'accepted.txt').write_text('approved project')
            key = root / 'server-private-key'
            key.write_text(CANARY)
            with patch.dict(os.environ, {'PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH': str(key)}):
                service = GitHubDelivery(store)
                self.assertNotIn('PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH', os.environ)
                result = subprocess.run(_sandbox_check([sys.executable, '-c', canary_script(project, [key])], project), cwd=project, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(project), 'TMPDIR': str(project)}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(key.read_text(), CANARY)
