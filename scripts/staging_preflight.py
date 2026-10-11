"""Read-only staged configuration check. Never prints configuration values.

Run inside the intended runtime environment, with secrets already provided by
the platform. A passing result verifies configuration shape only, not launch
readiness. This script creates no state, infrastructure or GitHub requests.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from parallax.deployment import Deployment


def assess(*, delivery=False, pilot=False):
    checks = []

    def check(name, ok, guidance):
        checks.append({"check": name, "ok": bool(ok), "guidance": None if ok else guidance})

    required = ("PARALLAX_ACCESS_TOKEN", "PARALLAX_STUDIO_ORIGINS", "PARALLAX_ALLOWED_HOSTS",
                "PARALLAX_PUBLIC_ORIGIN", "PARALLAX_HOME", "PARALLAX_PROJECTS_ROOT")
    for name in required:
        check(name + " present", os.environ.get(name), "Configure " + name + " on the staging relay.")
    deployment = None
    try:
        deployment = Deployment.from_env()
        check("Runtime configuration accepted", True, "")
    except (ValueError, OSError):
        # Refuse to render exception text: future validators might include a
        # supplied value. Operators inspect the documented names, never secrets.
        check("Runtime configuration accepted", False, "Check token strength, exact HTTPS origins/hosts, sign-in credentials and account settings in docs/DEPLOYMENT.md.")
    if deployment:
        public_host = urlsplit(deployment.public_origin or "").hostname
        check("Studio hostname allowed", public_host in deployment.hosts, "Include the exact Studio hostname in PARALLAX_ALLOWED_HOSTS.")
        check("Individual sign-in configured", deployment.github or deployment.supabase, "Configure staging Supabase or built-in GitHub sign-in, independently of delivery authorization.")
        check("Staging enrollment restricted", deployment.signup == "allowlist", "Set PARALLAX_SIGNUP=allowlist.")
        admitted = deployment.allowed_emails if deployment.supabase else deployment.allowed_github_ids
        check("Two designated test accounts admitted", len(admitted) >= 2, "Admit at least two distinct designated test accounts to exercise isolation and peer approval.")
    home = Path(os.environ.get("PARALLAX_HOME", "/data/parallax")).expanduser().resolve()
    projects = Path(os.environ.get("PARALLAX_PROJECTS_ROOT", "/data/projects")).expanduser().resolve()
    check("State and approved project roots separate", home != projects and not home.is_relative_to(projects) and not projects.is_relative_to(home),
          "Use separate state and project directories, such as /data/parallax and /data/projects.")
    desired_gate = "on" if pilot else "off"
    check("Pilot gate explicitly " + desired_gate, os.environ.get("PARALLAX_PILOT_ENABLED", "off") == desired_gate,
          "Set PARALLAX_PILOT_ENABLED=" + desired_gate + " only for this staging acceptance phase.")
    runtime = os.environ.get("PARALLAX_RUNTIME_URL")
    if runtime:
        parsed = urlsplit(runtime)
        check("Studio build relay origin valid", parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment,
              "Use an exact public HTTPS relay origin for PARALLAX_RUNTIME_URL; this belongs on the Studio build.")
    if delivery:
        names = ("ID", "PRIVATE_KEY_PATH", "CLIENT_ID", "CLIENT_SECRET", "WEBHOOK_SECRET", "SLUG")
        for suffix in names:
            name = "PARALLAX_GITHUB_APP_" + suffix
            check(name + " present", os.environ.get(name), "Configure " + name + " only on the relay.")
        check("GitHub App numeric identity", re.fullmatch(r"[1-9][0-9]*", os.environ.get("PARALLAX_GITHUB_APP_ID", "")), "Set the registered GitHub App ID.")
        check("GitHub App slug shape", re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,99}", os.environ.get("PARALLAX_GITHUB_APP_SLUG", "")), "Set the registered GitHub App slug.")
        check("GitHub App OAuth client identity", re.fullmatch(r"[a-zA-Z0-9._-]{8,100}", os.environ.get("PARALLAX_GITHUB_APP_CLIENT_ID", "")), "Set the delivery App client ID, independently of the sign-in client.")
        for suffix in ("CLIENT_SECRET", "WEBHOOK_SECRET"):
            value = os.environ.get("PARALLAX_GITHUB_APP_" + suffix, "")
            check("GitHub App " + suffix.lower() + " shape", len(value) >= 20 and value.isascii() and value.isprintable() and " " not in value,
                  "Provide the private App client secret and a separate random webhook secret through platform secrets.")
        value = os.environ.get("PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH", "")
        key = Path(value).expanduser().resolve() if value else None
        root = Path(__file__).resolve().parents[1]
        safe = bool(key and Path(value).expanduser().is_absolute() and not key.is_relative_to(projects) and not key.is_relative_to(root))
        check("GitHub App key outside repository and projects", safe, "Mount the App private key outside source and approved project roots, for example under /run/secrets.")
        private = False
        try:
            private = bool(safe and key.is_file() and stat.S_IMODE(key.stat().st_mode) & 0o077 == 0)
        except OSError:
            pass
        check("GitHub App key readable with private permissions", private and os.access(key, os.R_OK) if key else False,
              "Mount a readable regular key file with mode 0600 or stricter.")
        valid_key = False
        if private:
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import rsa
                parsed_key = serialization.load_pem_private_key(key.read_bytes(), password=None)
                valid_key = isinstance(parsed_key, rsa.RSAPrivateKey) and parsed_key.key_size >= 2048
            except (OSError, ValueError, TypeError):
                pass
        check("GitHub App signing key usable", valid_key, "Mount the unencrypted RSA private key issued for this GitHub App; key data is never printed.")
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "scope": "Configuration only; no authentication, inference, deployment, repository binding or publication exercised."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", action="store_true", help="Also require GitHub App configuration and a safe signing-key mount.")
    parser.add_argument("--pilot", action="store_true", help="Require the pilot gate on for the later pilot acceptance phase.")
    options = parser.parse_args()
    try:
        result = assess(delivery=options.delivery, pilot=options.pilot)
    except (ValueError, OSError):
        result = {"ok": False, "checks": [{"check": "Configuration paths and origins parse safely", "ok": False,
                  "guidance": "Correct malformed paths or URLs in the staging configuration; supplied values are not rendered."}],
                  "scope": "Configuration only; no external action exercised."}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
