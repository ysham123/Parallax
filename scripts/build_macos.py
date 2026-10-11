#!/usr/bin/env python3
"""Prepare a self-contained macOS beta app and DMG. Never publish or notarize."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import plistlib
import re
import shutil
import subprocess
import sys
import stat
import uuid
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Parallax Beta.app"
BUNDLE_ID = "com.yosefshammout.parallax.beta"
MACHO = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def run(args: list[str], **kwargs: object) -> str:
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    return result.stdout.strip()


def clean_build_env() -> dict[str, str]:
    """Build dependencies never inherit provider credentials or Python injection."""
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "MACOSX_DEPLOYMENT_TARGET": "15.0"}


def safe_extract_runtime(archive: Path, destination: Path) -> None:
    """Validate the entire archive, then extract without following archive links."""
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Runtime extraction destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Runtime extraction destination cannot be a symlink")
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > 20000 or sum(item.size for item in members) > 1024 * 1024 * 1024:
            raise ValueError("Runtime archive exceeds allowed limits")
        names: set[str] = set()
        links: set[str] = set()
        link_targets: dict[str, str] = {}
        regular_files: set[str] = set()
        for item in members:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or not path.parts or path.parts[0] != "python"
                    or ".." in path.parts or "\\" in item.name or "\x00" in item.name):
                raise ValueError("Unsafe runtime archive path")
            normalized = str(path)
            if normalized in names or not (item.isfile() or item.isdir() or item.issym()):
                raise ValueError("Duplicate or unsupported runtime archive entry")
            names.add(normalized)
            if item.isfile():
                regular_files.add(normalized)
            if item.issym():
                target = PurePosixPath(item.linkname)
                if target.is_absolute() or "\\" in item.linkname or "\x00" in item.linkname:
                    raise ValueError("Unsafe runtime symlink")
                resolved = (destination / str(path.parent) / str(target)).resolve()
                if not resolved.is_relative_to(destination / "python"):
                    raise ValueError("Runtime symlink escapes Python directory")
                links.add(normalized)
                link_targets[normalized] = posixpath.normpath(str(path.parent / target))
        if any(target not in regular_files for target in link_targets.values()):
            raise ValueError("Runtime links must point directly to included regular files")
        for name in names:
            if any(str(parent) in links or str(parent) in regular_files for parent in PurePosixPath(name).parents):
                raise ValueError("Runtime archive writes through a symlink or regular file")
        for item in members:
            if item.issym():
                continue
            target = destination / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.isdir():
                target.mkdir(exist_ok=True)
            else:
                stream = source.extractfile(item)
                if stream is None:
                    raise ValueError("Unreadable runtime file")
                with stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)
            target.chmod(item.mode & 0o755)
        for item in members:
            if item.issym():
                target = destination / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(item.linkname)


def private_cache_directory(cache: Path) -> Path:
    cache = cache.absolute()
    if ".." in cache.parts:
        raise ValueError("Desktop cache paths must be canonical")
    for ancestor in [*reversed(cache.parents), cache]:
        if ancestor.is_symlink():
            raise ValueError("Desktop cache paths cannot contain symlinks")
        if ancestor.exists():
            details = ancestor.stat()
            if details.st_mode & 0o022 and not details.st_mode & stat.S_ISVTX:
                raise ValueError("Desktop cache ancestor permits unsafe directory replacement")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise ValueError("Desktop cache must be owned by the current user with mode0700")
    finally:
        os.close(descriptor)
    if any(path.is_symlink() for path in cache.iterdir()):
        raise ValueError("Desktop cache contains an untrusted symlink")
    return cache


def obtain_runtime(lock: dict[str, object], cache: Path) -> Path:
    url = str(lock["url"])
    if not url.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/"):
        raise ValueError("Runtime must come from pinned Astral release URL")
    digest = str(lock["sha256"])
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Runtime SHA256 pin is required")
    cache = private_cache_directory(cache)
    filename = digest + (".tar.zst" if lock.get("archive_flavor") == "full" else ".tar.gz")
    path = cache / filename
    directory = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(directory)
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise ValueError("Desktop cache ownership or permissions changed")
        try:
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            temporary = "." + digest + "." + uuid.uuid4().hex + ".download"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
                    downloaded = hashlib.sha256()
                    count = 0
                    while block := response.read(1024 * 1024):
                        count += len(block)
                        if count > int(lock["size"]):
                            raise ValueError("Runtime download exceeds pinned size")
                        downloaded.update(block)
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                if count != int(lock["size"]) or downloaded.hexdigest() != digest:
                    raise ValueError("Runtime archive does not match pin")
                os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            details = os.fstat(source.fileno())
            if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_nlink != 1
                    or details.st_mode & 0o022 or details.st_size != int(lock["size"])):
                raise ValueError("Cached runtime file is untrusted or does not match pin")
            actual = hashlib.sha256()
            for block in iter(lambda: source.read(1024 * 1024), b""):
                actual.update(block)
            if actual.hexdigest() != digest:
                raise ValueError("Cached runtime archive does not match pin")
        return path
    finally:
        os.close(directory)


def install_runtime_licenses(lock: dict[str, object], cache: Path, resources: Path) -> None:
    archive = obtain_runtime(lock["licensing_archive"], cache)
    # Read exact regular license members from a hash-verified upstream full archive;
    # never extract its build artifacts, paths, or links into the app.
    names = run(["/usr/bin/tar", "-tf", str(archive)]).splitlines()
    licenses = [name for name in names if re.fullmatch(r"python/licenses/LICENSE\.[A-Za-z0-9_.+-]+\.txt", name)]
    if len(licenses) < 10 or len(licenses) != len(set(licenses)):
        raise ValueError("Runtime licensing archive is incomplete or ambiguous")
    metadata = json.loads(run(["/usr/bin/tar", "-xOf", str(archive), "python/PYTHON.json"]))
    if metadata["python_version"] != lock["python_version"] or metadata["target_triple"] != lock["target"]:
        raise ValueError("Runtime licensing metadata does not match the embedded Python")
    target = resources / "RuntimeLicenses"
    target.mkdir()
    atomic_json(target / "PYTHON.json", metadata)
    for name in licenses:
        text = run(["/usr/bin/tar", "-xOf", str(archive), name])
        if not text or len(text) > 1024 * 1024:
            raise ValueError("Invalid runtime license text")
        (target / PurePosixPath(name).name).write_text(text + "\n")


def explicit_keychain(value: Path | None) -> Path | None:
    """Inspect metadata only. Keychain secrets stay inside Apple's signing tools."""
    if value is None:
        return None
    path = value.expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("The explicit signing keychain must have an absolute canonical path")
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink():
            raise ValueError("The explicit signing keychain cannot use a symlink path")
    details = path.stat()
    if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
            or details.st_mode & 0o022 or not os.access(path, os.R_OK)):
        raise ValueError("The explicit signing keychain must be a readable user-owned regular file without group/world write access")
    return path

def require_identity(identity: str, team_id: str, keychain: Path | None = None) -> None:
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        raise ValueError("A ten-character Apple Team ID is required")
    if not identity.startswith("Developer ID Application: ") or not identity.endswith("(" + team_id + ")"):
        raise ValueError("Release requires a Developer ID Application identity for the selected team")
    keychain = explicit_keychain(keychain)
    command = ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"]
    if keychain is not None:
        command.append(str(keychain))
    identities = run(command)
    if '"' + identity + '"' not in identities:
        raise ValueError("Selected Developer ID identity is not currently usable; unlock the selected keychain and verify its certificate trust chain")


def macho_files(app: Path) -> list[Path]:
    files = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) in MACHO:
                    files.append(path)
    return sorted(files, key=lambda item: (-len(item.parts), str(item)))



def validate_macho_compatibility(app: Path) -> list[dict[str, object]]:
    """Refuse a payload whose native code needs newer macOS than the label."""
    components = []
    for path in macho_files(app):
        architectures = run(["/usr/bin/lipo", "-archs", str(path)]).split()
        if "arm64" not in architectures:
            raise ValueError("Bundle contains code incompatible with Apple Silicon")
        commands = run(["/usr/bin/otool", "-l", str(path)])
        minimums = re.findall(r"\bminos (\d+\.\d+(?:\.\d+)?)", commands)
        minimums += re.findall(r"LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+\.\d+(?:\.\d+)?)", commands)
        if not minimums:
            raise ValueError("Native component has no verifiable macOS deployment target")
        # Universal wheels may contain x86 code with a separate lower target.
        if any(tuple(int(part) for part in value.split(".")[:2]) > (15, 0) for value in minimums):
            raise ValueError("Native component exceeds the macOS15 support label: " + str(path.relative_to(app)))
        components.append({"path": str(path.relative_to(app)), "architectures": architectures, "minimum_macos": minimums})
    return components

def validate_entitlements(path: Path) -> None:
    # No broad runtime exceptions are necessary for the non-JIT embedded Python.
    if plistlib.loads(path.read_bytes()) != {}:
        raise ValueError("Beta signing entitlements must remain empty")


def sign_app(app: Path, identity: str, adhoc: bool, entitlements: Path, keychain: Path | None = None) -> None:
    validate_entitlements(entitlements)
    args = ["/usr/bin/codesign", "--force", "--sign", identity, "--timestamp=none" if adhoc else "--timestamp"]
    if keychain is not None:
        args += ["--keychain", str(keychain)]
    for path in macho_files(app):
        # Apple's library validation needs a real Team ID for a process loading
        # native extensions. Ad hoc local review cannot establish one. Keep the
        # narrow interpreter exception explicit; release mode hardens everything.
        local_interpreter = adhoc and path.parent == app / "Contents/Resources/python/bin" and re.fullmatch(r"python3\.\d+", path.name)
        hardening = [] if local_interpreter else ["--options", "runtime"]
        run(args + hardening + ["--entitlements", str(entitlements), str(path)])
    run(args + ["--options", "runtime", "--entitlements", str(entitlements), str(app)])
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])


def inventory(app: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(app.rglob("*")):
        name = str(path.relative_to(app))
        if path.is_symlink():
            target = os.readlink(path)
            if not path.resolve().is_relative_to(app.resolve()):
                raise ValueError("Bundle contains an escaping symlink")
            files.append({"path": name, "symlink": target})
        elif path.is_file():
            files.append({"path": name, "size": path.stat().st_size, "sha256": sha256(path), "mode": oct(path.stat().st_mode & 0o777)})
    return {"schema_version": 1, "files": files}



def stage_resource(source: Path, destination: Path, source_digests: dict[str, str]) -> None:
    name = str(source.relative_to(ROOT))
    if source.is_symlink() or not source.is_file() or name not in source_digests:
        raise ValueError("Desktop resource is absent from curated source inventory")
    shutil.copy2(source, destination)
    if sha256(destination) != source_digests[name]:
        destination.unlink(missing_ok=True)
        raise ValueError("Desktop resource changed after the source snapshot")

def create_dmg(app: Path, destination: Path, adhoc: bool, identity: str | None = None, keychain: Path | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="parallax-dmg-") as temporary:
        staging = Path(temporary)
        shutil.copytree(app, staging / APP_NAME, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        status = "LOCAL AD HOC REVIEW BUILD. Not notarized. Not an official customer download." if adhoc else "Developer ID beta. Distribute only after notarization and fresh-Mac acceptance."
        (staging / "Read Me.txt").write_text("Parallax Beta 1.4.0\n\n" + status + "\n\nDrag Parallax Beta to Applications and open it.\nChoose a project folder, then open Studio. Use the app's Help menu for setup, provider choices and beta limitations. Parallax's Python runtime and dependencies are included.\nCoding providers are installed and authorized separately. Their accounts and fees remain yours.\nThe app keeps state under ~/Library/Application Support/Parallax/Beta/projects and does not alter its bundle.\nQuit from the app to stop its local server. Do not quit during an active task.\nThis beta requires Apple Silicon and macOS15 or newer.\n", encoding="utf-8")
        pending = destination.with_name(destination.stem + ".pending.dmg")
        pending.unlink(missing_ok=True)
        try:
            run(["/usr/bin/hdiutil", "create", "-volname", "Parallax Beta", "-srcfolder", str(staging), "-format", "UDZO", "-fs", "HFS+", str(pending)])
            if not adhoc:
                if identity is None:
                    raise ValueError("DMG signing identity is required")
                command = ["/usr/bin/codesign", "--force", "--sign", identity, "--timestamp"]
                if keychain is not None:
                    command += ["--keychain", str(keychain)]
                run(command + [str(pending)])
            os.replace(pending, destination)
        finally:
            pending.unlink(missing_ok=True)


def install_dependencies(python: Path, requirements: Path, wheelhouse: Path, env: dict[str, str]) -> None:
    # Network is only used at build time for hash-locked binary wheels.
    wheelhouse = private_cache_directory(wheelhouse)
    common = [str(python), "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    run(common + ["download", "--only-binary=:all:", "--require-hashes", "--no-deps", "--index-url", "https://pypi.org/simple", "-r", str(requirements), "--dest", str(wheelhouse)], env=env)
    run(common + ["install", "--no-index", "--find-links", str(wheelhouse), "--only-binary=:all:", "--require-hashes", "--no-deps", "--no-compile", "-r", str(requirements)], env=env)


def build(args: argparse.Namespace) -> dict[str, object]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This beta builder is verified only on native Apple Silicon macOS")
    keychain = explicit_keychain(getattr(args, "keychain", None))
    if not args.adhoc:
        if not args.identity or not args.team_id:
            raise ValueError("Provide --identity and --team-id for release, or --adhoc for a local review build")
        require_identity(args.identity, args.team_id, keychain)
    output = args.output.resolve()
    if output == ROOT or ROOT.is_relative_to(output):
        raise ValueError("Output cannot replace or contain the source checkout")
    for generated in (output, args.cache.resolve()):
        if generated.is_relative_to(ROOT) and (generated == ROOT or generated.relative_to(ROOT).parts[0] not in {"output", "releases"}):
            raise ValueError("Generated desktop artifacts must remain outside curated source inputs")
    output.mkdir(parents=True, exist_ok=True)
    runtime_lock = json.loads((ROOT / "desktop/runtime-lock.json").read_text())["macos-arm64"]
    cache = private_cache_directory(args.cache)
    archive = obtain_runtime(runtime_lock, cache)
    # Curated source inventory rejects private state, symlinks, and credential files.
    from release_files import release_files
    source_files = release_files(ROOT)
    source_manifest = [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in source_files]
    source_digests = {item["path"]: item["sha256"] for item in source_manifest}
    launcher = ROOT / "desktop/macos/Launcher.swift"
    if not launcher.is_file() or launcher.is_symlink():
        raise ValueError("Native launcher source is missing")
    with tempfile.TemporaryDirectory(prefix="parallax-app-build-") as temporary:
        staging = Path(temporary)
        app = staging / APP_NAME
        contents = app / "Contents"
        resources = contents / "Resources"
        (contents / "MacOS").mkdir(parents=True)
        resources.mkdir()
        safe_extract_runtime(archive, resources)
        python = resources / "python/bin/python3"
        env = clean_build_env()
        env["HOME"] = str(staging / "build-home")
        Path(env["HOME"]).mkdir()
        wheels = cache / "wheels"
        install_dependencies(python, ROOT / "requirements.lock", wheels, env)
        site = Path(run([str(python), "-I", "-B", "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"], env=env))
        package_source = ROOT / "src/parallax"
        allowed = {path for path in source_files if path.is_relative_to(package_source)}
        package = site / "parallax"
        package.mkdir(exist_ok=True)
        for path in sorted(allowed):
            target = package / path.relative_to(package_source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if sha256(target) != source_digests[str(path.relative_to(ROOT))]:
                raise ValueError("Source changed while staging the app")
        # Keep core license, wheel license texts, runtime attribution and pinned inputs.
        install_runtime_licenses(runtime_lock, cache, resources)
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE-Parallax.txt")
        shutil.copy2(ROOT / "desktop/runtime-lock.json", resources / "runtime-lock.json")
        shutil.copy2(ROOT / "requirements.lock", resources / "requirements.lock")
        atomic_json(resources / "source-manifest.json", source_manifest)
        distributions = json.loads(run([str(python), "-I", "-B", "-c", "import importlib.metadata,json;print(json.dumps(sorted([{'name':d.metadata.get('Name'),'version':d.version,'license':d.metadata.get('License-Expression') or d.metadata.get('License'),'license_files':[str(p) for p in (d.files or []) if 'license' in str(p).lower() or 'copying' in str(p).lower()]} for d in importlib.metadata.distributions()],key=lambda d:d['name'].lower())))"], env=env))
        atomic_json(resources / "dependency-inventory.json", {"python": runtime_lock, "packages": distributions})
        (resources / "Third Party Notices.txt").write_text("Parallax is MIT licensed; see LICENSE-Parallax.txt.\nEmbedded CPython is supplied by Astral python-build-standalone.\nRuntime source and licenses: https://github.com/astral-sh/python-build-standalone/releases/tag/20261009\nRuntimeLicenses includes upstream runtime metadata and license texts. Python and package license files remain in the embedded runtime.\nSee dependency-inventory.json for component versions and license paths.\nNo host runtime, provider credentials, or customer project is included.\n")
        stage_resource(ROOT / "desktop/macos/Info.plist", contents / "Info.plist", source_digests)
        stage_resource(ROOT / "desktop/macos/Parallax.icns", resources / "Parallax.icns", source_digests)
        stage_resource(ROOT / "desktop/macos/BetaGuide.html", resources / "BetaGuide.html", source_digests)
        run(["/usr/bin/xcrun", "swiftc", "-parse-as-library", "-O", "-target", "arm64-apple-macos15.0", str(launcher), "-o", str(contents / "MacOS/Parallax")], env=env)
        # Build installs no bytecode, and runtime never writes bytecode into the signed app.
        for cache in resources.rglob("__pycache__"):
            shutil.rmtree(cache)
        run(["/usr/bin/xattr", "-cr", str(app)])
        identity = "-" if args.adhoc else args.identity
        native_components = validate_macho_compatibility(app)
        sign_app(app, identity, args.adhoc, ROOT / "desktop/macos/entitlements.plist", keychain)
        # A real embedded-runtime import check after hardened signing, with hostile host env absent.
        health = json.loads(run([str(python), "-I", "-B", "-c", "import ssl,sqlite3,cryptography,pydantic_core,fastapi,httpx,uvicorn,langgraph,parallax.desktop,sys,json;print(json.dumps({'python':sys.version.split()[0],'parallax':__import__('parallax').__version__,'module':parallax.desktop.__file__}))"], env=env))
        if health["python"] != runtime_lock["python_version"] or health["parallax"] != "1.4.0":
            raise ValueError("Embedded package or interpreter does not match release identity")
        health["module"] = str(Path(health["module"]).relative_to(app.resolve()))
        destination = output / APP_NAME
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(app, destination, symlinks=True)
        label = "local-adhoc" if args.adhoc else "developer-id-unnotarized"
        dmg = output / ("parallax-1.4.0-macos-arm64-" + label + ".dmg")
        create_dmg(destination, dmg, args.adhoc, identity, keychain)
        bundle_inventory = inventory(destination)
        atomic_json(output / "bundle-inventory.json", bundle_inventory)
        receipt = {"schema_version": 1, "version": "1.4.0", "architecture": "arm64", "minimum_macos": "15.0", "bundle_id": BUNDLE_ID, "app": str(destination), "dmg": str(dmg), "dmg_sha256": sha256(dmg), "bundle_inventory_sha256": sha256(output / "bundle-inventory.json"), "runtime": runtime_lock, "native_components": native_components, "requirements_sha256": sha256(ROOT / "requirements.lock"), "source_manifest_sha256": sha256(resources / "source-manifest.json"), "signing": "ad-hoc-local-review" if args.adhoc else "developer-id", "local_interpreter_hardened_runtime": not args.adhoc, "team_id": args.team_id if not args.adhoc else None, "notarized": False, "signing_entitlements": {}, "fresh_mac_acceptance": "unverified", "live_workflow_acceptance": "unverified", "release_ready": False, "published": False, "health": health}
        atomic_json(output / "build-receipt.json", receipt)
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adhoc", action="store_true", help="Explicit local review build; cannot be an official download")
    parser.add_argument("--identity", help="Exact Developer ID Application Keychain identity")
    parser.add_argument("--team-id")
    parser.add_argument("--keychain", type=Path, help="Optional dedicated Keychain path; unlock it manually, never pass a password")
    parser.add_argument("--output", type=Path, default=ROOT / "output/desktop/macos-arm64")
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()).resolve() / "parallax-desktop-runtime-cache")
    args = parser.parse_args()
    if args.adhoc and (args.identity or args.team_id or args.keychain):
        parser.error("Do not combine --adhoc with a release signing identity")
    try:
        receipt = build(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and Path(error.cmd[0]).name in {"codesign", "security"}:
            detail = "Apple signing tool failed. Unlock the selected keychain manually and check its matching identity; no secrets were exported."
        else:
            detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        parser.exit(1, "Build refused: " + str(detail)[-4000:] + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
