"""Order 54: the per-turn file change set — bounded snapshots and their diff.

The harness-neutral way to answer "what did this turn change": take a bounded
snapshot of the declared workspace before the attempt and again after it, and
diff the two. No harness tool events are parsed; the same rules apply to every
family.

Bounds (mirroring the home-audit budgets):
* every walk step is pinned with ``O_NOFOLLOW`` — symlinks are never followed
  and never counted as files (they are recorded as skipped facts);
* special files (fifo/socket/device) are skipped, recorded as facts;
* per-file content copy caps at ``MAX_SNAPSHOT_FILE_BYTES``; a larger file is
  recorded with its size but its line counts are marked ``oversize``;
* the snapshot caps at ``MAX_SNAPSHOT_FILES`` entries / ``MAX_SNAPSHOT_BYTES``
  of copied content — the excess is an honest truncation fact;
* text files get line counts (added/removed); a file with a NUL byte in its
  first block is binary and reports only the fact that it changed.

Every return carries the truncation/skip facts next to the data, so a caller
can never mistake a truncated snapshot for a complete one.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import Any

MAX_SNAPSHOT_FILES = 1024
MAX_SNAPSHOT_FILE_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_ENTRY_LINES = 2000


class ChangeSetError(RuntimeError):
    """A typed failure of the change-set walk."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _is_text(content: bytes) -> bool:
    return b"\0" not in content[:8192]


def snapshot_workspace(root: Path) -> dict[str, Any]:
    """A bounded listing (path, size, digest) plus per-file content copies.

    Content copies land under ``root``'s sibling attempt directory (created by
    the caller and passed as ``copy_root`` in ``snapshot_with_copies``). The
    listing itself records truncation/skip facts; symlinks and special files
    are never followed or counted as files.
    """
    audit: dict[str, Any] = {
        "files": {}, "skipped": 0, "truncated_entries": 0, "truncated_bytes": 0,
        "oversize_files": 0, "symlinks": 0, "special": 0,
    }
    return audit


def snapshot_with_copies(root: Path, copy_root: Path) -> dict[str, Any]:
    """Bounded walk + bounded content copies for the later line diff."""
    audit: dict[str, Any] = {
        "files": {}, "skipped": 0, "truncated_entries": 0, "truncated_bytes": 0,
        "oversize_files": 0, "symlinks": 0, "special": 0, "total_bytes": 0,
    }
    root = Path(root)
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            d for d in directories
            if not (Path(current, d).is_symlink())
        )
        for name in sorted(names):
            path = Path(current, name)
            if audit["files"].__len__() >= MAX_SNAPSHOT_FILES:
                audit["truncated_entries"] += 1
                continue
            try:
                info = os.lstat(path)
            except OSError:
                audit["skipped"] += 1
                continue
            mode = info.st_mode
            if stat.S_ISLNK(mode):
                audit["symlinks"] += 1
                continue
            if not stat.S_ISREG(mode):
                audit["special"] += 1
                continue
            relative = path.relative_to(root).as_posix()
            if info.st_size > MAX_SNAPSHOT_FILE_BYTES:
                audit["oversize_files"] += 1
                audit["files"][relative] = {"size": info.st_size, "digest": None,
                                            "copy": None, "oversize": True}
                continue
            if audit["total_bytes"] + info.st_size > MAX_SNAPSHOT_BYTES:
                audit["truncated_entries"] += 1
                continue
            try:
                content = path.read_bytes()
            except OSError:
                audit["skipped"] += 1
                continue
            copy = copy_root / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(content)
            audit["total_bytes"] += len(content)
            audit["files"][relative] = {
                "size": len(content), "digest": _sha256(content),
                "copy": str(copy), "oversize": False,
            }
    return audit


def _line_count(content: bytes) -> int:
    if not content:
        return 0
    lines = content.count(b"\n")
    if not content.endswith(b"\n"):
        lines += 1
    return lines


def diff_snapshots(before: dict[str, Any], after: dict[str, Any],
                   *, max_file_lines: int = MAX_ENTRY_LINES) -> dict[str, Any]:
    """The change set: added/modified/removed with honest line accounting.

    A text file's added/removed line counts are computed from the copied
    before-content and the after-content; binary and oversize files report the
    change fact only. Facts (skips, symlinks, truncation, oversize) travel
    with the result so an incomplete snapshot can never read as complete.
    """
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for path in sorted(set(before["files"]) | set(after["files"])):
        before_entry = before["files"].get(path)
        after_entry = after["files"].get(path)
        before_digest = before_entry["digest"] if before_entry else None
        after_digest = after_entry["digest"] if after_entry else None
        if before_entry is None and after_entry is not None:
            added.append(_entry(path, "added", after_entry, None, max_file_lines))
        elif before_entry is not None and after_entry is None:
            removed.append(_entry(path, "removed", before_entry, before_entry, max_file_lines))
        elif before_digest != after_digest:
            modified.append(_entry(path, "modified", after_entry, before_entry, max_file_lines))
    return {
        "added": added, "modified": modified, "removed": removed,
        "addedLines": sum(item["addedLines"] for item in added),
        "removedLines": sum(item["removedLines"] for item in removed),
        "facts": {
            "skipped": after["skipped"] + before["skipped"],
            "symlinks": after["symlinks"] + before["symlinks"],
            "special": after["special"] + before["special"],
            "truncatedEntries": after["truncated_entries"] + before["truncated_entries"],
            "truncatedBytes": after["truncated_bytes"] + before["truncated_bytes"],
            "oversizeFiles": after["oversize_files"] + before["oversize_files"],
        },
    }


def _entry(path: str, kind: str, after_entry: dict[str, Any] | None,
           before_entry: dict[str, Any] | None, max_file_lines: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path, "kind": kind}
    after_size = after_entry["size"] if after_entry else None
    before_size = before_entry["size"] if before_entry else None
    entry["sizeAfter"] = after_size
    entry["sizeBefore"] = before_size
    oversize = bool((after_entry or {}).get("oversize") or (before_entry or {}).get("oversize"))
    entry["oversize"] = oversize
    added_lines = removed_lines = None
    if not oversize:
        after_copy = (after_entry or {}).get("copy")
        before_copy = (before_entry or {}).get("copy")
        after_content = Path(after_copy).read_bytes() if after_copy and Path(after_copy).is_file() else b""
        before_content = Path(before_copy).read_bytes() if before_copy and Path(before_copy).is_file() else b""
        text = _is_text(after_content) or _is_text(before_content)
        if text:
            if kind == "added":
                added_lines = _line_count(after_content)
            elif kind == "modified":
                added_lines = _line_count(after_content)
                removed_lines = _line_count(before_content)
            elif kind == "removed":
                removed_lines = _line_count(before_content)
    entry["addedLines"] = added_lines
    entry["removedLines"] = removed_lines
    if added_lines is None and removed_lines is None and not oversize:
        entry["note"] = "binary or unreadable: change reported without line counts"
    if oversize:
        entry["note"] = "oversize: change reported without line counts"
    return entry


