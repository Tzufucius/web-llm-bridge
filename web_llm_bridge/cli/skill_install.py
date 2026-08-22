"""Install the bundled Web LLM Bridge Agent Skill without runtime side effects."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable

try:
    from importlib.resources.abc import Traversable
except ModuleNotFoundError:  # Python 3.9 exposes it from importlib.abc.
    from importlib.abc import Traversable


SKILL_NAME = "web-llm-bridge"
MANIFEST_NAME = ".web-llm-bridge-skill.json"
MANIFEST_SCHEMA_VERSION = 1
_EXECUTABLE_SUFFIXES = {".py", ".js", ".ts", ".sh", ".ps1", ".exe", ".dll", ".so"}


@dataclass(frozen=True)
class SkillBundle:
    version: str
    files: dict[str, bytes]
    content_hash: str


@dataclass(frozen=True)
class TargetStatus:
    path: Path
    status: str
    installed_version: str | None = None


def _package_version() -> str:
    return importlib.metadata.version("web-llm-bridge")


def _bundle_resource() -> Traversable:
    resource = resources.files("web_llm_bridge").joinpath("_bundled_skills", SKILL_NAME)
    if not resource.is_dir():
        raise RuntimeError("Bundled Web LLM Bridge Skill is missing from the installed package")
    return resource


def _relative_path(path: str) -> str:
    return path.replace("\\", "/")


def _bundle_files(resource: Traversable) -> dict[str, bytes]:
    files: dict[str, bytes] = {}

    def visit(node: Traversable, prefix: str = "") -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            relative = _relative_path(f"{prefix}/{child.name}" if prefix else child.name)
            if child.is_dir():
                visit(child, relative)
                continue
            suffix = Path(child.name).suffix.lower()
            if suffix in _EXECUTABLE_SUFFIXES or suffix != ".md":
                raise RuntimeError(f"Bundled Skill contains a non-Markdown file: {relative}")
            data = child.read_bytes()
            data.decode("utf-8")
            files[relative] = data

    visit(resource)
    required = {"SKILL.md"}
    if not required.issubset(files):
        raise RuntimeError("Bundled Skill must contain SKILL.md")
    if not any(path.startswith("references/") and path.endswith(".md") for path in files):
        raise RuntimeError("Bundled Skill must contain Markdown references")
    return files


def _hash_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        normalized = files[relative].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(normalized)
        digest.update(b"\0")
    return digest.hexdigest()


def load_bundle() -> SkillBundle:
    files = _bundle_files(_bundle_resource())
    return SkillBundle(version=_package_version(), files=files, content_hash=_hash_files(files))


def _target_files(path: Path) -> dict[str, bytes] | None:
    if not path.is_dir() or path.is_symlink():
        return None
    files: dict[str, bytes] = {}
    for file in path.rglob("*"):
        if not file.is_file() or file.name == MANIFEST_NAME:
            continue
        relative = _relative_path(file.relative_to(path).as_posix())
        if file.suffix.lower() != ".md":
            return None
        try:
            data = file.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        files[relative] = data
    return files


def _read_manifest(path: Path) -> dict[str, object] | None:
    manifest_path = path / MANIFEST_NAME
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def inspect_target(path: Path, bundle: SkillBundle) -> TargetStatus:
    if not path.exists() or path.is_symlink():
        return TargetStatus(path, "MISSING" if not path.exists() else "MODIFIED")
    if not path.is_dir():
        return TargetStatus(path, "MODIFIED")
    manifest = _read_manifest(path)
    files = _target_files(path)
    if manifest is None or files is None or files.keys() != bundle.files.keys():
        installed_version = manifest.get("bridge_version") if manifest else None
        return TargetStatus(path, "MODIFIED", installed_version if isinstance(installed_version, str) else None)
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("skill") != SKILL_NAME
        or manifest.get("installed_by") != "web-llm-bridge"
    ):
        installed_version = manifest.get("bridge_version")
        return TargetStatus(path, "MODIFIED", installed_version if isinstance(installed_version, str) else None)
    installed_version = manifest.get("bridge_version")
    installed_hash = manifest.get("content_hash")
    if not isinstance(installed_version, str) or not isinstance(installed_hash, str):
        return TargetStatus(path, "MODIFIED")
    if _hash_files(files) != bundle.content_hash or installed_hash != bundle.content_hash:
        return TargetStatus(path, "MODIFIED", installed_version)
    if installed_version != bundle.version:
        return TargetStatus(path, "OUTDATED", installed_version)
    return TargetStatus(path, "CURRENT", installed_version)


def _codex_root(global_scope: bool) -> Path:
    if global_scope:
        configured = os.environ.get("CODEX_HOME")
        return Path(configured).expanduser() if configured else Path.home() / ".codex"
    return Path.cwd() / ".codex"


def _target_roots(target: str, global_scope: bool) -> list[Path]:
    base = Path.home() if global_scope else Path.cwd()
    roots: dict[str, Path] = {
        "codex": _codex_root(global_scope),
        "claude": base / ".claude",
        "agents": base / ".agents",
    }
    if target == "all":
        return [roots["codex"] / "skills" / SKILL_NAME, roots["claude"] / "skills" / SKILL_NAME]
    return [roots[target] / "skills" / SKILL_NAME]


def resolve_targets(*, target: str | None, global_scope: bool, custom_path: str | None) -> list[Path]:
    if custom_path is not None:
        path = Path(custom_path).expanduser().resolve()
        if path.name != SKILL_NAME:
            raise ValueError(f"--path must name the final Skill directory {SKILL_NAME!r}")
        return [path]
    return _target_roots(target or "all", global_scope)


def _manifest(bundle: SkillBundle) -> str:
    return json.dumps(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "skill": SKILL_NAME,
            "bridge_version": bundle.version,
            "content_hash": bundle.content_hash,
            "installed_by": "web-llm-bridge",
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _copy_bundle(bundle: SkillBundle, destination: Path) -> None:
    for relative, data in bundle.files.items():
        file = destination / Path(relative)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    (destination / MANIFEST_NAME).write_bytes(_manifest(bundle).encode("utf-8"))


def _replace_target(path: Path, bundle: SkillBundle) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RuntimeError(f"Skill target is not a directory: {path}")
    temp_path: Path | None = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-", dir=parent))
    backup: Path | None = None
    try:
        _copy_bundle(bundle, temp_path)
        if inspect_target(temp_path, bundle).status != "CURRENT":
            raise RuntimeError("Bundled Skill integrity validation failed")
        if path.exists():
            backup = parent / f".{SKILL_NAME}.backup-{os.getpid()}"
            counter = 0
            while backup.exists():
                counter += 1
                backup = parent / f".{SKILL_NAME}.backup-{os.getpid()}-{counter}"
            path.rename(backup)
        assert temp_path is not None
        temp_path.rename(path)
        temp_path = None
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if temp_path is not None and temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
        if backup is not None and backup.exists() and not path.exists():
            backup.rename(path)
        raise


def _print_status(status: TargetStatus, bundle: SkillBundle) -> None:
    print(f"Skill: {SKILL_NAME}")
    print(f"CLI version: {bundle.version}")
    print(f"Target: {status.path}")
    print(f"Installed version: {status.installed_version or '-'}")
    print(f"Status: {status.status}")


def install(bundle: SkillBundle, targets: Iterable[Path], *, force: bool, check: bool) -> int:
    statuses = [inspect_target(path, bundle) for path in targets]
    if check:
        for status in statuses:
            _print_status(status, bundle)
        return 0 if all(status.status == "CURRENT" for status in statuses) else 1

    conflicts = [status for status in statuses if status.status not in {"MISSING", "CURRENT"}]
    if conflicts and not force:
        for status in conflicts:
            print(
                f"Installed Web LLM Bridge Skill differs from the bundled version at {status.path}.\n"
                "Run: web-llm-bridge install --skills --force to replace it.",
                file=sys.stderr,
            )
        return 1

    changed = False
    for status in statuses:
        if status.status == "CURRENT":
            print(f"Web LLM Bridge Skill is already up to date: {status.path}")
            continue
        _replace_target(status.path, bundle)
        print(f"Installed Web LLM Bridge Skill: {status.path}")
        changed = True
    return 0 if changed or statuses else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the bundled Web LLM Bridge Agent Skill.")
    parser.add_argument("--skills", action="store_true", help="Install or inspect the bundled Skill.")
    parser.add_argument("--target", choices=("all", "codex", "claude", "agents"), default=None)
    parser.add_argument("-g", "--global", dest="global_scope", action="store_true", help="Use the current user's Skill directories.")
    parser.add_argument("--path", help="Install into this final Skill directory.")
    parser.add_argument("--force", action="store_true", help="Replace an existing modified Skill explicitly.")
    parser.add_argument("--check", action="store_true", help="Report Skill status without modifying files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.skills:
        parser.error("install requires --skills")
    if args.force and args.check:
        parser.error("--force and --check are mutually exclusive")
    if args.path is not None and (args.target is not None or args.global_scope):
        parser.error("--path cannot be combined with --target or --global")
    try:
        targets = resolve_targets(target=args.target, global_scope=args.global_scope, custom_path=args.path)
        return install(load_bundle(), targets, force=args.force, check=args.check)
    except (OSError, RuntimeError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def warn_if_stale() -> None:
    """Warn for known installed targets without affecting Agent JSON output."""
    try:
        bundle = load_bundle()
        paths = (
            _target_roots("all", False)
            + _target_roots("agents", False)
            + _target_roots("all", True)
            + _target_roots("agents", True)
        )
        if any(inspect_target(path, bundle).status in {"OUTDATED", "MODIFIED"} for path in paths):
            print(
                "Web LLM Bridge Skill does not match the installed CLI version.\n"
                "Run: web-llm-bridge install --skills --force to update it.",
                file=sys.stderr,
            )
    except (OSError, RuntimeError, importlib.metadata.PackageNotFoundError):
        return
