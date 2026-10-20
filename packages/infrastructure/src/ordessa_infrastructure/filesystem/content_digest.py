"""Fail-closed content hashing for regular files and deterministic trees."""
import hashlib
import json
from pathlib import Path


def content_digest(path: object) -> str:
    """The single formal source-integrity digest; strict and fail closed.

    Regular files hash by content; directories hash as a canonical sorted
    tree listing.  Missing sources, symlinked sources, symlinks or special
    files inside a tree, and any other filesystem shape are rejected — a
    Harness that needs a sanitized snapshot must prepare an execution-local
    source before declaring it; the assembler never rewrites sources.
    """
    path = Path(path)
    if not path.exists() or path.is_symlink():
        raise ValueError("runtime source is unavailable or symlinked")
    if path.is_file():
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.is_dir():
        raise ValueError("runtime source must be a regular file or directory")
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("runtime source contains symlink or special file")
        rows.append((item.relative_to(path).as_posix(), "dir" if item.is_dir() else "file",
                     "" if item.is_dir() else hashlib.sha256(item.read_bytes()).hexdigest()))
    return "sha256:" + hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
