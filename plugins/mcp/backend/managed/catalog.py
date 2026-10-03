"""T05 managed domain (L0/L1): the ``McpToolCatalog`` observation record.

A catalog is, and may only ever be, the result of one ``tools/list``
observation taken over a live connected managed lease (contracts.md §1
"不能把定义条目伪装为活连接"):

* this module refuses to store an observation whose lease is not in
  ``connected``/``catalog-observed`` state;
* without such an observation the public read path
  (:meth:`backend.managed.session_manager.ManagedSessionManager.list_tools_for_definition`)
  answers ``MCP_CATALOG_MISSING`` - a stored definition is never dressed up
  as a live connection;
* digests are deterministic (sorted names, sha256 over the canonical
  content, ``sha256:`` prefix - the same rule as the definition store);
* a re-observation whose digest differs **supersedes** the old one: the old
  digest stops being current, a ``catalog-changed`` fact is written, and
  every approval frozen against the old digest goes stale (the lease's
  approved set never absorbs new tools automatically - FR-04).

Persistence: ``<root>/managed/catalogs.json``, one domain-owned JSON table,
flock + staging + ``os.replace`` like every sibling store. ``serverInfo``
and per-tool schema digests are non-secret; schema bodies themselves are
not stored, only their digests.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence, Tuple

from ..definition import definition_digest
from ..errors import MCP_ASSET_MISSING, MCP_CATALOG_UNOBSERVABLE, McpError
from .lease import McpConnectionLease

# T014 converge: MCP_CATALOG_UNOBSERVABLE is registered in backend/errors.py;
# this module keeps re-exporting the name (reported in reports/t05-domain.md).

CATALOG_STATUS_CURRENT = "current"
CATALOG_STATUS_SUPERSEDED = "superseded"
#: the only lease states a tools/list observation may be taken in; the
#: manager gates earlier, the store guards again (defence in depth).
_OBSERVABLE_LEASE_STATES = frozenset({"connected", "catalog-observed"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tool_schema_digest(tool: Mapping[str, Any]) -> str:
    """Deterministic digest of one observed tool descriptor (name+schema)."""
    if not isinstance(tool, Mapping):
        raise McpError(MCP_ASSET_MISSING, "a tool observation must be an object")
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        raise McpError(MCP_ASSET_MISSING, "an observed tool must carry a name")
    return definition_digest({"name": name, "inputSchema": tool.get("inputSchema")})


def catalog_digest_of(
    *, definition_id: str, revision: int, protocol_version: str,
    tools: Sequence[Sequence[str]],
) -> str:
    """Digest over (name, schemaDigest) pairs, order-normalised.

    ``serverInfo`` / ``observedAt`` deliberately stay out of the digest:
    drift means tool-set or schema drift, not a server restart stamp.
    """
    return definition_digest({
        "definition_id": definition_id,
        "revision": revision,
        "protocol_version": protocol_version,
        "tools": [list(pair) for pair in sorted(tuple(t) for t in tools)],
    })


@dataclass(frozen=True)
class McpToolCatalog:
    """One catalog observation (docs/design/mcp/data-model.md)."""
    lease_id: str
    definition_id: str
    revision: int
    observed_at: str
    protocol_version: str
    server_info: Mapping[str, Any]
    tool_names_and_schema_digests: Tuple[Tuple[str, str], ...]
    catalog_digest: str
    source_evidence: Mapping[str, Any]
    status: str

    @property
    def tool_names(self) -> Tuple[str, ...]:
        return tuple(name for name, _ in self.tool_names_and_schema_digests)


def _model(record: Mapping[str, Any]) -> McpToolCatalog:
    return McpToolCatalog(
        lease_id=record["lease_id"],
        definition_id=record["definition_id"],
        revision=int(record["revision"]),
        observed_at=record["observed_at"],
        protocol_version=record["protocol_version"],
        server_info=dict(record["server_info"]),
        tool_names_and_schema_digests=tuple(
            (str(name), str(digest))
            for name, digest in record["tool_names_and_schema_digests"]),
        catalog_digest=record["catalog_digest"],
        source_evidence=dict(record["source_evidence"]),
        status=record["status"],
    )


class McpToolCatalogStore:
    """Append-only store of catalog observations with current-pointer reads."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- plumbing -----------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        (self.root / "managed").mkdir(parents=True, exist_ok=True)
        with open(self.root / "managed" / ".lock", "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _table_path(self) -> Path:
        return self.root / "managed" / "catalogs.json"

    def _load(self) -> dict:
        path = self._table_path()
        if not path.is_file():
            return {"version": 1, "observations": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _commit(self, table: dict) -> None:
        path = self._table_path()
        staging = Path(tempfile.mkdtemp(prefix="mcp-catalog-", dir=str(path.parent)))
        try:
            tmp = staging / "catalogs.json"
            tmp.write_text(
                json.dumps(table, sort_keys=True, separators=(",", ":"), indent=1),
                encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

    # -- writes ---------------------------------------------------------------------

    def record_observation(
        self, lease: McpConnectionLease, *, tools: Sequence[Mapping[str, Any]],
        protocol_version: str, server_info: Mapping[str, Any],
    ) -> McpToolCatalog:
        """Store one tools/list observation for a live connected lease.

        Returns the new catalog; ``status`` is ``current`` and any earlier
        observation of the same (definitionId, revision) becomes
        ``superseded`` (its digest stops being current -> drift).
        """
        if lease.state not in _OBSERVABLE_LEASE_STATES:
            raise McpError(
                MCP_CATALOG_UNOBSERVABLE,
                "a catalog may only be observed over a connected managed lease "
                f"(lease is in state {lease.state!r})",
            )
        pairs = sorted({(tool["name"], tool_schema_digest(tool)) for tool in tools})
        digest = catalog_digest_of(
            definition_id=lease.definition_id, revision=lease.revision,
            protocol_version=protocol_version, tools=pairs)
        record = {
            "lease_id": lease.lease_id,
            "definition_id": lease.definition_id,
            "revision": lease.revision,
            "observed_at": _now(),
            "protocol_version": protocol_version,
            "server_info": {
                "name": server_info.get("name"), "version": server_info.get("version"),
            },
            "tool_names_and_schema_digests": [list(pair) for pair in pairs],
            "catalog_digest": digest,
            "source_evidence": {
                "origin": "tools-list",
                "lane": lease.lane,
                "lease_state_observed_from": lease.state,
                "endpoint_fingerprint": lease.endpoint_fingerprint,
            },
            "status": CATALOG_STATUS_CURRENT,
        }
        with self._lock():
            table = self._load()
            observations = table["observations"]
            for earlier in observations:
                if (earlier["definition_id"] == lease.definition_id
                        and int(earlier["revision"]) == lease.revision):
                    earlier["status"] = CATALOG_STATUS_SUPERSEDED
            observations.append(record)
            self._commit(table)
        return _model(record)

    # -- reads ------------------------------------------------------------------------

    def _all(self) -> list:
        with self._lock():
            observations = self._load()["observations"]
        return [_model(record) for record in observations]

    def latest(self, *, definition_id: str, revision: int) -> Optional[McpToolCatalog]:
        found = [
            catalog for catalog in self._all()
            if catalog.definition_id == definition_id and catalog.revision == revision
        ]
        return found[-1] if found else None

    def latest_for_lease(self, lease_id: str) -> Optional[McpToolCatalog]:
        found = [c for c in self._all() if c.lease_id == lease_id]
        return found[-1] if found else None

    def is_digest_current(self, *, definition_id: str, revision: int,
                          catalog_digest: str) -> bool:
        latest = self.latest(definition_id=definition_id, revision=revision)
        return latest is not None and latest.catalog_digest == catalog_digest

    def observations_for_lease(self, lease_id: str) -> Tuple[McpToolCatalog, ...]:
        return tuple(c for c in self._all() if c.lease_id == lease_id)


def make_catalog_provider(
    store: McpToolCatalogStore,
) -> Callable[[str, int], Optional[Mapping[str, object]]]:
    """Read adapter matching the ``resolve.resolve_preview`` seam.

    ``catalog_provider(definition_id, revision)`` returns
    ``{"catalogDigest": .., "toolNames": [..]}`` for the latest observed
    catalog of that revision, or ``None`` when nothing was ever observed.
    Injecting this makes a drift between a frozen ``toolSelection`` digest
    and the live observation mark the snapshot ``needs-revalidation``.
    """
    def provider(definition_id: str,
                 revision: int) -> Optional[Mapping[str, object]]:
        latest = store.latest(definition_id=definition_id, revision=revision)
        if latest is None:
            return None
        return {"catalogDigest": latest.catalog_digest, "toolNames": list(latest.tool_names)}
    return provider
