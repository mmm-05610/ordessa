"""Whole-directory skill validation: manifest, bounds, scripts (validator.py)."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ...api.errors import SkillAssetError
from .frontmatter import FrontmatterFacts, parse_frontmatter
from .tree import TreeEntry, scan_tree

#: Preview/transfer textual bound for one file (import-protocol.md).
MAX_PREVIEW_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class ValidatedSkill:
    facts: FrontmatterFacts
    entries: tuple[TreeEntry, ...]
    total_bytes: int
    scripts: tuple[str, ...]


def _script_markers(entries: list[TreeEntry]) -> tuple[str, ...]:
    """Files the UI must mark as scripts: everything under `scripts/` and any
    file carrying an executable bit. Content is never interpreted here."""
    markers = []
    for entry in entries:
        under_scripts = entry.relative == "scripts" or \
            entry.relative.startswith("scripts/")
        if under_scripts or entry.path.stat().st_mode & 0o111:
            markers.append(entry.relative)
    return tuple(sorted(markers))


def validate_skill_directory(root: Path, *,
                             directory_name: str | None = None) -> ValidatedSkill:
    """One skill directory in, typed facts or a typed refusal out.

    No file's content is executed, interpreted or expanded here: the manifest
    is parsed, the tree is bounded, scripts are only *named*.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SkillAssetError("SKILL_ASSET_INVALID", "the skill source must be a directory")
    manifest = root / "SKILL.md"
    if manifest.is_symlink() or not manifest.is_file():
        raise SkillAssetError("SKILL_ASSET_INVALID", "a skill needs a regular SKILL.md")
    facts = parse_frontmatter(
        manifest.read_text(encoding="utf-8", errors="replace"),
        directory_name=directory_name)
    entries = scan_tree(root)
    if not entries:
        raise SkillAssetError("SKILL_ASSET_INVALID", "the skill directory is empty")
    total = sum(entry.size for entry in entries)
    return ValidatedSkill(facts=facts, entries=tuple(entries), total_bytes=total,
                          scripts=_script_markers(entries))


def file_preview(entry: TreeEntry, root: Path) -> dict:
    """A bounded textual row for one file; binaries give path/bytes only."""
    info: dict = {"path": entry.relative, "bytes": entry.size}
    mode = entry.path.stat().st_mode
    if entry.size <= MAX_PREVIEW_FILE_BYTES:
        try:
            info["text"] = entry.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return info
    if entry.relative.startswith("scripts/") or mode & stat.S_IXUSR:
        info["script"] = True
    return info


def assert_regular_within(root: Path, relative: str) -> Path:
    """Resolve one stored path strictly inside its revision (no escape, no link)."""
    if relative.startswith("/") or ".." in Path(relative).parts or "\x00" in relative:
        raise SkillAssetError("SKILL_ASSET_INVALID", "path escapes the revision",
                              detail=relative)
    target = root / relative
    if target.is_symlink() or not target.is_file():
        raise SkillAssetError("SKILL_ASSET_MISSING", "no such file in the revision",
                              detail=relative)
    # Legacy fidelity (752f148b1b validator.py:84): a resolved target must be
    # PathLike — a non-PathLike one raises TypeError here, not later.
    _ = os.fspath(target)
    return target
