"""Order 091: control-plane -> execution-side sync engine (transport-agnostic).

R-0012 makes the Windows control plane the sole authority for the sync set -
profile records (with configuration, permission posture and model slots),
provider/model records and workspace records - and the execution side a bounded,
re-derivable *projection* with a deployment manifest, never a second
authoritative store. Credentials are never in this set: their content stays on
the control plane and reaches an execution only as the per-attempt ephemeral
projection the existing launch path already performs; this module only guarantees
secret-shaped material can never be written into a synced record.

The engine is deliberately pure and transport-agnostic: it turns control-plane
records into a content-addressed manifest, applies it to an execution-side
projection idempotently (version + digest), and refuses execution-side local
edits so "Windows wins" is structural, not a convention. It is independent of
*how* the manifest physically reaches a remote worker (that transport is the
order's open ruling); it is the logic every transport must share.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ordessa_server.records import digest as _digest, reject_sensitive_keys

#: The sync set, in one fixed order. A record kind outside this set is refused
#: by name rather than silently synced or silently dropped.
SYNC_SET = ("profile", "provider-model", "workspace")

#: What is *never* synced, kept explicit so "not delivered" is a stated rule,
#: not an omission: native home, sessions/transcripts (per platform, order 45),
#: and credential content (control-plane only).
NOT_SYNCED = ("native-home", "session", "transcript", "credential-content")


class ControlPlaneSyncError(RuntimeError):
    """A typed refusal in the sync path (unknown kind, or an execution-side edit)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SyncItem:
    """One sync-set record as the control plane sees it (secret-free body)."""

    kind: str
    id: str
    version: int
    body: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.id)

    @property
    def digest(self) -> str:
        return _digest({"kind": self.kind, "id": self.id, "version": self.version,
                        "body": dict(self.body)})


@dataclass(frozen=True)
class ManifestEntry:
    kind: str
    id: str
    version: int
    digest: str


@dataclass(frozen=True)
class DeploymentManifest:
    """The deployment ledger: one line per sync-set record + an order digest."""

    entries: tuple[ManifestEntry, ...]

    @property
    def manifest_digest(self) -> str:
        return _digest([{"kind": e.kind, "id": e.id, "version": e.version,
                         "digest": e.digest} for e in self.entries])

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "manifestDigest": self.manifest_digest,
            "items": [{"kind": e.kind, "id": e.id, "version": e.version,
                       "digest": e.digest} for e in self.entries],
        }


def _validate(item: SyncItem) -> None:
    if item.kind not in SYNC_SET:
        raise ControlPlaneSyncError(
            "SYNC_KIND_UNSUPPORTED",
            f"{item.kind!r} is not in the control-plane sync set {SYNC_SET}",
        )
    # Credential content can never be a synced field; reject_sensitive_keys
    # raises ServerError("SECRET_FIELD_FORBIDDEN") on any secret-shaped key, so
    # G3's "zero persisted secret" holds before anything reaches the projection.
    reject_sensitive_keys(dict(item.body))


def plan_deployment(items: Iterable[SyncItem]) -> DeploymentManifest:
    """Freeze the sync set into a manifest of per-item digests (pure)."""
    entries: list[ManifestEntry] = []
    for item in items:
        _validate(item)
        entries.append(ManifestEntry(item.kind, item.id, item.version, item.digest))
    return DeploymentManifest(tuple(sorted(entries, key=lambda e: (e.kind, e.id))))


@dataclass
class _Record:
    version: int
    digest: str
    body: Mapping[str, Any]


@dataclass
class SyncReport:
    applied: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # How many times each record was actually written - proves idempotent replay
    # (a re-delivered version must not bump its own apply count).
    apply_count: dict[str, int] = field(default_factory=dict)


class ExecutionSideProjection:
    """The execution side's bounded, re-derivable view of the sync set.

    Writes enter only through ``apply``/``apply_incremental`` (control-plane
    deliveries). ``local_edit`` exists solely to *refuse* an execution-side edit -
    the control plane is the only author, so "Windows wins" is enforced here.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _Record] = {}

    def get(self, kind: str, id: str) -> _Record | None:
        return self._records.get((kind, id))

    def apply(self, manifest: DeploymentManifest, items: Sequence[SyncItem]) -> SyncReport:
        """Idempotent first-deploy / full-sync: apply changed versions, drop absent."""
        by_key = {item.key: item for item in items}
        report = SyncReport()
        seen: set[tuple[str, str]] = set()
        for entry in manifest.entries:
            key = (entry.kind, entry.id)
            seen.add(key)
            item = by_key.get(key)
            if item is None:
                raise ControlPlaneSyncError(
                    "SYNC_MANIFEST_BODY_MISSING", f"no body for {entry.kind}/{entry.id}")
            _validate(item)
            if item.digest != entry.digest or item.version != entry.version:
                raise ControlPlaneSyncError(
                    "SYNC_MANIFEST_MISMATCH",
                    f"{entry.kind}/{entry.id} body drifted from its manifest line")
            report.apply_count.setdefault(f"{entry.kind}:{entry.id}", 0)
            existing = self._records.get(key)
            if existing is not None and existing.version == entry.version \
                    and existing.digest == entry.digest:
                report.unchanged.append(f"{entry.kind}:{entry.id}")
                continue
            self._records[key] = _Record(entry.version, entry.digest, dict(item.body))
            report.applied.append(f"{entry.kind}:{entry.id}")
            report.apply_count[f"{entry.kind}:{entry.id}"] += 1
        for key in list(self._records):
            if key not in seen:
                del self._records[key]
                report.removed.append(f"{key[0]}:{key[1]}")
        return report

    def apply_incremental(self, item: SyncItem) -> str:
        """Deliver one changed record; a re-delivery of the same version is a no-op."""
        _validate(item)
        key = item.key
        existing = self._records.get(key)
        if existing is not None and existing.version == item.version \
                and existing.digest == item.digest:
            return "unchanged"
        self._records[key] = _Record(item.version, item.digest, dict(item.body))
        return "applied"

    def local_edit(self, kind: str, id: str, body: Mapping[str, Any]) -> None:
        """Refuse an execution-side authoring attempt - the control plane wins."""
        authoritative = self._records.get((kind, id))
        raise ControlPlaneSyncError(
            "CONTROL_PLANE_AUTHORITY",
            f"the execution side cannot edit {kind}/{id}; "
            f"authoritative version {authoritative.version if authoritative else 'none'} "
            "lives on the Windows control plane - edit it there")


def verify_parity(projection: ExecutionSideProjection,
                  manifest: DeploymentManifest) -> list[str]:
    """Return the manifest lines not faithfully present on the execution side."""
    problems: list[str] = []
    for entry in manifest.entries:
        record = projection.get(entry.kind, entry.id)
        if record is None:
            problems.append(f"{entry.kind}:{entry.id}=missing")
        elif record.version != entry.version or record.digest != entry.digest:
            problems.append(f"{entry.kind}:{entry.id}=diverged")
    return problems


def collect_sync_snapshot(*, profiles: Sequence[Mapping[str, Any]],
                          provider_models: Sequence[Mapping[str, Any]],
                          workspaces: Sequence[Mapping[str, Any]]) -> list[SyncItem]:
    """Adapt real control-plane repository rows into secret-free SyncItems.

    Only identity + version + the record's *public* body travel; a credential is
    referenced by id/kind only, never by content, and ``_validate`` rejects any
    secret-shaped key that could ever slip in.
    """
    items: list[SyncItem] = []
    for row in profiles:
        items.append(SyncItem("profile", str(row["profile_id"]), int(row["version"]),
                              _public_body(row, {"profile_id", "version"})))
    for row in provider_models:
        items.append(SyncItem("provider-model", str(row["id"]), int(row["version"]),
                              _public_body(row, {"id", "version"})))
    for row in workspaces:
        items.append(SyncItem("workspace", str(row["id"]), int(row["version"]),
                              _public_body(row, {"id", "version"})))
    return items


def _public_body(row: Mapping[str, Any], drop: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in drop}
