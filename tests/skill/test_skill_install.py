import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib import resources
from unittest.mock import patch

from web_llm_bridge.cli import launcher
from web_llm_bridge.cli import skill_install


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "skills" / "web-llm-bridge"
MIRROR = ROOT / "web_llm_bridge" / "_bundled_skills" / "web-llm-bridge"


def _normalized_tree(path: Path) -> dict[str, str]:
    return {
        file.relative_to(path).as_posix(): file.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        for file in path.rglob("*.md")
    }


class SkillInstallTests(unittest.TestCase):
    def test_canonical_and_packaged_mirror_match(self) -> None:
        self.assertEqual(_normalized_tree(CANONICAL), _normalized_tree(MIRROR))

    def test_canonical_skill_has_only_markdown_files(self) -> None:
        self.assertTrue((CANONICAL / "SKILL.md").is_file())
        self.assertTrue(all(path.suffix.lower() == ".md" for path in CANONICAL.rglob("*" ) if path.is_file()))

    def test_relative_markdown_links_stay_inside_skill_tree(self) -> None:
        pattern = re.compile(r"\]\(([^)]+)\)")
        for file in CANONICAL.rglob("*.md"):
            for target in pattern.findall(file.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                self.assertTrue((file.parent / relative).resolve().is_file(), f"broken link: {file} -> {target}")

    def test_package_resource_contains_skill(self) -> None:
        resource = resources.files("web_llm_bridge").joinpath("_bundled_skills", "web-llm-bridge", "SKILL.md")
        self.assertIn("# Web LLM Bridge", resource.read_text(encoding="utf-8"))

    def test_project_targets_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("web_llm_bridge.cli.skill_install.Path.cwd", return_value=Path(directory)):
            self.assertEqual(skill_install.main(["--skills"]), 0)
            codex = Path(directory) / ".codex" / "skills" / "web-llm-bridge"
            claude = Path(directory) / ".claude" / "skills" / "web-llm-bridge"
            self.assertTrue((codex / "SKILL.md").is_file())
            self.assertTrue((claude / "references" / "error-handling.md").is_file())
            self.assertEqual(skill_install.main(["--skills"]), 0)

    def test_explicit_targets_and_custom_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("web_llm_bridge.cli.skill_install.Path.cwd", return_value=root):
                self.assertEqual(skill_install.main(["--skills", "--target", "agents"]), 0)
                self.assertTrue((root / ".agents" / "skills" / "web-llm-bridge" / "SKILL.md").is_file())
            custom = root / "custom" / "web-llm-bridge"
            self.assertEqual(skill_install.main(["--skills", "--path", str(custom)]), 0)
            self.assertTrue((custom / "SKILL.md").is_file())

    def test_global_target_uses_home_and_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as codex_home:
            with patch("web_llm_bridge.cli.skill_install.Path.home", return_value=Path(home)), patch.dict(
                skill_install.os.environ, {"CODEX_HOME": codex_home}
            ):
                self.assertEqual(skill_install.main(["--skills", "--global", "--target", "all"]), 0)
            self.assertTrue((Path(codex_home) / "skills" / "web-llm-bridge" / "SKILL.md").is_file())
            self.assertTrue((Path(home) / ".claude" / "skills" / "web-llm-bridge" / "SKILL.md").is_file())

    def test_manifest_hash_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "web-llm-bridge"
            self.assertEqual(skill_install.main(["--skills", "--path", str(target)]), 0)
            manifest = json.loads((target / skill_install.MANIFEST_NAME).read_text(encoding="utf-8"))
            bundle = skill_install.load_bundle()
            self.assertEqual(manifest["bridge_version"], bundle.version)
            self.assertEqual(manifest["content_hash"], bundle.content_hash)
            self.assertEqual(skill_install.inspect_target(target, bundle).status, "CURRENT")

            manifest["bridge_version"] = "0.0.9"
            (target / skill_install.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(skill_install.inspect_target(target, bundle).status, "OUTDATED")

    def test_modified_target_requires_force_and_force_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "web-llm-bridge"
            self.assertEqual(skill_install.main(["--skills", "--path", str(target)]), 0)
            skill_file = target / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(skill_install.main(["--skills", "--path", str(target)]), 1)
            self.assertIn("--force", error.getvalue())
            self.assertEqual(skill_install.main(["--skills", "--path", str(target), "--force"]), 0)
            self.assertEqual(skill_install.inspect_target(target, skill_install.load_bundle()).status, "CURRENT")

    def test_check_is_read_only_and_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "web-llm-bridge"
            self.assertEqual(skill_install.main(["--skills", "--path", str(target), "--check"]), 1)
            self.assertFalse(target.exists())
            self.assertEqual(skill_install.main(["--skills", "--path", str(target)]), 0)
            before = (target / "SKILL.md").read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(skill_install.main(["--skills", "--path", str(target), "--check"]), 0)
            self.assertIn("Status: CURRENT", output.getvalue())
            self.assertEqual(before, (target / "SKILL.md").read_bytes())

    def test_crlf_does_not_change_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "web-llm-bridge"
            self.assertEqual(skill_install.main(["--skills", "--path", str(target)]), 0)
            for file in target.rglob("*.md"):
                file.write_bytes(file.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(skill_install.inspect_target(target, skill_install.load_bundle()).status, "CURRENT")

    def test_install_does_not_start_broker(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "ensure_broker") as ensure, patch(
            "socket.create_connection", side_effect=AssertionError("installer must not use sockets")
        ):
            self.assertEqual(launcher.manual_main(["install", "--skills", "--path", str(Path(directory) / "web-llm-bridge")]), 0)
        ensure.assert_not_called()
