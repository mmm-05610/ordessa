"""Order 63: reading a Profile's memory files - declared, bounded, scanned.

"Memory" here is what the *Harness itself* writes and reads back (Codex's
`memories/MEMORY.md`, Claude Code's `.claude/CLAUDE.md`): the registry declares
each family's paths, and this reader only ever touches those. Four rules, each
with a counterexample in the tests:

* **declared paths only** - the file list is the declaration, never a walk of
  the home ("顺手把家列一遍" is exactly what the order forbids);
* **bounded** - a per-file cap, an entry cap and a total-byte cap; exceeding
  one is a typed refusal, not a quietly shorter answer;
* **scanned before returned** - order 45's credential rule applies to every
  file: a hit means that file is *refused* (typed), and its content never
  reaches a log or an answer;
* **read-only and link-free** - the file is opened `O_NOFOLLOW` inside the
  native home; a symlink is refused rather than followed, and nothing is ever
  written.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Iterable, Sequence

MAX_MEMORY_FILE_BYTES = 64 * 1024
MAX_MEMORY_TOTAL_BYTES = 256 * 1024
MAX_MEMORY_FILES = 8

REASONS = (
    "MEMORY_HOME_MISSING", "MEMORY_FILE_OUTSIDE_BOUNDS", "MEMORY_FILE_UNSAFE",
    "MEMORY_READ_FAILED", "MEMORY_UNAVAILABLE",
)


def read_memory(
    home: Path | str | None, *, declared: Sequence[str], forbidden: bytes | None = None,
) -> dict[str, Any]:
    """Read the declared memory files under one Profile's native home.

    Returns ``{"available": bool, "reason": str | None, "files": [...]}``;
    each file is ``{path, size, digest, content?}``. A declared file that is
    not there is simply **absent** (never an empty string), a file carrying
    credential material is refused with its own reason, and a missing home is
    the one reason that covers the whole answer.
    """
    paths = tuple(str(item) for item in declared)[:MAX_MEMORY_FILES]
    if home is None:
        return {"available": False, "reason": "MEMORY_HOME_MISSING", "files": []}
    root = Path(home)
    if not root.is_dir():
        return {"available": False, "reason": "MEMORY_HOME_MISSING", "files": []}
    files: list[dict[str, Any]] = []
    total = 0
    reason: str | None = None
    for relative in paths:
        if not relative or relative.startswith("/") or ".." in relative.split("/"):
            reason = reason or "MEMORY_FILE_UNSAFE"
            continue
        target = root.joinpath(*relative.split("/"))
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            continue  # a declared file that is not there is simply absent
        except OSError:
            reason = reason or "MEMORY_READ_FAILED"
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            reason = reason or "MEMORY_FILE_UNSAFE"
            continue
        if info.st_size > MAX_MEMORY_FILE_BYTES or total + info.st_size > MAX_MEMORY_TOTAL_BYTES:
            reason = reason or "MEMORY_FILE_OUTSIDE_BOUNDS"
            continue
        try:
            handle = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(handle, "rb") as stream:
                content = stream.read(MAX_MEMORY_FILE_BYTES + 1)
        except OSError:
            reason = reason or "MEMORY_READ_FAILED"
            continue
        if len(content) > MAX_MEMORY_FILE_BYTES:
            reason = reason or "MEMORY_FILE_OUTSIDE_BOUNDS"
            continue
        if forbidden and forbidden in content:
            # The file is refused as a whole: its content must not be returned
            # and must not be logged. The reason names the file, never bytes.
            files.append({"path": relative, "size": len(content),
                          "reason": "MEMORY_CONTAINS_SECRET", "refused": True})
            continue
        total += len(content)
        files.append({
            "path": relative,
            "size": len(content),
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "content": content.decode("utf-8", errors="replace"),
        })
    return {"available": True, "reason": reason, "files": files}


def memory_paths_for(registry_profile: Any) -> tuple[str, ...]:
    """The family's declared memory paths (empty when it declares none)."""
    return tuple(getattr(registry_profile, "memory_paths", ()) or ())
