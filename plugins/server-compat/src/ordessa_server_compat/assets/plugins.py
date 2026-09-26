"""Order 59: an OpenCode-style hook is *code*, so it is a code asset.

The family's hooks are JavaScript/TypeScript plugins, and the order's rule is
explicit: the user supplies the source, we store it with a digest and show a
preview, and we deliver it - we never assemble code from form fields. So this
store takes exactly one regular text file per revision, keeps it under a
content-addressed revision directory, and derives the preview the UI shows.
There is no schema to validate: the "validation" is that the bytes are text,
bounded, and that the digest a reader sees is the digest a reader gets.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

MAX_PLUGIN_BYTES = 256 * 1024
MAX_PREVIEW_LINES = 24
MAX_PREVIEW_CHARS = 4096
#: The extensions the two observed families load (`.js`/`.ts` under the
#: plugins directory).
PLUGIN_SUFFIXES = (".js", ".mjs", ".ts")


class PluginAssetError(RuntimeError):
    """A typed refusal of one plugin install or read."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def preview_of(content: bytes) -> str:
    """A bounded preview: the first lines, with the truncation visible."""
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()
    preview = "\n".join(lines[:MAX_PREVIEW_LINES])
    if len(preview) > MAX_PREVIEW_CHARS:
        preview = preview[:MAX_PREVIEW_CHARS] + "\n…"
    elif len(lines) > MAX_PREVIEW_LINES:
        preview += "\n…"
    return preview


class PluginAssetStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def revision_dir(self, asset_id: str, revision: int) -> Path:
        return self.root / "plugin" / asset_id / str(revision)

    def install(self, source: Path | str, *, asset_id: str, revision: int) -> dict:
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise PluginAssetError("PLUGIN_ASSET_INVALID", "the source must be a regular file")
        if source.suffix not in PLUGIN_SUFFIXES:
            raise PluginAssetError(
                "PLUGIN_ASSET_INVALID",
                f"the source must end in one of {PLUGIN_SUFFIXES}",
            )
        content = source.read_bytes()
        if not content or len(content) > MAX_PLUGIN_BYTES:
            raise PluginAssetError("PLUGIN_ASSET_OUTSIDE_BOUNDS", "the plugin is empty or oversized")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PluginAssetError(
                "PLUGIN_NOT_TEXT", "a plugin asset must be UTF-8 text") from exc
        destination = self.revision_dir(asset_id, revision)
        if destination.exists():
            raise PluginAssetError(
                "PLUGIN_REVISION_EXISTS", f"revision {revision} of {asset_id} already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="plugin-staging-", dir=str(destination.parent)))
        try:
            target = staging / f"{asset_id}{source.suffix}"
            target.write_bytes(content)
            os.chmod(target, 0o644)
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "asset_id": asset_id,
            "kind": "plugin",
            "revision": revision,
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "filename": f"{asset_id}{source.suffix}",
            "bytes": len(content),
            "preview": preview_of(content),
        }

    def read(self, *, asset_id: str, revision: int) -> tuple[str, bytes]:
        directory = self.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise PluginAssetError("PLUGIN_ASSET_MISSING", "the plugin revision is not installed")
        files = [item for item in sorted(directory.iterdir()) if item.is_file()]
        if len(files) != 1:
            raise PluginAssetError("PLUGIN_ASSET_INVALID", "a plugin revision holds one file")
        return files[0].name, files[0].read_bytes()

    def verify(self, *, asset_id: str, revision: int, expected_digest: str) -> bool:
        _name, content = self.read(asset_id=asset_id, revision=revision)
        return "sha256:" + hashlib.sha256(content).hexdigest() == expected_digest
