"""Synthetic canaries for the policy produced by actual native adapters.

No model requests or user authentication files are read. The native Codex
sandbox test uses a new HOME/CODEX_HOME and only a loopback HTTP listener.
"""
import http.server
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from parallax.isolation import native_scopes, register_private_paths
from parallax.providers import ProviderRegistry, _supported_native_version


class Owner:
    pass


class NativeBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='parallax-native-canaries-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.state = self.root / 'private-state'
        self.workspace = self.state / 'candidate'
        self.workspace.mkdir(parents=True)
        (self.workspace / '.parallax-owned').write_text('synthetic')
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.owner = Owner()
        self.key = self.workspace / 'private-key'
        self.key.write_text('SYNTHETIC_REGISTERED_KEY')
        register_private_paths(self.owner, state=[self.state], files=[self.key])
        self.registry = ProviderRegistry(home=self.home)
        self.registry.codex_home = self.home / '.codex'
        self.registry.codex_home.mkdir()
        self.registry._help = {'codex': '--config --sandbox --strict-config',
                               'claude': '--safe-mode --restricted --strict-mcp-config --permission-prompts --tools --settings'}

    def codex_command(self, mode='consult', executable='codex'):
        return self.registry._command('codex', executable, self.workspace, 'synthetic task',
                                      {'model': 'synthetic', 'effort': None}, mode, None,
                                      10, None, self.scratch, {})

    def test_environment_is_allowlisted_for_metadata_and_run(self):
        secrets = {'PARALLAX_SYNTHETIC_HOST_TOKEN': 'SYNTHETIC_SECRET', 'SSH_AUTH_SOCK': '/synthetic/agent',
                   'AWS_SESSION_TOKEN': 'SYNTHETIC_AWS', 'PYTHONPATH': '/synthetic/injection',
                   'NODE_OPTIONS': '--require /synthetic/injection', 'HTTPS_PROXY': 'https://synthetic:password@example.invalid'}
        with patch.dict(os.environ, secrets):
            _, _, env, _ = self.codex_command()
            metadata = self.registry._environment()
        for key in secrets:
            self.assertNotIn(key, env)
            self.assertNotIn(key, metadata)
        self.assertEqual(env['HOME'], str(self.home))
        self.assertEqual(env['CODEX_HOME'], str(self.registry.codex_home))

    @unittest.skipUnless(os.name == 'posix', 'login names are passed through on POSIX only')
    def test_plain_login_name_passes_through_for_native_sign_in_lookup(self):
        with patch.dict(os.environ, {'USER': 'synthetic.user', 'LOGNAME': 'synthetic.user'}):
            self.assertEqual(self.registry._environment()['USER'], 'synthetic.user')
            self.assertEqual(self.codex_command()[2]['LOGNAME'], 'synthetic.user')
        with patch.dict(os.environ, {'USER': 'x; rm -rf /', 'LOGNAME': 'a\nb'}):
            self.assertNotIn('USER', self.registry._environment())
            self.assertNotIn('LOGNAME', self.registry._environment())

    def test_generated_profile_denies_root_and_retains_narrow_candidate(self):
        argv, _, _, _ = self.codex_command()
        settings = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '-c']
        policy = tomllib.loads(next(item for item in settings if item.startswith('permissions.parallax=')))['permissions']['parallax']
        self.assertEqual(policy['filesystem'][':root'], 'deny')
        self.assertEqual(policy['filesystem'][str(self.state)], 'deny')
        self.assertEqual(policy['filesystem'][str(self.workspace)], 'read')
        self.assertEqual(policy['filesystem'][str(self.key)], 'deny')
        self.assertFalse(policy['network']['enabled'])
        shell = tomllib.loads(next(item for item in settings if item.startswith('shell_environment_policy=')))['shell_environment_policy']
        self.assertEqual(shell['inherit'], 'none')
        self.assertNotIn('--sandbox', argv)
        self.assertIn('--strict-config', argv)
        self.assertIn('features.view_image=false', settings)

    def test_complete_state_grant_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'complete runtime state'):
            native_scopes(self.state)

    def test_native_grants_do_not_interpret_literal_paths_as_globs(self):
        candidate = self.root / 'candidate[1]'
        candidate.mkdir()
        with self.assertRaisesRegex(ValueError, 'glob metacharacters'):
            native_scopes(candidate)

    def test_unsupported_codex_flags_fail_before_launch(self):
        self.registry._help['codex'] = '--config --sandbox'
        with self.assertRaisesRegex(ValueError, 'cannot enforce'):
            self.codex_command()

    def test_unknown_and_older_native_versions_are_not_supported(self):
        for provider, version in [('codex', '0.161.0'), ('codex', 'unknown'),
                                  ('claude', '2.1.294'), ('claude', '3.0.0'),
                                  ('antigravity', '1.2.0'), ('grok', '1.0.50')]:
            self.assertFalse(_supported_native_version(provider, version), (provider, version))
        self.assertTrue(_supported_native_version('codex', 'codex-cli 0.162.1'))
        self.assertTrue(_supported_native_version('claude', '2.1.295 (Claude Code)'))

    def test_antigravity_adapter_generated_gate_denies_private_paths_and_search(self):
        with self.registry._customizations('antigravity', self.workspace, self.scratch, 'edit') as customization:
            hooks = json.loads((self.workspace / '.agents/hooks.json').read_text())
            command = shlex.split(hooks['parallax-gate']['PreToolUse'][0]['hooks'][0]['command'])
            def decision(name, args):
                result = subprocess.run(command, input=json.dumps({'toolCall': {'name': name, 'args': args}}),
                                        text=True, capture_output=True, timeout=10, env=self.registry._environment())
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)['decision']
            self.assertEqual(decision('view_file', {'AbsolutePath': str(self.workspace / 'app.py')}), 'allow')
            for target in (self.home / '.codex/auth.json', self.state / 'sibling', self.key,
                           self.workspace / '.ENV.local', self.workspace / 'nested/.ssh/id_rsa'):
                self.assertEqual(decision('view_file', {'AbsolutePath': str(target)}), 'deny', str(target))
            (self.workspace / 'alias').symlink_to(self.key)
            self.assertEqual(decision('view_file', {'AbsolutePath': str(self.workspace / 'alias')}), 'deny')
            self.assertEqual(decision('grep_search', {'SearchPath': str(self.workspace), 'Query': 'TOKEN'}), 'deny')
            self.assertEqual(decision('write_to_file', {'TargetFile': str(self.key)}), 'deny')
            self.assertGreater(len(customization['gate_audit'].read_text().splitlines()), 5)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('codex'), 'Installed native Codex sandbox required')
    def test_actual_codex_sandbox_uses_adapter_profile_for_negative_canaries(self):
        executable = shutil.which('codex')
        argv, _, env, _ = self.codex_command(executable=executable)
        overrides = []
        for i, arg in enumerate(argv[:-1]):
            if arg == '-c':
                overrides.extend(['-c', argv[i + 1]])
        visible = self.workspace / 'app.py'
        visible.write_text('VISIBLE_CANDIDATE')
        sibling = self.state / 'sibling'
        sibling.write_text('SYNTHETIC_SIBLING_SECRET')
        credential = self.registry.codex_home / 'auth.json'
        credential.write_text('SYNTHETIC_PROVIDER_CREDENTIAL')
        (self.workspace / 'alias').symlink_to(sibling)
        nested = self.workspace / 'nested'
        nested.mkdir()
        (nested / '.ENV.local').write_text('SYNTHETIC_ENV_SECRET')
        class Handler(http.server.BaseHTTPRequestHandler):
            requests = 0
            def do_GET(self):
                type(self).requests += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'SYNTHETIC_NETWORK')
            def log_message(self, *_):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        # Each command exits success only when its attempted secret read fails.
        script = 'cat app.py; for p in "$@"; do if cat "$p"; then exit 91; fi; done; if touch forbidden-write; then exit 92; fi; if /usr/bin/curl -fsS --max-time 2 "$CANARY_URL"; then exit 93; fi; test -z "$PARALLAX_SYNTHETIC_HOST_TOKEN"'
        env['CANARY_URL'] = 'http://127.0.0.1:' + str(server.server_port)
        result = subprocess.run([executable, 'sandbox', *overrides, '-P', 'parallax', '-C', str(self.workspace),
                                 '--', '/bin/sh', '-c', script, 'canary', str(sibling), str(credential),
                                 str(self.key), str(nested / '.ENV.local'), str(self.workspace / 'alias')],
                                env=env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'VISIBLE_CANDIDATE')
        self.assertFalse((self.workspace / 'forbidden-write').exists())
        self.assertEqual(Handler.requests, 0)
        edited, _, edit_env, _ = self.codex_command('edit', executable)
        edit_overrides = []
        for i, arg in enumerate(edited[:-1]):
            if arg == '-c':
                edit_overrides.extend(['-c', edited[i + 1]])
        edit_script = 'printf EDITED > allowed-write; if cat "$1"; then exit 91; fi'
        result = subprocess.run([executable, 'sandbox', *edit_overrides, '-P', 'parallax', '-C', str(self.workspace),
                                 '--', '/bin/sh', '-c', edit_script, 'canary', str(sibling)],
                                env=edit_env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.workspace / 'allowed-write').read_text(), 'EDITED')
        self.assertEqual(result.stdout, '')

    @unittest.skipUnless(os.name == 'posix' and shutil.which('codex'), 'Installed native Codex required')
    def test_actual_exec_strict_config_is_validated_before_empty_prompt(self):
        argv, _, env, _ = self.codex_command(executable=shutil.which('codex'))
        # No prompt or real authentication is supplied: the process must stop
        # before inference. This uses exec because sandbox rejects strict-config.
        result = subprocess.run(argv, input='', env=env, text=True, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('unknown configuration field', result.stderr)
        self.assertIn('No prompt provided', result.stderr)
        rejected = subprocess.run([*argv[:-1], '-c', 'parallax_unknown_canary=false', argv[-1]],
                                  input='', env=env, text=True, capture_output=True, timeout=20)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('unknown configuration field', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
