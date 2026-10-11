#!/usr/bin/env python3
"""Explicitly notarize an existing Developer ID beta. Never publish downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import uuid

from build_macos import (APP_NAME, BUNDLE_ID, atomic_json, create_dmg, inventory,
                         macho_files, require_identity, run, sha256, explicit_keychain)


def developer_id_details(path: Path, team_id: str, *, executable: bool = False) -> None:
    run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(path)])
    result = subprocess.run(["/usr/bin/codesign", "--display", "--verbose=4", str(path)], check=True, capture_output=True, text=True)
    details = result.stderr
    if "Authority=Developer ID Application: " not in details or "TeamIdentifier=" + team_id not in details:
        raise ValueError("Artifact must be signed with the requested Developer ID Application team")
    if "Timestamp=" not in details or "Signature=adhoc" in details:
        raise ValueError("Developer ID artifact needs a secure timestamp")
    if executable and re.search(r"flags=.*\(.*runtime.*\)", details) is None:
        raise ValueError("Every executable needs the hardened runtime")
    # No broad code-loading exceptions or debug grants are allowed in this beta.
    entitlement = subprocess.run(["/usr/bin/codesign", "--display", "--entitlements", "-", str(path)], check=True, capture_output=True)
    raw = entitlement.stdout
    if raw.strip() and plistlib.loads(raw) != {}:
        raise ValueError("Unexpected signing entitlements")


def validate_inputs(receipt_path: Path, identity: str, team_id: str, keychain: Path | None = None) -> tuple[dict[str, object], Path, Path]:
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("signing") != "developer-id" or receipt.get("team_id") != team_id or receipt.get("published"):
        raise ValueError("Only an unpublished Developer ID build can be notarized")
    app, dmg = Path(receipt["app"]), Path(receipt["dmg"])
    if app.name != APP_NAME or app.is_symlink() or dmg.is_symlink() or not app.is_dir() or not dmg.is_file():
        raise ValueError("Build artifacts are missing or invalid")
    original_inventory = receipt_path.parent / "bundle-inventory.json"
    if original_inventory.is_symlink() or sha256(original_inventory) != receipt.get("bundle_inventory_sha256"):
        raise ValueError("Original bundle inventory does not match the build receipt")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleShortVersionString") != receipt["version"]:
        raise ValueError("Build bundle identity does not match its receipt")
    require_identity(identity, team_id, keychain)
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    developer_id_details(app, team_id, executable=True)
    for path in macho_files(app):
        developer_id_details(path, team_id, executable=True)
    developer_id_details(dmg, team_id)
    return receipt, app, dmg


def submit(path: Path, profile: str, journal: dict[str, object], prefix: str, journal_path: Path) -> None:
    existing = journal.get(prefix + "_submission_id")
    if existing:
        result = json.loads(run(["/usr/bin/xcrun", "notarytool", "info", str(existing), "--keychain-profile", profile, "--output-format", "json"]))
        if result.get("status") == "In Progress":
            result = json.loads(run(["/usr/bin/xcrun", "notarytool", "wait", str(existing), "--keychain-profile", profile, "--output-format", "json", "--timeout", "20m"]))
    else:
        # Capture the durable submission ID before waiting. A process interruption
        # during submit may require resubmitting these identical bytes; never rebuild.
        result = json.loads(run(["/usr/bin/xcrun", "notarytool", "submit", str(path), "--keychain-profile", profile, "--output-format", "json"]))
        journal[prefix + "_submission_id"] = result["id"]
        atomic_json(journal_path, journal)
        result = json.loads(run(["/usr/bin/xcrun", "notarytool", "wait", str(result["id"]), "--keychain-profile", profile, "--output-format", "json", "--timeout", "20m"]))
    journal[prefix + "_notary_status"] = result.get("status")
    atomic_json(journal_path, journal)
    if result.get("status") != "Accepted":
        raise ValueError("Apple notarization was not accepted; inspect the recorded submission with notarytool log")


def notarize(args: argparse.Namespace) -> Path:
    request_id = str(uuid.UUID(args.request_id))
    receipt_path = args.build_receipt.resolve()
    receipt = json.loads(receipt_path.read_text())
    # Reject local ad hoc builds before Keychain access or any upload.
    if receipt.get("signing") != "developer-id":
        raise ValueError("An ad hoc review build cannot be notarized or distributed as official")
    directory = receipt_path.parent
    journal_path = directory / ("notarization-" + request_id + ".json")
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {
        "schema_version": 1, "request_id": request_id, "build_receipt_sha256": sha256(receipt_path),
        "team_id": args.team_id, "published": False, "status": "prepared",
    }
    if journal.get("build_receipt_sha256") != sha256(receipt_path) or journal.get("team_id") != args.team_id:
        raise ValueError("Request ID is already bound to a different build or signing team")
    keychain = explicit_keychain(getattr(args, "keychain", None))
    receipt, app, dmg = validate_inputs(receipt_path, args.identity, args.team_id, keychain)
    expected_dmg = journal.get("dmg_stapled_sha256") or journal.get("dmg_submission_sha256") or receipt["dmg_sha256"]
    if sha256(dmg) != expected_dmg:
        raise ValueError("DMG has changed since its durable operation record")
    if journal.get("status") == "complete":
        if journal.get("app_inventory") != inventory(app):
            raise ValueError("Accepted app has changed")
        run(["/usr/bin/xcrun", "stapler", "validate", str(app)])
        run(["/usr/bin/xcrun", "stapler", "validate", str(dmg)])
        return journal_path
    if not journal.get("app_stapled"):
        current_inventory = inventory(app)
        source_inventory = json.loads((directory / "bundle-inventory.json").read_text())
        if current_inventory != source_inventory:
            raise ValueError("App has changed since signing; do not reuse the build receipt")
        app_zip = directory / ("notary-app-" + request_id + ".zip")
        if journal.get("app_zip_sha256"):
            if not app_zip.exists() or sha256(app_zip) != journal["app_zip_sha256"]:
                raise ValueError("Notary submission ZIP has changed")
        else:
            run(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(app_zip)])
            journal["app_zip_sha256"] = sha256(app_zip)
            atomic_json(journal_path, journal)
        submit(app_zip, args.keychain_profile, journal, "app", journal_path)
        run(["/usr/bin/xcrun", "stapler", "staple", str(app)])
        run(["/usr/bin/xcrun", "stapler", "validate", str(app)])
        journal["app_stapled"] = True
        journal["app_inventory"] = inventory(app)
        atomic_json(journal_path, journal)
    elif journal.get("app_inventory") != inventory(app):
        raise ValueError("Stapled app has changed")
    if not journal.get("dmg_submission_sha256"):
        # Include the accepted app ticket in the final image, then sign that image.
        create_dmg(app, dmg, False, args.identity, keychain)
        journal["dmg_submission_sha256"] = sha256(dmg)
        atomic_json(journal_path, journal)
    if not journal.get("dmg_stapled_sha256"):
        submit(dmg, args.keychain_profile, journal, "dmg", journal_path)
        run(["/usr/bin/xcrun", "stapler", "staple", str(dmg)])
        journal["dmg_stapled_sha256"] = sha256(dmg)
        atomic_json(journal_path, journal)
    run(["/usr/bin/xcrun", "stapler", "validate", str(app)])
    run(["/usr/bin/xcrun", "stapler", "validate", str(dmg)])
    run(["/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose=2", str(app)])
    run(["/usr/sbin/spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=2", str(dmg)])
    journal["status"] = "complete"
    journal["notarized"] = True
    journal["fresh_mac_acceptance"] = "unverified"
    journal["live_workflow_acceptance"] = "unverified"
    journal["release_ready"] = False
    journal["published"] = False
    atomic_json(journal_path, journal)
    return journal_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--keychain", type=Path, help="Optional dedicated signing Keychain; unlock it manually")
    parser.add_argument("--keychain-profile", required=True, help="Existing notarytool Keychain profile; never pass passwords")
    parser.add_argument("--request-id", required=True, help="Durable UUID reused on interruption")
    args = parser.parse_args()
    try:
        journal = notarize(args)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        # Don't echo Apple tool output, which may contain account or signing details.
        parser.exit(1, "Notarization refused: " + (str(error) if not isinstance(error, subprocess.CalledProcessError) else "Apple tool failed; inspect its local operation record") + "\n")
    print("Accepted and stapled; unpublished. Operation record: " + str(journal))


if __name__ == "__main__":
    main()
