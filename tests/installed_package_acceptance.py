"""Smoke a fresh installed wheel's CLI, MCP and bundled Studio without inference.

Run: python tests/installed_package_acceptance.py --cli /path/to/venv/bin/parallax
Create the disposable environment and install the hash-locked dependencies and
reviewed local wheel first. This never edits or launches the user's normal state.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def verify(cli, expected):
    cli = cli.resolve()
    assert subprocess.check_output([str(cli), "--version"], text=True).strip() == "Parallax " + expected
    assert "--pair-file" in subprocess.check_output([str(cli), "worker", "--help"], text=True)
    messages = "\n".join(json.dumps(message) for message in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )) + "\n"
    with tempfile.TemporaryDirectory(prefix="parallax-installed-") as temp:
        root = Path(temp)
        state, project = root / "state", root / "project"
        state.mkdir(); project.mkdir()
        env = {**os.environ, "PARALLAX_HOME": str(state), "PYTHONPATH": ""}
        reply = subprocess.run([str(cli), "mcp"], input=messages, capture_output=True, text=True, check=True, env=env, cwd=root)
        responses = [json.loads(line) for line in reply.stdout.splitlines()]
        assert [response["id"] for response in responses] == [1, 2]
        tools = {entry["name"] for entry in responses[1]["result"]["tools"]}
        assert {"parallax_start_run", "parallax_studio", "parallax_get_run", "parallax_get_receipt"} <= tools
        with (root / "server.log").open("w") as log:
            process = subprocess.Popen([str(cli), "serve", "--workspace", str(project)], env=env, cwd=root, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Installed server exited: " + (root / "server.log").read_text())
                    try:
                        endpoint = json.loads((state / "server.json").read_text())
                        def read(path):
                            request = urllib.request.Request(endpoint["url"] + path, headers={"Authorization": "Bearer " + endpoint["token"]})
                            with urllib.request.urlopen(request, timeout=5) as response:
                                return response.read()
                        assert json.loads(read("/api/health"))["version"] == expected
                        break
                    except (OSError, ValueError):
                        time.sleep(.05)
                else:
                    raise RuntimeError("Installed server startup timed out")
                html = read("/").decode()
                assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                assert len(assets) >= 2
                for asset in assets:
                    assert read(asset)
                recipes = json.loads(read("/api/workflow-templates"))
                assert len(recipes) >= 3
                assert (state / "server.json").stat().st_mode & 0o777 == 0o600
                return {"status": "passed", "version": expected, "mcp_tools": len(tools), "wheel_studio_assets": assets,
                        "server_and_recipe_initialization": "passed", "normal_user_state": "untouched", "provider_calls": 0}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--version", default="1.4.0")
    args = parser.parse_args()
    print(json.dumps(verify(args.cli, args.version), indent=2))
