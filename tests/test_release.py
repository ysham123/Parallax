"""Release enumeration must exclude caches and reject private artifacts."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from release_files import release_files
from build_claude_plugin import build, check, plugin_files
from build_openai_plugin import build as build_openai, package_files as openai_files
import json
import zipfile


class ReleaseInputsTest(unittest.TestCase):
    def test_caches_are_pruned_and_sources_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for name in ('src/parallax/main.py','studio/node_modules/tool/index.js','studio/.playwright-cli/trace.log','studio/dist/app.js','tests/__pycache__/case.pyc'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            self.assertEqual([str(p.relative_to(root)) for p in release_files(root)],['src/parallax/main.py'])

    def test_private_inputs_fail_before_packaging(self):
        for name in ('docs/.env.local','src/state.sqlite3','studio/server.json','docs/api-sessions/request.json','scripts/.grok/config.toml'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_text('private fixture')
                with self.assertRaisesRegex(ValueError,'Private runtime or credential'):
                    release_files(root)

    def test_file_and_directory_symlinks_are_rejected(self):
        for directory in (False,True):
            with self.subTest(directory=directory),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'docs').mkdir();target=root/'outside'
                target.mkdir() if directory else target.write_text('fixture')
                (root/'docs/link').symlink_to(target,target_is_directory=directory)
                with self.assertRaisesRegex(ValueError,'symlinks'):
                    release_files(root)


class ClaudePluginTreeTest(unittest.TestCase):
    """The tree Anthropic's directory installs ships the Claude Code skills and runtime, never the Codex plugin."""

    def test_repository_tree_is_ready_and_has_only_claude_code_skills(self):
        files=plugin_files()
        self.assertEqual(check(files),[])
        skills=sorted(path for path in files if path.startswith("skills/"))
        self.assertEqual(skills,["skills/build/SKILL.md","skills/parallax/SKILL.md","skills/review/SKILL.md","skills/studio/SKILL.md"])
        self.assertFalse(any("codex" in path for path in files))
        for required in (".claude-plugin/plugin.json","README.md","LICENSE","scripts/parallax.py","requirements.lock","src/parallax/server.py","studio/src/App.tsx"):
            self.assertIn(required,files)
        self.assertFalse(any(path.startswith(("tests/","docs/",".github/",".codex-plugin/")) or path in {".mcp.json","mcp.json","plugin.json"} for path in files))

    def test_build_writes_the_tree_with_executable_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/"plugin"
            files=build(out)
            self.assertEqual(sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()),sorted([*files,"vercel.json"]))
            self.assertTrue((out/"scripts/parallax.py").stat().st_mode&0o111)
            self.assertEqual((out/"README.md").read_bytes(),files["README.md"].read_bytes())

    def test_directory_rules_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            large=root/"large.py";large.write_text("x"*(300*1024))
            system=root/".DS_Store";system.write_text("x")
            files={**plugin_files(),"src/parallax/large.py":large,"skills/.DS_Store":system}
            problems="\n".join(check(files))
            self.assertIn("src/parallax/large.py is over 256 KiB",problems)
            self.assertIn("System file",problems)
            self.assertIn("exactly the build, parallax, review and studio skills",check({**plugin_files(),"skills/extra/SKILL.md":plugin_files()["skills/build/SKILL.md"]})[0])


class OpenAIPluginTest(unittest.TestCase):
    def test_package_is_remote_only_and_review_materials_are_explicit(self):
        files = openai_files(draft=True)
        self.assertEqual(set(files), {"plugin.json","mcp.json","README.md","LICENSE","assets/parallax-icon.svg","skills/connect-parallax/SKILL.md"})
        manifest = json.loads(files["plugin.json"])
        extension = manifest["extensions"]["com.openai"]
        self.assertEqual(manifest["name"], "parallax-team")
        self.assertEqual(len(extension["review"]["test_cases"]["positive"]), 5)
        self.assertEqual(len(extension["review"]["test_cases"]["negative"]), 3)
        self.assertNotIn("demo_recording_url", extension["review"])
        self.assertIn(extension["onboardingSkill"].removeprefix("./"), files)
        mcp = json.loads(files["mcp.json"])["mcpServers"]["parallax"]
        self.assertEqual(mcp, {"type":"streamable-http","url":"https://parallax.yosefshammout.com/api/mcp"})
        with self.assertRaisesRegex(ValueError, "demo-recording-url"):
            openai_files()
        for origin in ["http://public.example", "https://key@host.com", "https://localhost", "https://host.com/private"]:
            with self.assertRaises(ValueError): openai_files(draft=True, origin=origin)

    def test_zip_is_reproducible_and_includes_only_declared_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/"first.zip", Path(directory)/"second.zip"
            build_openai(first, draft=True)
            build_openai(second, draft=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), set(openai_files(draft=True)))

