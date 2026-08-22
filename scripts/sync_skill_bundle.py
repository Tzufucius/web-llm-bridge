"""Synchronize the canonical Markdown Skill into the packaged resource tree."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "web-llm-bridge"
DESTINATION = ROOT / "web_llm_bridge" / "_bundled_skills" / "web-llm-bridge"
EXECUTABLE_SUFFIXES = {".py", ".js", ".ts", ".sh", ".ps1", ".exe", ".dll", ".so"}


def validate_source() -> list[Path]:
    if not SOURCE.is_dir():
        raise RuntimeError(f"Canonical Skill directory is missing: {SOURCE}")
    files = sorted(path for path in SOURCE.rglob("*") if path.is_file())
    if not any(path.name == "SKILL.md" for path in files):
        raise RuntimeError("Canonical Skill must contain SKILL.md")
    for path in files:
        if path.suffix.lower() in EXECUTABLE_SUFFIXES or path.suffix.lower() != ".md":
            raise RuntimeError(f"Canonical Skill contains a non-Markdown file: {path.relative_to(SOURCE)}")
        path.read_text(encoding="utf-8")
    return files


def sync() -> int:
    files = validate_source()
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if DESTINATION.exists():
        if DESTINATION.is_symlink() or not DESTINATION.is_dir():
            raise RuntimeError(f"Generated Skill mirror is not a directory: {DESTINATION}")
        shutil.rmtree(DESTINATION)
    shutil.copytree(SOURCE, DESTINATION)
    print(f"Synchronized {len(files)} Markdown files")
    print(f"Source: {SOURCE}")
    print(f"Mirror: {DESTINATION}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(sync())
    except (OSError, RuntimeError, UnicodeDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
