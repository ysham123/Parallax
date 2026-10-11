"""Disposable Docker checks; no provider credentials, inference or remote writes."""
from http.cookies import SimpleCookie
import argparse
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.request


class DockerResources:
    """Track only this smoke run's resources until explicit removal succeeds."""

    def __init__(self):
        self.containers = []
        self.volumes = []

    def create_volume(self, name):
        subprocess.run(["docker", "volume", "create", name], check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
        self.volumes.append(name)

    def create_container(self, arguments):
        container = subprocess.check_output(["docker", "create", *arguments],
                                            text=True, timeout=30).strip()
        self.containers.append(container)
        return container

    def remove_container(self, container, *, force=False):
        if container not in self.containers:
            raise ValueError("Container is not owned by this smoke run")
        arguments = ["docker", "rm"]
        if force:
            arguments.append("--force")
        subprocess.run([*arguments, container], check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
        self.containers.remove(container)

    def stop_container(self, container):
        if container not in self.containers:
            raise ValueError("Container is not owned by this smoke run")
        subprocess.run(["docker", "stop", container], check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
        # Auto-removal after `docker stop` is asynchronous. Keep ownership
        # until this explicit removal has released the volume attachment.
        self.remove_container(container)

    def cleanup(self):
        failures = []
        for container in reversed(self.containers[:]):
            try:
                self.remove_container(container, force=True)
            except (OSError, subprocess.SubprocessError) as error:
                failures.append(error)
        for volume in reversed(self.volumes[:]):
            try:
                subprocess.run(["docker", "volume", "rm", volume], check=True,
                               stdout=subprocess.DEVNULL, timeout=30)
                self.volumes.remove(volume)
            except (OSError, subprocess.SubprocessError) as error:
                failures.append(error)
        if failures:
            raise RuntimeError("Docker smoke cleanup failed: " + "; ".join(str(error) for error in failures)) from failures[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="parallax-runtime", help="Image to test; a unique audit tag avoids replacing another user's image.")
    parser.add_argument("--restore", action="store_true", help="Cold-copy fixture data to a new volume before the final replacement.")
    options = parser.parse_args()
    image = options.image
    token = secrets.token_urlsafe(48)
    volume = "parallax-smoke-" + secrets.token_hex(8)
    resources = DockerResources()
    container = None
    origin = "https://studio.example.com"
    admin = {"Authorization": "Bearer " + token}
    url = ""

    def request(path, *, method="GET", headers=None, body=None, status=200):
        supplied = dict(headers or {})
        data = None
        if body is not None:
            supplied["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url + path, data=data, headers=supplied, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            assert response.code == status, f"{method} {path}: expected {status}, got {response.code}"
            payload = response.read()
            return (json.loads(payload) if payload else None), response.headers

    def start():
        nonlocal container, url
        container = resources.create_container([
            "-p", "127.0.0.1::8080",
            "--mount", f"type=volume,source={volume},target=/data",
            "-e", "PARALLAX_ACCESS_TOKEN=" + token,
            "-e", "PARALLAX_STUDIO_ORIGINS=" + origin,
            "-e", "PARALLAX_ALLOWED_HOSTS=runtime.example.com", image,
        ])
        subprocess.run(["docker", "start", container], check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
        address = subprocess.check_output(["docker", "port", container, "8080"], text=True).strip()
        url = "http://" + address
        for _ in range(100):
            try:
                health, _ = request("/api/health")
                assert health["ok"]
                return
            except (OSError, urllib.error.URLError):
                time.sleep(.2)
        raise RuntimeError("Container did not become healthy")

    def stop():
        nonlocal container
        if container:
            resources.stop_container(container)
            container = None

    resources.create_volume(volume)
    try:
        start()
        request("/api/runs", status=401)
        runs, _ = request("/api/runs", headers=admin)
        assert runs == []
        request("/api/health", headers={"Host": "healthcheck.railway.app"})
        request("/api/runs", headers={**admin, "Host": "healthcheck.railway.app"}, status=403)
        request("/api/runs", headers={**admin, "Host": "attacker.example.com"}, status=403)
        request("/api/runs", headers={**admin, "Origin": "https://attacker.example.com"}, status=403)
        request("/api/workspaces", method="POST", headers=admin, body={"name": "Closed pilot"}, status=503)
        delivery, _ = request("/api/github/config", headers=admin)
        assert not delivery["configured"]

        _, headers = request("/api/session", method="POST", headers={"Origin": origin}, body={"token": token})
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        morsel = next(iter(cookie.values()))
        assert morsel["secure"] and morsel["httponly"] and morsel["samesite"] == "strict"
        assert token not in headers["Set-Cookie"]
        # Docker exposes only loopback HTTP. Explicitly carry the Secure cookie to
        # exercise its server-side record; a browser must use HTTPS in staging.
        session = {"Cookie": f"{morsel.key}={morsel.value}"}
        principal, _ = request("/api/session", headers=session)
        assert principal["workspace"]["kind"] == "operator"
        request("/api/session", method="DELETE", headers=session, status=403)

        pair, _ = request("/api/executors/pair", method="POST", headers=admin)
        legacy, _ = request("/api/worker/connect", method="POST", body={
            "code": pair["code"], "name": "Disposable smoke worker",
            "platform": "linux", "workspaces": ["/data/projects"],
        })
        worker = {"Authorization": "Bearer " + legacy["token"]}
        request("/api/worker/next", headers=worker)
        request("/api/executors", headers=worker, status=401)
        # Replace the container, preserving only the mounted data, rather than
        # restarting one process whose writable image layer could hide a bug.
        stop()
        start()
        principal, _ = request("/api/session", headers=session)
        assert principal["workspace"]["kind"] == "operator"
        request("/api/worker/next", headers=worker)
        machines, _ = request("/api/executors", headers=admin)
        assert [machine["id"] for machine in machines] == [legacy["id"]]
        request("/api/executors/" + legacy["id"], method="DELETE", headers=admin)
        request("/api/session", method="DELETE", headers={**session, "Origin": origin})
        # Retain one active session as well as the signed-out session and
        # revoked worker, so restore checks both positive and negative state.
        _, active_headers = request("/api/session", method="POST", headers={"Origin": origin}, body={"token": token})
        active_cookie = SimpleCookie(); active_cookie.load(active_headers["Set-Cookie"])
        active_morsel = next(iter(active_cookie.values()))
        active_session = {"Cookie": f"{active_morsel.key}={active_morsel.value}"}
        stop()
        if options.restore:
            restored = volume + "-restored"
            resources.create_volume(restored)
            # The source process is stopped. Copy the entire private data tree,
            # including SQLite sidecars, into a different empty volume. Keep
            # the runtime mount path the same; saved managed paths are absolute.
            copy = """from pathlib import Path
import hashlib, shutil
source, target = Path('/source'), Path('/restored')
assert not any(target.iterdir()), 'Restore target must be empty'
for path in source.iterdir():
    if path.is_dir(): shutil.copytree(path, target / path.name, symlinks=True)
    else: shutil.copy2(path, target / path.name)
def manifest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert manifest(source) and manifest(source) == manifest(target), 'Cold restore bytes differ'
print('Cold fixture volume restored with identical file hashes.')
"""
            copy_container = resources.create_container(["--network", "none", "--entrypoint", "python",
                "--mount", f"type=volume,source={volume},target=/source,readonly",
                "--mount", f"type=volume,source={restored},target=/restored", image, "-c", copy])
            subprocess.run(["docker", "start", "--attach", copy_container], check=True, timeout=60)
            resources.remove_container(copy_container)
            volume = restored
        start()
        request("/api/worker/next", headers=worker, status=401)
        request("/api/session", headers=session, status=401)
        principal, _ = request("/api/session", headers=active_session)
        assert principal["workspace"]["kind"] == "operator"
        print("Container health, origin/host guards, pilot defaults, durable sessions, worker compatibility and revocation passed.")
    finally:
        try:
            stop()
        finally:
            resources.cleanup()


if __name__ == "__main__":
    main()
