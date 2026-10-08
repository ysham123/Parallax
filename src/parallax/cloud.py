"""Railway entry point. Local CLI startup remains loopback only."""
from pathlib import Path
import fcntl
import os
import uvicorn
import json
from .deployment import Deployment, HOSTED_SECRETS
from .server import create_app
from .store import state_directory

def main():
    deployment = Deployment.from_env()
    # Configuration is held in memory; no provider CLI, project check, or Git process inherits these values.
    for name in HOSTED_SECRETS:
        os.environ.pop(name, None)
    state = state_directory()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    deployment.projects.mkdir(parents=True, exist_ok=True)
    workspace = os.environ.get("PARALLAX_WORKSPACE") or str(deployment.projects)
    deployment.check_workspace(workspace)
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    # One process owns SQLite, subprocess management and recovery.
    with (state / "runtime.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps({"parallax": "hosted runtime", "github_sign_in": bool(deployment.github_redirect),
                          "public_origin": deployment.public_origin, "signup": deployment.signup,
                          "operator_accounts": len(deployment.owner_github_ids), "max_accounts": deployment.max_accounts}), flush=True)
        uvicorn.run(create_app(token=deployment.token, workspace=workspace, deployment=deployment),
                    host="0.0.0.0", port=port, workers=1, access_log=False,
                    proxy_headers=False, timeout_graceful_shutdown=10)

if __name__ == "__main__":
    main()
