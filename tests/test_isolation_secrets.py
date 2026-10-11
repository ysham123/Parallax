"""Runtime state/file canaries in locations outside the user-home deny list."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from parallax.api_agent import ApiAgent
from parallax.assessment import execution_capability
from parallax.engine import Engine, _sandbox_check
from parallax.isolation import register_private_paths
from parallax.store import Store

CANARY = 'PUBLIC SYNTHETIC CREDENTIAL CANARY'


def fixture_directory():
    # /private/var/tmp was outside the former macOS user-data deny list.
    # /dev/shm is a separate Linux host mount, formerly exposed by ro-bind /.
    parent = '/var/tmp' if sys.platform == 'darwin' else '/dev/shm'
    return tempfile.TemporaryDirectory(prefix='parallax-isolation-canary-', dir=parent)


def canary_script(project, secrets):
    return f'''from pathlib import Path
for name in {list(map(str, secrets))!r}:
    target = Path(name)
    try:
        value = target.read_text()
    except (PermissionError, FileNotFoundError):
        pass
    else:
        assert {CANARY!r} not in value, 'private canary readable'
    try:
        target.write_text('attempted escape')
    except (PermissionError, FileNotFoundError):
        pass
assert Path({str(project / 'accepted.txt')!r}).read_text() == 'approved project'
Path({str(project / 'result.txt')!r}).write_text('verified')
print('private state protected; approved project usable')
'''


class IsolationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.store = Store(self.root / 'state')
        self.addCleanup(self.store.close)
        self.engine = Engine(self.store, registry=object())
        self.project = self.root / 'project'
        self.project.mkdir()

    def linux_command(self, **kwargs):
        with patch('parallax.engine.sys.platform', 'linux'), patch('parallax.engine.shutil.which', return_value='/usr/bin/bwrap'):
            return _sandbox_check(['/bin/true'], self.project, **kwargs)

    def test_linux_root_contains_runtime_allowlist_and_no_blanket_host_binding(self):
        command = self.linux_command()
        self.assertNotIn(['--ro-bind', '/', '/'], [command[i:i+3] for i in range(len(command))])
        self.assertIn(['--tmpfs', '/'], [command[i:i+2] for i in range(len(command))])
        self.assertNotIn('/mnt', command)
        self.assertNotIn('/run/secrets', command)
        self.assertNotIn('/etc/shadow', command)
        self.assertNotIn(['--ro-bind', '/etc', '/etc'], [command[i:i+3] for i in range(len(command))])
        self.assertIn('--unshare-pid', command)
        self.assertIn('--unshare-net', command)

    def test_state_inside_project_is_masked_after_project_bind(self):
        nested = Store(self.project / 'custom-state')
        self.addCleanup(nested.close)
        Engine(nested, registry=object())
        command = self.linux_command()
        binding = command.index('--bind')
        mask_positions = [i for i in range(len(command)-1) if command[i:i+2] == ['--tmpfs', str(nested.home)]]
        self.assertTrue(any(position > binding for position in mask_positions))

    def test_private_environment_inside_nested_state_is_restored_without_siblings(self):
        nested = Store(self.project / 'custom-state')
        self.addCleanup(nested.close)
        Engine(nested, registry=object())
        environment = nested.home / 'environments' / 'selected'
        environment.mkdir(parents=True)
        command = self.linux_command(readable=[environment])
        mask = max(i for i in range(len(command)-1) if command[i:i+2] == ['--tmpfs', str(nested.home)])
        grant = max(i for i in range(len(command)-2) if command[i:i+3] == ['--ro-bind', str(environment), str(environment)])
        self.assertLess(mask, grant)
        self.assertNotIn(['--bind', str(nested.home), str(nested.home)], [command[i:i+3] for i in range(len(command))])

    def test_whole_state_or_filesystem_root_grant_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'runtime state'):
            _sandbox_check(['/bin/true'], self.store.home)
        with self.assertRaisesRegex(ValueError, 'runtime state'):
            _sandbox_check(['/bin/true'], Path('/'))

    def test_configured_paths_and_file_symlink_targets_are_protected(self):
        external_state = self.root / 'other-state'
        external_state.mkdir()
        target = self.project / 'ordinary-file'
        target.write_text(CANARY)
        launch = self.root / 'app-key'
        launch.symlink_to(target)
        with patch.dict(os.environ, {'PARALLAX_HOME': str(external_state), 'PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH': str(launch)}):
            command = self.linux_command()
        for path in (launch, target):
            self.assertIn(['--ro-bind', '/dev/null', str(path)], [command[i:i+3] for i in range(len(command))])
        self.assertIn(['--tmpfs', str(external_state)], [command[i:i+2] for i in range(len(command))])


@unittest.skipUnless(sys.platform == 'darwin' or sys.platform.startswith('linux'), 'requires native command sandbox')
class NativeIsolationCanaryTests(unittest.TestCase):
    def test_engine_preserves_managed_candidate_but_hides_sibling_state_and_external_key(self):
        self.assertTrue(execution_capability()['enforced'], 'Native host must enforce command isolation')
        with fixture_directory() as directory:
            folder = Path(directory).resolve()
            store = Store(folder / 'custom-state')
            self.addCleanup(store.close)
            engine = Engine(store, registry=object())
            project = store.home / 'runs' / 'candidate'
            project.mkdir(parents=True)
            (project / 'accepted.txt').write_text('approved project')
            state_secret, app_key, project_key = store.home / 'session-data', folder / 'application-key', project / 'ordinary-key-name'
            secrets = [state_secret, app_key, project_key]
            for path in secrets:
                path.write_text(CANARY)
            register_private_paths(store, files=[app_key, project_key])
            if sys.platform.startswith('linux'):
                unknown_mount_file = folder / 'unregistered-mount-file'
                unknown_mount_file.write_text(CANARY)
                secrets.append(unknown_mount_file)
            code = canary_script(project, secrets)
            command = _sandbox_check([sys.executable, '-c', code], project)
            result = subprocess.run(command, cwd=project, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(project), 'TMPDIR': str(project)}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((project / 'result.txt').read_text(), 'verified')
            self.assertTrue(all(path.read_text() == CANARY for path in secrets), 'Host private files changed')

    def test_api_command_uses_same_private_state_and_file_policy(self):
        self.assertTrue(execution_capability()['enforced'], 'Native host must enforce command isolation')
        with fixture_directory() as directory:
            folder = Path(directory).resolve()
            agent = ApiAgent(folder / 'api-private-state')
            agent.home.mkdir()
            project = folder / 'project'
            project.mkdir()
            (project / 'accepted.txt').write_text('approved project')
            secrets = [agent.home / 'journal', folder / 'server-key']
            for path in secrets:
                path.write_text(CANARY)
            register_private_paths(agent, files=[secrets[1]])
            script = project / 'test_canary.py'
            script.write_text(canary_script(project, secrets))
            result = asyncio.run(agent._tool(project, 'run_command', {'argv': [sys.executable, '-B', str(script)]}, 'edit', ['result.txt'], None, None))
            self.assertTrue(result['ok'], result)
            self.assertEqual((project / 'result.txt').read_text(), 'verified')
            self.assertTrue(all(path.read_text() == CANARY for path in secrets), 'Host private files changed')
