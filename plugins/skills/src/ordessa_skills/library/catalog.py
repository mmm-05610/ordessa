"""Directory-shaped sources: snapshot first, install on request (catalog.py).

Ported unchanged from `plugins/assets/src/ordessa_assets/server/catalog.py`
@ 752f148b1b (research-and-reuse.md 目录/版本/元数据 row). The snapshot path
`<assets root>/catalogs/<source_id>/index.json`, the `schema_version` 1 index
and its canonical-JSON digest are preserved identifiers (legacy-inventory.md
§B.2); kind `mcp` entries are parsed for wire compatibility but never
installed from here (plan.md: 旧表其他 kind 由迁移账指定旧业务所有者).

A failed sync lands nothing; an install pins its provenance to
`<snapshot digest>:<origin>`; syncing and installing never touch bindings.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from ..api.errors import CatalogError
from .records import AssetRecords
from .store import SkillRevisionStore

KINDS = ("skill", "mcp")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_MAX_ENTRIES = 512
_MAX_INDEX_BYTES = 1024 * 1024


def parse_index(content: bytes) -> dict[str, Any]:
    """Validate one source index and return its canonical snapshot facts."""
    if len(content) > _MAX_INDEX_BYTES:
        raise CatalogError("CATALOG_INVALID", "the index exceeds the size bound")
    try:
        document = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CatalogError("CATALOG_INVALID", "the index is not readable JSON") from exc
    if (not isinstance(document, dict)
            or document.get("schema_version") != 1
            or not isinstance(document.get("entries"), list)
            or len(document["entries"]) > _MAX_ENTRIES):
        raise CatalogError("CATALOG_INVALID", "the index shape is unknown")
    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in document["entries"]:
        if not isinstance(raw, dict) or set(raw) - {"kind", "name", "path", "origin",
                                                   "description"}:
            raise CatalogError("CATALOG_INVALID", "an entry has unknown fields")
        kind = raw.get("kind")
        name = raw.get("name")
        path = raw.get("path")
        origin = raw.get("origin")
        if kind not in KINDS:
            raise CatalogError("CATALOG_INVALID", f"entry kind {kind!r} is not served",
                               detail=str(name))
        if not isinstance(name, str) or _SLUG.fullmatch(name) is None:
            raise CatalogError("CATALOG_INVALID", "entry name must be a lowercase slug",
                               detail=str(name))
        if (not isinstance(path, str) or not path or path.startswith("/")
                or ".." in path.split("/") or "\x00" in path):
            raise CatalogError("CATALOG_INVALID", "entry path must stay inside the source",
                               detail=str(name))
        if not isinstance(origin, str) or not origin:
            raise CatalogError(
                "CATALOG_ORIGIN_MISSING", "every entry states where it came from",
                detail=str(name))
        if (kind, name) in seen:
            raise CatalogError("CATALOG_INVALID", "duplicate entry", detail=name)
        seen.add((kind, name))
        entry = {"kind": kind, "name": name, "path": path, "origin": origin}
        description = raw.get("description")
        if description is not None:
            if not isinstance(description, str) or len(description) > 512:
                raise CatalogError("CATALOG_INVALID", "description must be short text",
                                   detail=str(name))
            entry["description"] = description
        entries.append(entry)
    canonical = json.dumps({"schema_version": 1, "entries": entries},
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "entries": entries,
        "digest": "sha256:" + hashlib.sha256(canonical).hexdigest(),
    }


class CatalogStore:
    """Local snapshots of directory-shaped sources."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def snapshot_path(self, source_id: str) -> Path:
        if _SLUG.fullmatch(source_id) is None:
            raise CatalogError("CATALOG_INVALID", "source_id must be a lowercase slug")
        return self.root / source_id / "index.json"

    def sync(self, *, source_id: str, source_path: Path | str) -> dict[str, Any]:
        """Read one source directory into a fresh snapshot (or refuse).

        Nothing is written until the index has parsed: an invalid index or a
        missing directory leaves the previous snapshot exactly as it was.
        """
        source = Path(source_path)
        index = source / "index.json"
        if index.is_symlink() or not index.is_file():
            raise CatalogError("CATALOG_SOURCE_MISSING", "the source has no index.json")
        facts = parse_index(index.read_bytes())

        destination = self.snapshot_path(source_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".index-{os.getpid()}.tmp"
        try:
            staging.write_bytes(json.dumps(
                {"schema_version": 1, "source_path": str(source.resolve()),
                 "digest": facts["digest"], "entries": facts["entries"]},
                sort_keys=True, indent=1).encode("utf-8"))
            os.replace(staging, destination)
        except BaseException:
            try:
                staging.unlink()
            except OSError:
                pass
            raise
        return self.snapshot(source_id)

    def snapshot(self, source_id: str) -> dict[str, Any] | None:
        path = self.snapshot_path(source_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def annotate(self, snapshot: Mapping[str, Any], *,
                 installed: Mapping[str, str]) -> list[dict[str, Any]]:
        """Per-entry install annotations, computed from the catalogue."""
        annotated: list[dict[str, Any]] = []
        for entry in snapshot.get("entries", ()):
            key = f"{entry['kind']}:{entry['name']}"
            digest = installed.get(key)
            annotated.append({**entry, "installed": digest is not None,
                              "installedDigest": digest})
        return annotated

    def install_entry(self, *, snapshot: Mapping[str, Any], entry_name: str,
                      revision: int, records: AssetRecords,
                      store: SkillRevisionStore | None = None) -> dict[str, Any]:
        """Install one catalogue entry as a revision (a user-driven act).

        The payload is read from the source the snapshot names — never from
        wherever the caller happens to point — and the published row records
        the pinned provenance. Syncing/installs never touch bindings.
        """
        entry = None
        for candidate in snapshot.get("entries", ()):
            if candidate["name"] == entry_name:
                entry = candidate
                break
        if entry is None:
            raise CatalogError("CATALOG_ENTRY_UNKNOWN", "no such entry in the snapshot",
                               detail=entry_name)
        if entry["kind"] != "skill":
            raise CatalogError(
                "CATALOG_INVALID",
                f"kind {entry['kind']!r} is not owned by the assets-skill domain",
                detail=entry_name)
        payload = self.payload_path(snapshot, entry_name)
        if not (payload / "SKILL.md").is_file() or (payload / "SKILL.md").is_symlink():
            raise CatalogError("CATALOG_SOURCE_MISSING",
                               "the entry payload has no SKILL.md", detail=entry_name)
        origin = f"{snapshot['digest']}:{entry['origin']}"
        skills = store if store is not None else SkillRevisionStore(self.root.parent)
        facts = skills.install(payload, asset_id=entry_name, revision=revision,
                               source_ref=origin)
        published = records.publish(
            kind="skill", name=facts["name"], revision=revision,
            digest=facts["tree_digest"], description=facts["description"],
            source=origin, asset_id=entry_name)[1]
        return {"asset_id": published["asset_id"], "kind": "skill",
                "name": facts["name"], "revision": revision,
                "digest": facts["tree_digest"], "source": origin}

    def payload_path(self, snapshot: Mapping[str, Any], entry_name: str) -> Path:
        """Resolve one entry's payload inside the source it came from."""
        for entry in snapshot.get("entries", ()):
            if entry["name"] == entry_name:
                source = Path(str(snapshot["source_path"])).resolve()
                target = (source / entry["path"]).resolve()
                if not target.is_relative_to(source):
                    raise CatalogError("CATALOG_INVALID", "the entry escapes its source",
                                       detail=entry_name)
                if not target.exists():
                    raise CatalogError("CATALOG_SOURCE_MISSING",
                                       "the entry payload is not there", detail=entry_name)
                return target
        raise CatalogError("CATALOG_ENTRY_UNKNOWN", "no such entry in the snapshot",
                           detail=entry_name)
