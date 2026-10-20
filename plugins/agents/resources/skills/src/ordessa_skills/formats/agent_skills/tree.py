"""Bounded, link-free scanning of one skill directory (tree.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...api.errors import SkillAssetError
from ...api.identity import MAX_ASSET_BYTES, MAX_ASSET_ENTRIES


@dataclass(frozen=True)
class TreeEntry:
    relative: str
    size: int
    path: Path


def scan_tree(root: Path) -> list[TreeEntry]:
    """Every regular file under the skill directory, bounded and link-free.

    Symlinks (files or directories), FIFOs and other non-regular entries are
    typed refusals, not surprises; the entry-count and total-byte budgets are
    charged as the tree is walked, so a bomb cannot hide deeper down.
    """
    entries: list[TreeEntry] = []
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in dirnames:
            if os.path.islink(os.path.join(directory, name)):
                raise SkillAssetError(
                    "SKILL_ASSET_INVALID", "a skill may hold only regular files",
                    detail=name)
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise SkillAssetError(
                    "SKILL_ASSET_INVALID", "a skill may hold only regular files",
                    detail=str(path.relative_to(root)))
            size = path.stat().st_size
            total += size
            if len(entries) >= MAX_ASSET_ENTRIES or total > MAX_ASSET_BYTES:
                raise SkillAssetError(
                    "SKILL_ASSET_OUTSIDE_BOUNDS",
                    "the skill exceeds the install bounds",
                    detail=str(path.relative_to(root)))
            entries.append(TreeEntry(str(path.relative_to(root)), size, path))
    return entries
