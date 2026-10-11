"""Docker smoke cleanup must release only recorded owned resources."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_container.py"
spec = importlib.util.spec_from_file_location("smoke_container", path)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ContainerCleanupTests(unittest.TestCase):
    def test_stop_retains_ownership_until_explicit_removal_releases_volume(self):
        resources = smoke.DockerResources()
        mounted = {"owned-container"}
        operations = []

        def docker(arguments, **options):
            operations.append(arguments)
            self.assertTrue(options["check"])
            self.assertEqual(options["timeout"], 30)
            if arguments[1] == "stop":
                # A completed stop leaves the volume attached until removal.
                self.assertEqual(resources.containers, ["owned-container"])
                self.assertEqual(mounted, {"owned-container"})
            elif arguments[1] == "rm":
                self.assertEqual(resources.containers, ["owned-container"])
                mounted.remove(arguments[-1])
            elif arguments[1:3] == ["volume", "rm"]:
                self.assertFalse(mounted, "The volume is still attached")
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(smoke.subprocess, "run", side_effect=docker), patch.object(
            smoke.subprocess, "check_output", return_value="owned-container\n"
        ) as create:
            resources.create_volume("owned-volume")
            container = resources.create_container(["--mount", "type=volume,source=owned-volume,target=/data", "test-image"])
            self.assertNotIn("--rm", create.call_args.args[0])
            resources.stop_container(container)
            self.assertEqual(resources.containers, [])
            resources.cleanup()

        self.assertEqual(operations[-3:], [
            ["docker", "stop", "owned-container"],
            ["docker", "rm", "owned-container"],
            ["docker", "volume", "rm", "owned-volume"],
        ])

    def test_stop_failure_is_preserved_and_owned_container_can_be_force_cleaned(self):
        resources = smoke.DockerResources()
        resources.containers = ["owned-container"]
        resources.volumes = ["owned-volume"]
        failure = subprocess.CalledProcessError(1, ["docker", "stop", "owned-container"])
        with patch.object(smoke.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                resources.stop_container("owned-container")
        self.assertIs(caught.exception, failure)
        self.assertEqual(resources.containers, ["owned-container"])
        with patch.object(smoke.subprocess, "run") as run:
            resources.cleanup()
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["docker", "rm", "--force", "owned-container"],
            ["docker", "volume", "rm", "owned-volume"],
        ])
        self.assertEqual(resources.containers, [])
        self.assertEqual(resources.volumes, [])

    def test_failed_explicit_removal_retains_id_for_final_cleanup(self):
        resources = smoke.DockerResources()
        resources.containers = ["owned-container"]
        failure = subprocess.TimeoutExpired(["docker", "rm", "owned-container"], 30)
        with patch.object(smoke.subprocess, "run", side_effect=[None, failure]):
            with self.assertRaises(subprocess.TimeoutExpired):
                resources.stop_container("owned-container")
        self.assertEqual(resources.containers, ["owned-container"])
        with patch.object(smoke.subprocess, "run") as run:
            resources.cleanup()
        run.assert_called_once_with(["docker", "rm", "--force", "owned-container"],
                                    check=True, stdout=subprocess.DEVNULL, timeout=30)

    def test_cleanup_reports_failures_and_still_attempts_other_owned_resources(self):
        resources = smoke.DockerResources()
        resources.containers = ["owned-first", "owned-second"]
        resources.volumes = ["owned-volume"]
        failure = subprocess.CalledProcessError(1, ["docker", "rm", "--force", "owned-second"])
        with patch.object(smoke.subprocess, "run", side_effect=[failure, None, None]) as run:
            with self.assertRaisesRegex(RuntimeError, "Docker smoke cleanup failed") as caught:
                resources.cleanup()
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(resources.containers, ["owned-second"])
        self.assertEqual(resources.volumes, [])
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["docker", "rm", "--force", "owned-second"],
            ["docker", "rm", "--force", "owned-first"],
            ["docker", "volume", "rm", "owned-volume"],
        ])

    def test_unowned_container_is_refused_without_a_docker_command(self):
        resources = smoke.DockerResources()
        resources.containers = ["owned-container"]
        with patch.object(smoke.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "not owned"):
                resources.stop_container("unrelated-container")
            with self.assertRaisesRegex(ValueError, "not owned"):
                resources.remove_container("unrelated-container", force=True)
        run.assert_not_called()

    def test_failed_start_is_not_hidden_and_main_cleans_created_container(self):
        operations = []
        failure = subprocess.CalledProcessError(1, ["docker", "start", "owned-container"])

        def docker(arguments, **options):
            operations.append(arguments)
            if arguments[1] == "start":
                raise failure
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(smoke.subprocess, "run", side_effect=docker), patch.object(
            smoke.subprocess, "check_output", return_value="owned-container\n"
        ), patch.object(smoke.secrets, "token_hex", return_value="unique-fixture"), patch(
            "sys.argv", ["smoke_container.py"]
        ):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                smoke.main()
        self.assertIs(caught.exception, failure)
        self.assertEqual(operations, [
            ["docker", "volume", "create", "parallax-smoke-unique-fixture"],
            ["docker", "start", "owned-container"],
            ["docker", "stop", "owned-container"],
            ["docker", "rm", "owned-container"],
            ["docker", "volume", "rm", "parallax-smoke-unique-fixture"],
        ])

    def test_failed_cold_copy_keeps_ownership_and_propagates_failure_after_cleanup(self):
        operations = []
        identifiers = iter(["owned-runtime-first", "owned-runtime-second", "owned-copy"])
        failure = subprocess.CalledProcessError(23, ["docker", "start", "--attach", "owned-copy"])
        principal = {"workspace": {"kind": "operator"}}
        cookie_headers = {"Set-Cookie": "session=synthetic-cookie; Secure; HttpOnly; SameSite=strict"}
        responses = iter([
            (200, {"ok": True}, {}), (401, {}, {}), (200, [], {}),
            (200, {"ok": True}, {}), (403, {}, {}), (403, {}, {}),
            (403, {}, {}), (503, {}, {}), (200, {"configured": False}, {}),
            (200, {}, cookie_headers), (200, principal, {}), (403, {}, {}),
            (200, {"code": "fixture-pair"}, {}),
            (200, {"token": "fixture-worker", "id": "fixture-id"}, {}),
            (200, {}, {}), (401, {}, {}), (200, {"ok": True}, {}),
            (200, principal, {}), (200, {}, {}),
            (200, [{"id": "fixture-id"}], {}), (200, {}, {}),
            (200, {}, {}), (200, {}, cookie_headers),
        ])

        def http(*arguments, **options):
            code, payload, headers = next(responses)
            response = io.BytesIO(json.dumps(payload).encode())
            response.code = code
            response.headers = headers
            return response

        def output(arguments, **options):
            if arguments[1] == "create":
                self.assertNotIn("--rm", arguments)
                return next(identifiers) + "\n"
            self.assertEqual(arguments[1], "port")
            return "127.0.0.1:12345\n"

        def docker(arguments, **options):
            operations.append(arguments)
            if arguments == failure.cmd:
                raise failure
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(smoke.subprocess, "run", side_effect=docker), patch.object(
            smoke.subprocess, "check_output", side_effect=output
        ), patch.object(smoke.urllib.request, "urlopen", side_effect=http), patch.object(
            smoke.secrets, "token_hex", return_value="unique-fixture"
        ), patch("sys.argv", ["smoke_container.py", "--restore"]):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                smoke.main()
        self.assertIs(caught.exception, failure)
        self.assertEqual(operations[-4:], [
            ["docker", "start", "--attach", "owned-copy"],
            ["docker", "rm", "--force", "owned-copy"],
            ["docker", "volume", "rm", "parallax-smoke-unique-fixture-restored"],
            ["docker", "volume", "rm", "parallax-smoke-unique-fixture"],
        ])


if __name__ == "__main__":
    unittest.main()
