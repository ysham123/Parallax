#!/usr/bin/env python3
"""Build a small portable remote-MCP plugin ZIP. Credentials never belong here."""
from __future__ import annotations
import argparse
import json
import ipaddress
from pathlib import Path
import sys
from urllib.parse import urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_files import release_files

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGIN = "https://parallax.yosefshammout.com"


def public_url(value: str, *, origin=False) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    try:
        private_address = not ipaddress.ip_address(host).is_global
    except ValueError:
        private_address = False
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment
            or private_address or host in {"localhost", "example.com"} or host.endswith((".localhost", ".example", ".invalid", ".example.com"))
            or any(c.isspace() for c in value) or "\\" in value
            or (origin and (parsed.path not in {"", "/"} or parsed.query))):
        raise ValueError("Use a public HTTPS URL without credentials; the service origin cannot contain a path or query")
    return value.rstrip("/") if origin else value


def package_files(*, root=ROOT, origin=DEFAULT_ORIGIN, demo_recording_url=None, draft=False):
    origin = public_url(origin, origin=True)
    if not draft and not demo_recording_url:
        raise ValueError("A submission package needs --demo-recording-url. Use --draft for local review before recording.")
    if demo_recording_url:
        demo_recording_url = public_url(demo_recording_url)
    # Reuse release-file safety checks and copy only these explicit public inputs.
    safe = {p.relative_to(root).as_posix():p for p in release_files(root)}
    source_manifest = json.loads(safe["plugin.json"].read_text())
    cases = json.loads(safe["openai/review-cases.json"].read_text())
    if len(cases.get("positive", [])) != 5 or len(cases.get("negative", [])) != 3:
        raise ValueError("Review needs five positive and three negative cases")
    for kind, rows in cases.items():
        for row in rows:
            required = {"description", "prompt", "tools_triggered", "expected_behavior"} if kind == "positive" else {"description", "prompt"}
            if not all(isinstance(row.get(field), str) and row[field] for field in required):
                raise ValueError("Incomplete review case")
    review = {"test_cases":cases, "commerce":False}
    if demo_recording_url:
        review["demo_recording_url"] = demo_recording_url
    manifest = {"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name":"parallax-team",
        "version":source_manifest["version"], "description":"Verified coding teams on your paired machines.",
        "author":source_manifest["author"], "homepage":origin,"repository":source_manifest["repository"], "license":"MIT",
        "extensions":{"com.openai":{
            "interface":{"displayName":"Parallax Team", "shortDescription":"Verified coding teams.",
                "longDescription":"Connect your Parallax account to review projects and run verified builds on your paired machines. Choose your coding providers and approved projects locally. Inspect progress, verification results and recent runs, or stop a run. Reviews and builds use your providers' quota. Requires an online worker; personal workspaces have no hosted execution. Builds require independent providers and passing verification gates.",
                "developerName":"Yosef Shammout", "category":"Developer Tools", "capabilities":["Read","Write"],
                "websiteURL":origin,"supportURL":origin+"/support","privacyPolicyURL":origin+"/privacy","termsOfServiceURL":origin+"/terms",
                "logo":"./assets/parallax-icon.svg","composerIcon":"./assets/parallax-icon.svg",
                "defaultPrompt":["Show my paired machines and approved projects.", "Review a project using my connected coding providers.", "Check the status of my latest Parallax run."]},
            "onboardingSkill":"./skills/connect-parallax/SKILL.md", "review":review,
            "publication":{"release_notes":"Account-authorized remote MCP tools, OAuth consent, revocable connections, and paired-machine reviews and builds."}}}}
    mcp = {"$schema":"https://agent-plugins.org/schemas/1.0.0/mcp.schema.json", "mcpServers":{"parallax":{"type":"streamable-http","url":origin+"/api/mcp"}}}
    files = {"plugin.json":(json.dumps(manifest, indent=2)+"\n").encode(), "mcp.json":(json.dumps(mcp, indent=2)+"\n").encode()}
    for target, source in {"assets/parallax-icon.svg":"assets/parallax-icon.svg", "LICENSE":"LICENSE", "README.md":"openai/README.md",
                           "skills/connect-parallax/SKILL.md":"openai/skills/connect-parallax/SKILL.md"}.items():
        files[target] = safe[source].read_bytes()
    return files


def build(out: Path, **kwargs):
    files = package_files(**kwargs)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT/"dist/parallax-team-openai.zip")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--demo-recording-url")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    try:
        files = build(args.out, origin=args.origin, demo_recording_url=args.demo_recording_url, draft=args.draft)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Built {args.out}: {len(files)} files. " + ("Draft only; recording and live review checks remain." if args.draft else "Complete live review checks before submission."))


if __name__ == "__main__":
    main()
