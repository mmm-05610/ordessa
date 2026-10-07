"""T05 managed domain (L0/L1): connection leases, sole ownership, state machine.

This module owns the ``McpConnectionLease`` entity and its durable table
(docs/design/mcp/data-model.md). Evidence level is **L0/L1 domain layer**:
no real MCP SDK client and no Pi bridge exist here yet (those are the G2/G4
dependency batches, see specs/011-q4-mcp/reports/t04-t05-research.md); the
only clients usable through this code are the explicitly-labelled in-memory
fakes in :mod:`backend.managed.session_manager`. Nothing here has ever
connected to a real server and no statement in this package may claim one.

Load-bearing invariants implemented here:

* one ``(runtimeGeneration, sessionRef, endpointFingerprint)`` triple holds
  **at most one active lease**; ``refused`` and ``closed`` release the key,
  every other state (including ``unknown``) keeps it occupied;
* the native and managed lanes are mutually exclusive on that same triple:
  a native projection refuses a managed lease and vice versa, both with the
  typed ``MCP_OWNER_CONFLICT`` (harness-adapters.md「避免双启动的机械约束」);
* ``ownerId`` is unique per active lease and close is an owner-only,
  once-effective, idempotently-retryable operation;
* a foreign principal / foreign session probing a lease gets the generic
  ``MCP_LEASE_MISSING`` refusal and never learns the lease exists, let
  alone its content (verification.md counterexample 2);
* a failure whose outcome cannot be confirmed parks the lease in
  ``unknown``; a second lease on the same key is then refused with
  ``MCP_RECONCILE_REQUIRED`` until the owner reconciles - the system never
  "bets" the old client/process exited (FR-10, verification.md
  counterexample 7);
* every state entry is one independent fact record in the lease's fact
  ledger: the FR-02 six-level ladder is never collapsed into a boolean.

Storage policy matches the sibling stores (definition_store.py,
assignment.py): a domain-owned JSON table under the plugin data root, an
exclusive ``fcntl.flock`` around each read-modify-write and an
``os.replace`` commit; the staging-directory writes never expose a partial
file. Facts and errors carry ids and digests only - never credentials,
never argument bodies.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Tuple

from ..definition import (
    McpRevision,
    RemoteTransport,
    StdioTransport,
    definition_digest,
)
from ..errors import (
    MCP_ASSET_MISSING,
    MCP_LEASE_BUSY,
    MCP_LEASE_MISSING,
    MCP_NOT_CONNECTED,
    MCP_OWNER_CONFLICT,
    MCP_RECONCILE_REQUIRED,
    MCP_STATE_TRANSITION_INVALID,
    MCP_TOOL_NOT_APPROVED,
    McpError,
)

# T014 converge: the lease-domain family is registered in backend/errors.py;
# this module keeps re-exporting the names for its consumers (reported in
# specs/011-q4-mcp/reports/t05-domain.md).

LANE_NATIVE = "native"
LANE_MANAGED = "managed"
_LANES = (LANE_NATIVE, LANE_MANAGED)

# docs/design/mcp/data-model.md 状态:
#   defined -> selected -> planned -> connecting -> connected
#           -> catalog-observed -> closing -> closed   (+ refused, + unknown)
LEASE_STATES = (
    "defined", "selected", "planned", "connecting", "connected",
    "catalog-observed", "closing", "closed", "refused", "unknown",
)
#: states that still occupy the ``(generation, sessionRef, fingerprint)`` key.
#: ``refused`` is a *confirmed* no-resource outcome, so it releases the key;
#: ``unknown`` keeps it (counterexample 7: no second lease while the old
#: client's fate is unconfirmed).
ACTIVE_STATES = frozenset(LEASE_STATES) - {"closed", "refused"}
#: states from which a close/drain sequence may run.
CLOSABLE_STATES = frozenset({
    "defined", "selected", "planned", "connecting", "connected", "catalog-observed",
})

#: the only legal (from -> to) pairs. Each legal move appends one independent
#: fact to the lease ledger; anything else is refused typed.
LEGAL_TRANSITIONS: Mapping[str, frozenset] = {
    "defined": frozenset({"selected", "closing"}),
    "selected": frozenset({"planned", "closing"}),
    "planned": frozenset({"connecting", "refused", "closing"}),
    "connecting": frozenset({"connected", "refused", "unknown", "closing"}),
    "connected": frozenset({"catalog-observed", "unknown", "closing"}),
    "catalog-observed": frozenset({"closing", "unknown"}),
    "closing": frozenset({"closed", "unknown", "closing"}),  # closing->closing = drain retry
    "unknown": frozenset({"closed", "connected"}),           # only via reconcile()
    "closed": frozenset(),
    "refused": frozenset(),
}

_RECONCILE_OUTCOMES = ("terminated", "alive")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_lease_id() -> str:
    return "lease-" + str(uuid.uuid4())


def new_owner_id() -> str:
    return "owner-" + str(uuid.uuid4())


def endpoint_fingerprint(revision: McpRevision) -> str:
    """Deterministic endpoint identity of one revision - WITHOUT secrets.

    stdio: executable ref + argv; remote: url. env/header values never
    participate (they may be ``SecretRef`` slots; the credential dimension
    is the lease's ``credential_revision`` field, FR-05).
    """
    transport = revision.transport
    if isinstance(transport, StdioTransport):
        payload: dict = {
            "transport": "stdio",
            "executable_ref": transport.executable_ref,
            "argv": list(transport.argv),
        }
    elif isinstance(transport, RemoteTransport):
        payload = {"transport": "remote", "url": transport.url}
    else:  # pragma: no cover - the revision model has exactly two transports
        raise McpError(MCP_ASSET_MISSING, "the revision transport shape is unknown")
    return definition_digest(payload)


def lease_key(runtime_generation: Any, session_ref: str, fingerprint: str) -> str:
    """Serialised uniqueness key of the data-model triple."""
    return definition_digest({
        "runtime_generation": runtime_generation,
        "session_ref": session_ref,
        "endpoint_fingerprint": fingerprint,
    })


@dataclass(frozen=True)
class LeaseCaller:
    """Who is calling: the identity every lease operation is checked against.

    A lease is only ever visible to the (principal, sessionRef) pair that
    opened it; anything else gets the storage-mirror behaviour of "the
    record is not installed" and learns nothing.
    """
    principal: str
    session_ref: str
    runtime_generation: int


@dataclass(frozen=True)
class McpConnectionLease:
    """One managed-lane connection lease (docs/design/mcp/data-model.md)."""
    lease_id: str
    target_session: str
    runtime_generation: int
    definition_id: str
    revision: int
    lane: str
    owner_id: str
    principal: str
    server_scope: str
    credential_revision: Optional[str]
    endpoint_fingerprint: str
    state: str
    started_at: Optional[str]
    closed_at: Optional[str]
    cleanup_evidence: Optional[Mapping[str, Any]]
    approved_tool_names: Tuple[str, ...]
    approved_catalog_digest: Optional[str]

    @property
    def key(self) -> str:
        return lease_key(self.runtime_generation, self.target_session,
                         self.endpoint_fingerprint)

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES


def _model(record: Mapping[str, Any]) -> McpConnectionLease:
    return McpConnectionLease(
        lease_id=record["lease_id"],
        target_session=record["target_session"],
        runtime_generation=record["runtime_generation"],
        definition_id=record["definition_id"],
        revision=int(record["revision"]),
        lane=record["lane"],
        owner_id=record["owner_id"],
        principal=record["principal"],
        server_scope=record["server_scope"],
        credential_revision=record.get("credential_revision"),
        endpoint_fingerprint=record["endpoint_fingerprint"],
        state=record["state"],
        started_at=record.get("started_at"),
        closed_at=record.get("closed_at"),
        cleanup_evidence=record.get("cleanup_evidence"),
        approved_tool_names=tuple(record.get("approved_tool_names", ())),
        approved_catalog_digest=record.get("approved_catalog_digest"),
    )


class McpLeaseStore:
    """Durable lease table + fact ledger + native-lane occupancy.

    Layout: ``<root>/managed/leases.json`` under ``<root>/managed/.lock``,
    same flock+staging+``os.replace`` discipline as the definition store.
    The fact ledger is per-lease and append-only from the public API: one
    record per state entry plus operation facts (``drain-timeout``,
    ``cleanup-error``, ``reconcile``, ``catalog-changed`` ...).
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- plumbing ---------------------------------------------------------------

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
        return self.root / "managed" / "leases.json"

    def _load(self) -> dict:
        path = self._table_path()
        if not path.is_file():
            return {"version": 1, "leases": {}, "native": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _commit(self, table: dict) -> None:
        path = self._table_path()
        staging = Path(tempfile.mkdtemp(prefix="mcp-lease-", dir=str(path.parent)))
        try:
            tmp = staging / "leases.json"
            tmp.write_text(
                json.dumps(table, sort_keys=True, separators=(",", ":"), indent=1),
                encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _occupancy_conflict(table: dict, key: str) -> None:
        """The one active-occupancy rule for both lane directions."""
        for record in table["leases"].values():
            if record["lane"] != LANE_MANAGED or record["state"] not in ACTIVE_STATES:
                continue
            if lease_key(record["runtime_generation"], record["target_session"],
                         record["endpoint_fingerprint"]) != key:
                continue
            if record["state"] == "unknown":
                raise McpError(
                    MCP_RECONCILE_REQUIRED,
                    "an earlier managed lease on this endpoint ended with an "
                    "unconfirmed outcome; reconcile it before any retry or new lease",
                )
            raise McpError(
                MCP_OWNER_CONFLICT,
                "this (runtimeGeneration, sessionRef, endpointFingerprint) already "
                "holds an active managed lease",
            )
        if table["native"].get(key) is not None:
            raise McpError(
                MCP_OWNER_CONFLICT,
                "a native-lane projection occupies this endpoint for this session; "
                "native and managed lanes are mutually exclusive (no double start)",
            )

    # -- managed leases -----------------------------------------------------------

    def create_lease(
        self, *, caller: LeaseCaller, server_scope: str, definition_id: str,
        revision: int, endpoint_fingerprint: str,
        credential_revision: Optional[str] = None,
        lease_id: Optional[str] = None, owner_id: Optional[str] = None,
    ) -> McpConnectionLease:
        """Open one managed lease in state ``defined`` (chain start).

        Refused before anything is stored when the key already holds an
        active lease (or is ``unknown`` - reconcile first) or a native
        projection (``MCP_OWNER_CONFLICT`` either way).
        """
        lease_id = lease_id or new_lease_id()
        owner_id = owner_id or new_owner_id()
        key = lease_key(caller.runtime_generation, caller.session_ref, endpoint_fingerprint)
        with self._lock():
            table = self._load()
            if lease_id in table["leases"]:
                raise McpError(MCP_OWNER_CONFLICT, "the lease id already exists")
            self._occupancy_conflict(table, key)
            for record in table["leases"].values():
                if record["owner_id"] == owner_id and record["state"] in ACTIVE_STATES:
                    raise McpError(
                        MCP_OWNER_CONFLICT, "the connection owner id is not unique")
            record = {
                "lease_id": lease_id,
                "target_session": caller.session_ref,
                "runtime_generation": caller.runtime_generation,
                "definition_id": definition_id,
                "revision": revision,
                "lane": LANE_MANAGED,
                "owner_id": owner_id,
                "principal": caller.principal,
                "server_scope": server_scope,
                "credential_revision": credential_revision,
                "endpoint_fingerprint": endpoint_fingerprint,
                "state": "defined",
                "started_at": None,
                "closed_at": None,
                "cleanup_evidence": None,
                "approved_tool_names": [],
                "approved_catalog_digest": None,
                "facts": [],
            }
            self._append_fact(record, "state-entry",
                              {"from": None, "to": "defined", "evidence": {}})
            table["leases"][lease_id] = record
            self._commit(table)
        return _model(record)

    def get_lease(self, lease_id: str, caller: LeaseCaller) -> McpConnectionLease:
        """Visibility-gated read: foreign callers get a uniform NOT-FOUND."""
        with self._lock():
            record = self._load()["leases"].get(lease_id)
        return self._check_visible(record, caller)

    def require_owner(self, lease: McpConnectionLease, owner_id: str) -> None:
        if lease.owner_id != owner_id:
            raise McpError(
                MCP_OWNER_CONFLICT,
                "the caller is not the sole connection owner of this lease",
            )

    @staticmethod
    def _check_visible(record: Optional[dict], caller: LeaseCaller) -> McpConnectionLease:
        if (record is None or record.get("principal") != caller.principal
                or record.get("target_session") != caller.session_ref
                or record.get("runtime_generation") != caller.runtime_generation):
            # A foreign principal/session must not learn the lease exists,
            # its fingerprint, its catalog - nothing.
            raise McpError(MCP_LEASE_MISSING, "the MCP lease is not visible to this caller")
        return _model(record)

    def transition(
        self, lease_id: str, caller: LeaseCaller, to_state: str, *,
        evidence: Optional[Mapping[str, Any]] = None,
        fact_kind: str = "state-entry",
    ) -> McpConnectionLease:
        """One legal state entry = one independent fact record (FR-02)."""
        if to_state not in LEASE_STATES:
            raise McpError(
                MCP_STATE_TRANSITION_INVALID, f"unknown lease state {to_state!r}")
        with self._lock():
            table = self._load()
            record = table["leases"].get(lease_id)
            lease = self._check_visible(record, caller)
            legal = to_state in LEGAL_TRANSITIONS[lease.state]
            if not legal:
                raise McpError(
                    MCP_STATE_TRANSITION_INVALID,
                    f"the lease transition {lease.state} -> {to_state} is not legal",
                )
            self._append_fact(record, fact_kind,
                              {"from": lease.state, "to": to_state,
                               "evidence": dict(evidence or {})})
            record["state"] = to_state
            if to_state == "connecting" and record.get("started_at") is None:
                record["started_at"] = _now()
            if to_state == "closed":
                record["closed_at"] = _now()
                record["cleanup_evidence"] = {
                    "closed_at": record["closed_at"],
                    "reconciled": bool((record.get("cleanup_evidence") or {}).get("reconciled")),
                    "cleanup_errors": list(
                        (record.get("cleanup_evidence") or {}).get("cleanup_errors", [])),
                }
            self._commit(table)
            return _model(record)

    def add_fact(
        self, lease_id: str, caller: LeaseCaller, kind: str, details: Mapping[str, Any],
    ) -> McpConnectionLease:
        with self._lock():
            table = self._load()
            record = table["leases"].get(lease_id)
            lease = self._check_visible(record, caller)
            self._append_fact(record, kind, dict(details))
            self._commit(table)
            return lease

    def set_approved_catalog_snapshot(
        self, lease_id: str, caller: LeaseCaller, *,
        tool_names: Tuple[str, ...], catalog_digest: str,
    ) -> McpConnectionLease:
        """Freeze the callable subset for this lease against one catalog digest.

        Newly discovered tools are never auto-approved: widening the set is
        only possible through this explicit owner action (FR-04).
        """
        with self._lock():
            table = self._load()
            record = table["leases"].get(lease_id)
            lease = self._check_visible(record, caller)
            record["approved_tool_names"] = sorted(tool_names)
            record["approved_catalog_digest"] = catalog_digest
            self._append_fact(record, "approved-catalog",
                              {"tool_names": sorted(tool_names),
                               "catalog_digest": catalog_digest})
            self._commit(table)
            return _model(record)

    def record_close_result(
        self, lease_id: str, caller: LeaseCaller, *,
        state: str, cleanup_errors: Tuple[Mapping[str, Any], ...],
        reconciled: bool = False,
    ) -> McpConnectionLease:
        """Persist close/drain evidence (cleanup_errors ledger included)."""
        with self._lock():
            table = self._load()
            record = table["leases"].get(lease_id)
            lease = self._check_visible(record, caller)
            evidence = record.get("cleanup_evidence") or {}
            record["cleanup_evidence"] = {
                "closed_at": record.get("closed_at"),
                "reconciled": reconciled or bool(evidence.get("reconciled")),
                "cleanup_errors": [dict(e) for e in cleanup_errors],
                "last_close_state": state,
            }
            if record["state"] == "closed":
                record["cleanup_evidence"]["closed_at"] = record.get("closed_at")
            self._commit(table)
            return _model(record)

    def reconcile(
        self, lease_id: str, caller: LeaseCaller, *, outcome: str,
        evidence: Mapping[str, Any],
    ) -> McpConnectionLease:
        """The only exit from ``unknown``: a queried reconciliation record.

        ``terminated`` -> ``closed`` (key released, retry may open a NEW
        lease); ``alive`` -> ``connected`` (the same lease continues - never
        a second one).
        """
        if outcome not in _RECONCILE_OUTCOMES:
            raise McpError(
                MCP_STATE_TRANSITION_INVALID,
                f"reconcile outcome must be one of {_RECONCILE_OUTCOMES}",
            )
        to_state = "closed" if outcome == "terminated" else "connected"
        with self._lock():
            table = self._load()
            record = table["leases"].get(lease_id)
            lease = self._check_visible(record, caller)
            if lease.state != "unknown":
                raise McpError(
                    MCP_STATE_TRANSITION_INVALID,
                    "only a lease in state unknown can be reconciled",
                )
            self._append_fact(record, "reconcile",
                              {"from": "unknown", "to": to_state,
                               "outcome": outcome, "evidence": dict(evidence)})
            record["state"] = to_state
            if to_state == "closed":
                record["closed_at"] = _now()
                record["cleanup_evidence"] = {
                    "closed_at": record["closed_at"], "reconciled": True,
                    "cleanup_errors": list((record.get("cleanup_evidence") or {}).get(
                        "cleanup_errors", [])),
                }
            self._commit(table)
            return _model(record)

    # -- reads ---------------------------------------------------------------------

    def list_leases(self, caller: LeaseCaller) -> list:
        with self._lock():
            records = self._load()["leases"]
        return [
            _model(record)
            for key in sorted(records)
            if (record := records[key])["principal"] == caller.principal
            and record["target_session"] == caller.session_ref
            and record["runtime_generation"] == caller.runtime_generation
        ]

    def facts(self, lease_id: str, caller: LeaseCaller) -> Tuple[Mapping[str, Any], ...]:
        with self._lock():
            record = self._load()["leases"].get(lease_id)
        self._check_visible(record, caller)
        assert record is not None
        return tuple(dict(f) for f in record["facts"])

    def active_leases(self) -> list:
        """Every still-occupying managed lease, across sessions/principals.

        Used for unload gating; exposes only ids/states/owners, never
        endpoint credentials or catalog bodies.
        """
        with self._lock():
            records = self._load()["leases"]
        return [
            _model(record)
            for key in sorted(records)
            if (record := records[key])["state"] in ACTIVE_STATES
        ]

    @staticmethod
    def _append_fact(record: dict, kind: str, details: Mapping[str, Any]) -> None:
        facts = record.setdefault("facts", [])
        facts.append({
            "seq": len(facts),
            "kind": kind,
            "at": _now(),
            **details,
        })

    # -- native lane occupancy (mutual-exclusion projection of C2 plans) ------------

    def project_native(
        self, *, caller: LeaseCaller, definition_id: str, revision: int,
        endpoint_fingerprint: str, projection_digest: str,
    ) -> Mapping[str, Any]:
        """Register that a native-lane projection occupies the endpoint.

        Refused with ``MCP_OWNER_CONFLICT`` when an active managed lease
        holds the same key - the same rule read from the other direction.
        """
        key = lease_key(caller.runtime_generation, caller.session_ref, endpoint_fingerprint)
        with self._lock():
            table = self._load()
            for record in table["leases"].values():
                if record["state"] not in ACTIVE_STATES or not (
                        lease_key(record["runtime_generation"], record["target_session"],
                                  record["endpoint_fingerprint"]) == key):
                    continue
                raise McpError(
                    MCP_OWNER_CONFLICT,
                    "an active managed lease owns this endpoint for this session; "
                    "the same server must not also be projected to the native lane",
                )
            entry = {
                "key": key, "definition_id": definition_id, "revision": revision,
                "principal": caller.principal, "projection_digest": projection_digest,
                "at": _now(),
            }
            table["native"][key] = entry
            self._commit(table)
            return dict(entry)

    def native_occupancy(self, *, caller: LeaseCaller,
                         endpoint_fingerprint: str) -> Optional[Mapping[str, Any]]:
        key = lease_key(caller.runtime_generation, caller.session_ref, endpoint_fingerprint)
        with self._lock():
            entry = self._load()["native"].get(key)
        return dict(entry) if entry else None
