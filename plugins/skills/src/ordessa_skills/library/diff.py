"""Revision-to-revision diff and bounded preview (diff.py).

Legacy predecessor: `plugins/assets/src/ordessa_assets/server/service.py`
@ 752f148b1b — `diff()` (existence/bytes/sha256 map diff, :69-82 with
`_file_map` :140) and `skill_preview()` (bounded textual preview with the
script flag, :44-67). plan.md 原有 Assets-Skill 迁移 splits that façade: the
generic Assets surface (mcp/command/plugin) stays with its old owner, while
these two skill-content reads land here (research-and-reuse.md 旧 AssetsService
row: Skill 管理部分留一个服务).

Guarantees (verification.md G02):

* a preview reads **only** files inside one installed revision — the path is
  shape-checked and then resolved with `assert_regular_within`, so an absolute
  path, a `..` traversal, a NUL and a symlink all refuse (「preview 读任意文
  件」 counter-example);
* text is size-bounded by `MAX_PREVIEW_BYTES`, the same bound the legacy
  service carried;
* diffing and previewing never execute or interpret content: files are read as
  bytes, hashed, and (for text) decoded only to be shown (「导入即执行脚本」).
"""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Any

from ..api.errors import AssetDomainError, PreviewError, SkillAssetError
from ..formats.agent_skills.tree import scan_tree
from ..formats.agent_skills.validator import assert_regular_within
from .store import SkillRevisionStore

#: The legacy service bound (service.py:21) — 256 KiB of text per read.
MAX_PREVIEW_BYTES = 256 * 1024
#: And the same bound caps one unified text preview between two revisions, so
#: a "what changed" view cannot be used to stream an arbitrary amount of text.
MAX_DIFF_TEXT_BYTES = 256 * 1024

#: The file the Agent Skills format guarantees, hence the default text target.
SKILL_MANIFEST = "SKILL.md"


def _checked_relative(relative: str) -> str:
    """Reject a path shape that could leave one revision tree, before any read."""
    if (not isinstance(relative, str) or not relative
            or relative.startswith("/") or "\x00" in relative
            or ".." in Path(relative).parts):
        raise PreviewError("PREVIEW_REFUSED",
                           "only files inside the revision may be previewed",
                           detail=str(relative))
    return relative


def file_map(store: SkillRevisionStore, asset_id: str,
             revision: int) -> dict[str, tuple[int, str]]:
    """`{relative path: (bytes, sha256 hex)}` for one installed revision."""
    directory = store.revision_dir(asset_id, revision)
    if not directory.is_dir():
        raise AssetDomainError("SKILL_ASSET_MISSING",
                               "the skill revision is not installed")
    mapping = {}
    for entry in scan_tree(directory):
        data = entry.path.read_bytes()
        mapping[entry.relative] = (entry.size, hashlib.sha256(data).hexdigest())
    return mapping


def diff_revisions(store: SkillRevisionStore, *, asset_id: str, from_revision: int,
                   to_revision: int) -> dict[str, Any]:
    """File-level differences between two revisions (existence/bytes/digest).

    Byte-identical to the legacy `AssetsService.diff` response shape.
    """
    old = file_map(store, asset_id, from_revision)
    new = file_map(store, asset_id, to_revision)
    return {
        "assetId": asset_id,
        "fromRevision": from_revision,
        "toRevision": to_revision,
        "changed": sorted(path for path in set(old) & set(new)
                          if old[path] != new[path]),
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
    }


def read_revision_text(store: SkillRevisionStore, *, asset_id: str, revision: int,
                       path: str) -> str | None:
    """One revision's file as text, or None when that revision lacks the file.

    A file that exists only in one of two revisions is an added/removed row,
    not a refusal; anything that is not a regular file inside the tree is.
    """
    _checked_relative(path)
    directory = store.revision_dir(asset_id, revision)
    if not directory.is_dir():
        raise AssetDomainError("SKILL_ASSET_MISSING",
                               "the skill revision is not installed")
    candidate = directory / path
    if candidate.is_symlink():
        # A link is not an absent file: it is a refusal (G02 symlink escape).
        raise PreviewError("PREVIEW_REFUSED",
                           f"cannot preview {path}",
                           detail="a revision may hold only regular files")
    try:
        target = assert_regular_within(directory, path)
    except SkillAssetError as refusal:
        if refusal.code == "SKILL_ASSET_MISSING":
            return None
        raise PreviewError("PREVIEW_REFUSED", f"cannot preview {path}",
                           detail=refusal.message) from refusal
    data = target.read_bytes()
    if len(data) > MAX_PREVIEW_BYTES:
        raise PreviewError("PREVIEW_REFUSED", "the file exceeds the preview bound",
                           detail=path)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreviewError("PREVIEW_REFUSED", "only text previews are served",
                           detail=path) from exc


def preview_file(store: SkillRevisionStore, *, asset_id: str, revision: int,
                 path: str) -> dict[str, Any]:
    """A bounded, textual, never-executing preview of one stored file."""
    directory = store.revision_dir(asset_id, revision)
    _checked_relative(path)
    if not directory.is_dir():
        raise AssetDomainError("SKILL_ASSET_MISSING",
                               "the skill revision is not installed")
    try:
        target = assert_regular_within(directory, path)
    except AssetDomainError as refusal:
        raise PreviewError("PREVIEW_REFUSED",
                           f"cannot preview {path}", detail=refusal.message) from refusal
    data = target.read_bytes()
    if len(data) > MAX_PREVIEW_BYTES:
        raise PreviewError("PREVIEW_REFUSED", "the file exceeds the preview bound",
                           detail=path)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreviewError("PREVIEW_REFUSED", "only text previews are served",
                           detail=path) from exc
    executable = target.stat().st_mode & 0o111
    return {
        "path": path,
        "bytes": len(data),
        "text": text,
        "script": path.startswith("scripts/") or bool(executable),
    }


def text_diff(store: SkillRevisionStore, *, asset_id: str, from_revision: int,
              to_revision: int, path: str = SKILL_MANIFEST,
              max_bytes: int = MAX_DIFF_TEXT_BYTES) -> dict[str, Any]:
    """A bounded unified text preview of one file between two revisions.

    FR07 「可预览 diff」: the upgrade act shows what changes. `truncated` is
    reported, never silently dropped, and the whole read stays inside the two
    revision trees.
    """
    old = read_revision_text(store, asset_id=asset_id, revision=from_revision, path=path)
    new = read_revision_text(store, asset_id=asset_id, revision=to_revision, path=path)
    lines = list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(),
        fromfile=f"r{from_revision}/{path}", tofile=f"r{to_revision}/{path}",
        lineterm=""))
    body: list[str] = []
    held = 0
    truncated = False
    for line in lines:
        held += len(line.encode("utf-8")) + 1
        if held > max_bytes:
            truncated = True
            break
        body.append(line)
    return {
        "assetId": asset_id,
        "path": path,
        "fromRevision": from_revision,
        "toRevision": to_revision,
        "changed": old != new,
        "unified": body,
        "bytes": held,
        "truncated": truncated,
    }
