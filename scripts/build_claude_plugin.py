#!/usr/bin/env python3
"""Assemble the Claude Code plugin exactly as Anthropic's directory installs it, and check it against the directory's rules.

The repository root is also a Codex plugin, so its default skills/ folder holds the Codex skill. The directory installs
the folder that holds .claude-plugin/plugin.json, so it gets a tree of its own: the runtime, the four Claude Code skills
under skills/, the Studio source, and nothing Codex-specific. CI publishes this tree to the claude-code-plugin branch.
"""
from pathlib import Path
import argparse
import json
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_files import release_files

ROOT = Path(__file__).resolve().parents[1]
NAME = "parallax-team"
MCP_SERVERS = {"parallax": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/parallax.py", "mcp"]}}
FILE_LIMIT, SIZE_LIMIT, HARD_SIZE_LIMIT = 512, 256 * 1024, 5 * 1024 * 1024
# The packaged Studio bundle is minified and larger than the per-file limit, so a reviewer always reads it; CI proves
# it is the build of studio/. Nothing else may exceed the limit.
LARGE_ALLOWED = re.compile(r"src/parallax/static/assets/index-[A-Za-z0-9_-]+\.(js|css)")
RESERVED = {"claude", "anthropic", "official", "plugin", "mcp", "test"}
SYSTEM_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
# Vercel builds every branch of the repository; this keeps it from trying to deploy the plugin branch.
GENERATED = {"vercel.json": json.dumps({"git": {"deploymentEnabled": False}}, indent=2) + "\n"}


def plugin_files(root: Path = ROOT) -> dict[str, Path]:
    """Map each path in the plugin tree to its source in the repository."""
    root = root.resolve()
    files: dict[str, Path] = {}
    for path in release_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("src/parallax/", "studio/")) or relative in {"scripts/parallax.py", "requirements.lock", "pyproject.toml",
                                                                          "LICENSE", "assets/parallax-icon.svg"}:
            files[relative] = path
        elif relative.startswith("claude-code/skills/"):
            files["skills/" + relative.removeprefix("claude-code/skills/")] = path
    files[".claude-plugin/plugin.json"] = root / ".claude-plugin/plugin.json"
    files["README.md"] = root / "claude-code/README.md"
    return dict(sorted(files.items()))


def _front_matter(text: str) -> dict[str, str] | None:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def check(files: dict[str, Path]) -> list[str]:
    """Problems the directory would block or that would change what users install. An empty list means ready."""
    problems = []
    every = sorted([*files, *GENERATED])
    if len(every) > FILE_LIMIT:
        problems.append(f"{len(every)} files; the directory reviews any plugin over {FILE_LIMIT}")
    seen = {}
    for relative in every:
        parts = relative.split("/")
        if parts[-1].lower() in SYSTEM_FILES or "__MACOSX" in parts:
            problems.append("System file in the plugin: " + relative)
        if any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts[:-1]):
            problems.append("Folder name the directory cannot validate: " + relative)
        if re.search(r'[:<>"|?*]|[. ]$', parts[-1]):
            problems.append("File name invalid on Windows: " + relative)
        if relative.lower() in seen:
            problems.append(f"Names differ only by case: {seen[relative.lower()]} and {relative}")
        seen[relative.lower()] = relative
    for relative, path in files.items():
        size = path.stat().st_size
        if size > HARD_SIZE_LIMIT:
            problems.append(f"{relative} is over 5 MiB")
        elif size > SIZE_LIMIT and not LARGE_ALLOWED.fullmatch(relative):
            problems.append(f"{relative} is over 256 KiB")
    manifest = json.loads(files[".claude-plugin/plugin.json"].read_text())
    if manifest.get("name") != NAME or manifest["name"] in RESERVED or not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?", manifest["name"]):
        problems.append("Plugin name must be " + NAME)
    if manifest.get("mcpServers") != MCP_SERVERS:
        problems.append("The MCP server must start as python3 ${CLAUDE_PLUGIN_ROOT}/scripts/parallax.py mcp")
    for field in ("description", "author", "version", "license"):
        if not manifest.get(field):
            problems.append("plugin.json is missing " + field)
    for field in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        if not str(manifest.get(field, "")).startswith("https://"):
            problems.append(f"plugin.json {field} must be an https:// URL")
    if manifest.get("icon", "").removeprefix("./") not in files:
        problems.append("plugin.json icon must name a file in the plugin")
    readme = re.sub(r"```.*?```", "", files["README.md"].read_text(), flags=re.S)
    if len(re.findall(r"[A-Za-z0-9][\w'-]*", readme)) < 40:
        problems.append("README.md needs at least 40 words outside code blocks")
    if "LICENSE" not in files:
        problems.append("LICENSE is missing")
    skills = sorted(relative for relative in files if re.fullmatch(r"skills/[^/]+/SKILL\.md", relative))
    if [skill.split("/")[1] for skill in skills] != ["build", "parallax", "review", "studio"]:
        problems.append("The plugin must ship exactly the build, parallax, review and studio skills")
    for skill in skills:
        fields = _front_matter(files[skill].read_text())
        if not fields or not fields.get("description"):
            problems.append(f"{skill} needs front matter with a description")
    if any(relative.startswith(("hooks/", "bin/")) or relative in {".mcp.json", ".lsp.json"} for relative in files):
        problems.append("The plugin must not ship hooks, bin/, .mcp.json or .lsp.json")
    return problems


def build(destination: Path, root: Path = ROOT) -> dict[str, Path]:
    files = plugin_files(root)
    problems = check(files)
    if problems:
        raise SystemExit("Claude Code plugin is not ready:\n- " + "\n- ".join(problems))
    if destination.exists():
        shutil.rmtree(destination)
    for relative, source in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(source.stat().st_mode & 0o777)
    for relative, text in GENERATED.items():
        (destination / relative).write_text(text)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist/claude-code-plugin", help="where to write the plugin tree")
    parser.add_argument("--check", action="store_true", help="check the plugin without writing it")
    args = parser.parse_args()
    if args.check:
        problems = check(plugin_files())
        if problems:
            raise SystemExit("Claude Code plugin is not ready:\n- " + "\n- ".join(problems))
        print("Claude Code plugin is ready for the directory.")
        return
    files = build(args.out.resolve())
    print(f"Wrote the {NAME} plugin ({len(files) + len(GENERATED)} files) to {args.out}")


if __name__ == "__main__":
    main()
