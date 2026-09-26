"""Order 58 G7: a directory-shaped hub - snapshot first, install on request.

A *source* is a directory the operator points us at (a checked-out skills
repository, a community mirror): it holds an ``index.json`` listing entries,
each naming its kind, a payload path relative to the source root, and the
provenance string the entry came from. The rules are order 57's, restated for
assets:

* **list first, install later**: syncing only reads the index into a local
  snapshot, so a listing is drawable immediately and installing is a separate,
  user-driven act;
* **pinned provenance**: the snapshot records its own digest, and every entry
  keeps the ``origin`` the index stated. An install records that origin, and a
  later sync that changes the index writes a *new* snapshot - it never rewrites
  what was installed;
* **a failed sync lands nothing**: the snapshot is staged and renamed, so an
  invalid index or a read error leaves the previous snapshot untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

KINDS = ("skill", "mcp")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_MAX_ENTRIES = 512
_MAX_INDEX_BYTES = 1024 * 1024


class CatalogError(RuntimeError):
    """A typed refusal of one catalog operation."""

    def __init__(self, code: str, message: str, *, entry: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.entry = entry


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
                               entry=str(name))
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise CatalogError("CATALOG_INVALID", "entry name must be a lowercase slug",
                               entry=str(name))
        if (not isinstance(path, str) or not path or path.startswith("/")
                or ".." in path.split("/") or "\x00" in path):
            raise CatalogError("CATALOG_INVALID", "entry path must stay inside the source",
                               entry=name)
        if not isinstance(origin, str) or not origin:
            raise CatalogError("CATALOG_ORIGIN_MISSING",
                               "every entry states where it came from", entry=name)
        if (kind, name) in seen:
            raise CatalogError("CATALOG_INVALID", "duplicate entry", entry=name)
        seen.add((kind, name))
        entry = {"kind": kind, "name": name, "path": path, "origin": origin}
        description = raw.get("description")
        if description is not None:
            if not isinstance(description, str) or len(description) > 512:
                raise CatalogError("CATALOG_INVALID", "description must be short text",
                                   entry=name)
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
        if _NAME.fullmatch(source_id) is None:
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

    def annotate(
        self, snapshot: Mapping[str, Any], *, installed: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        """Per-entry install annotations, computed from the catalogue.

        `installed` maps "<kind>:<name>" to the digest currently published for
        it; an entry whose origin's bytes changed cannot be detected here (the
        payload is only read at install time), so the annotation says exactly
        two things: installed, and at which recorded digest.
        """
        annotated: list[dict[str, Any]] = []
        for entry in snapshot.get("entries", ()):
            key = f"{entry['kind']}:{entry['name']}"
            digest = installed.get(key)
            annotated.append({**entry, "installed": digest is not None,
                              "installedDigest": digest})
        return annotated

    def install_entry(
        self, *, snapshot: Mapping[str, Any], entry_name: str, revision: int,
        records, skills, mcp,
    ) -> dict[str, Any]:
        """Install one catalogue entry as a revision (a user-driven act).

        The install goes through the ordinary stores, so every format rule
        still applies; what the catalogue adds is the pinned provenance: the
        published row records ``<source digest>:<entry origin>``, and the
        payload is read from the source the snapshot names - never from
        wherever the caller happens to point.
        """
        entry = None
        for candidate in snapshot.get("entries", ()):
            if candidate["name"] == entry_name:
                entry = candidate
                break
        if entry is None:
            raise CatalogError("CATALOG_ENTRY_UNKNOWN", "no such entry in the snapshot",
                               entry=entry_name)
        payload = self.payload_path(snapshot, entry_name)
        origin = f"{snapshot['digest']}:{entry['origin']}"
        if entry["kind"] == "skill":
            facts = skills.install(payload, asset_id=entry_name, revision=revision)
            digest = facts["tree_digest"]
            name = facts["name"]
            description = facts["description"]
            kind = "skill"
        else:
            definition = json.loads(payload.read_text(encoding="utf-8"))
            facts = mcp.install(definition, asset_id=entry_name, revision=revision)
            from ordessa_server_compat.assets.mcp import definition_digest

            digest = definition_digest(mcp.read(asset_id=entry_name, revision=revision))
            name = facts["name"]
            description = None
            kind = "mcp"
        published = records.publish(
            key=f"catalog:{snapshot['digest']}:{entry_name}:{revision}",
            request_digest=f"{snapshot['digest']}:{entry_name}:{revision}",
            kind=kind, name=name, revision=revision, digest=digest,
            description=description, source=origin, asset_id=entry_name,
        )[1]
        return {"asset_id": published["asset_id"], "kind": kind, "name": name,
                "revision": revision, "digest": digest, "source": origin}

    def payload_path(self, snapshot: Mapping[str, Any], entry_name: str) -> Path:
        """Resolve one entry's payload inside the source it came from."""
        for entry in snapshot.get("entries", ()):
            if entry["name"] == entry_name:
                source = Path(str(snapshot["source_path"])).resolve()
                target = (source / entry["path"]).resolve()
                if not target.is_relative_to(source):
                    raise CatalogError("CATALOG_INVALID",
                                       "the entry escapes its source", entry=entry_name)
                if not target.exists():
                    raise CatalogError("CATALOG_SOURCE_MISSING",
                                       "the entry payload is not there", entry=entry_name)
                return target
        raise CatalogError("CATALOG_ENTRY_UNKNOWN", "no such entry in the snapshot",
                           entry=entry_name)
