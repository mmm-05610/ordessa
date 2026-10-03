"""T05 managed domain (L0/L1): session manager wiring lease + catalog + ports.

**Evidence level.** This module is the L0/L1 domain layer: its own tests run
on the explicitly-labelled in-memory fakes below. The transport/client
capability is an injected port (:class:`ManagedClientPort`); two concrete
limited-substitute drivers exist, both **L2** against controlled loopback
fake MCP servers: the stdio client (:mod:`backend.managed.client_stdio`,
route ruling in specs/011-q4-mcp/reports/t05-client.md) and the
Streamable-HTTP client (:mod:`backend.managed.client_http`, Q4 T011,
specs/011-q4-mcp/reports/t011-http-client.md). There is still no Pi bridge
here (G4 dependency batch,
specs/011-q4-mcp/reports/t04-t05-research.md §8); no statement in this
package may claim a connection to a real product MCP server.

The manager owns the managed-lane lifecycle end to end:

* ``open_lease`` binds a lease to a real stored revision (a definition
  entry alone is never "live");
* ``plan_connection`` / ``start_connection`` / ``observe_catalog`` walk the
  state chain - each entry its own fact (FR-02), each failure either a
  confirmed ``refused`` (nothing was ever started) or an honest ``unknown``
  (an unconfirmable client outcome - reconcile required before any retry,
  FR-10 / counterexample 7);
* ``call_tool`` is the single side-effect door: it passes the lease-state
  gate, the live-catalog/approval gates and the unified permission seam -
  the same ``backend.permissions.check_tool_callable`` double gate the
  native lane uses, answered by the injected :class:`PermissionAuthority`
  port with a ``ToolCallDecision`` - before the managed client ever sees a
  call, so a fake extension cannot bypass the gates (contracts.md §3/§4);
* ``close_lease`` stops new calls, drains in-flight work under a time
  limit, books a ``drain-timeout`` refusal (``MCP_LEASE_BUSY``, retryable)
  with the pending manifest when the limit expires, releases the sole
  owner's lease exactly once (idempotent replay afterwards) and records
  ``cleanup-error`` facts without ever masking the primary error
  (contracts.md §5, verification.md counterexample 9);
* sessions are isolated by construction: the uniqueness key contains the
  sessionRef and there is **no pooling path** - the factory is asked for a
  fresh client per lease, including two sessions on the same URL
  (data-model「首版默认不池化」, counterexample 3);
* ``project_native`` / lease creation enforce the native-vs-managed lane
  mutual exclusion with ``MCP_OWNER_CONFLICT``;
* ``request_unload`` answers busy while any lease is active.

Secrets never enter events, facts or audits: arguments are represented by
their digest, credentials by the opaque ``credential_revision`` id.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from ..definition import definition_digest
from ..definition_store import McpDefinitionStore
from ..errors import (
    CATALOG_CHANGED,
    CONNECTION_FAILED,
    MCP_CATALOG_MISSING,
    MCP_CLIENT_FACTORY_MISSING,
    MCP_TOOL_NOT_OBSERVED,
    UNKNOWN_OUTCOME,
    McpError,
)
from ..permissions import (
    STATUS_ALLOWED,
    PermissionAuthority,
    check_tool_callable,
)
from .catalog import (
    McpToolCatalog,
    McpToolCatalogStore,
)
from .lease import (
    LeaseCaller,
    McpConnectionLease,
    McpLeaseStore,
    MCP_LEASE_BUSY,
    MCP_LEASE_MISSING,
    MCP_NOT_CONNECTED,
    MCP_RECONCILE_REQUIRED,
    MCP_TOOL_NOT_APPROVED,
    endpoint_fingerprint,
)

# T014 converge: MCP_CLIENT_FACTORY_MISSING is registered in
# backend/errors.py; this module keeps re-exporting the name (reported in
# specs/011-q4-mcp/reports/t05-domain.md).

#: ``(lease) -> client``; limited-substitute factories exist for both
#: transports (``client_stdio.make_stdio_client_factory`` and
#: ``client_http.make_http_client_factory``, one fresh client per lease,
#: no pooling); the pinned-SDK route stays C0's ruling (integration item 10).
ClientFactory = Callable[[McpConnectionLease], "ManagedClientPort"]


class ManagedClientPort(Protocol):
    """The transport/client capability the managed lane drives.

    Deliberately the first-version minimum (harness-adapters.md「Managed
    lane」): start the owning process/transport, protocol connect,
    ``tools/list``, ``tools/call``, idempotent close. No resources,
    sampling, elicitation or tasks.
    """

    def start(self) -> None:
        """Bring the client transport up (may create the owned process)."""

    def connect(self) -> Mapping[str, Any]:
        """Protocol handshake; returns at least protocolVersion/serverInfo."""

    def list_tools(self) -> Mapping[str, Any]:
        """``tools/list`` result shape: ``{"tools": [{"name", ...}]}``."""

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """``tools/call``; the only path with server-side effects."""

    def close(self) -> None:
        """Release the transport/process. Must be safe to be called once."""


class AuditSink(Protocol):
    """Existing event/audit interface seam (no second host lifecycle)."""

    def write(self, event: Mapping[str, Any]) -> None:
        ...


# -- L0/L1 in-memory fakes (test doubles; NOT real clients) -------------------------


@dataclass
class InMemoryManagedClient:
    """Deterministic in-memory double of a managed MCP client (**L0/L1**).

    It records every observable interaction so tests can prove sole
    ownership and no leaks: ``start_count``/``connect_count``/
    ``close_count`` and ``executed_calls``. It shares no state with any
    other instance - two clients for one URL are two worlds.
    """

    tools: list = field(default_factory=list)
    protocol_version: str = "2024-11-05"
    server_info: Mapping[str, Any] = field(
        default_factory=lambda: {"name": "in-memory-fake", "version": "0"})
    start_count: int = 0
    connect_count: int = 0
    close_count: int = 0
    started: bool = False
    connected: bool = False
    closed: bool = False
    executed_calls: list = field(default_factory=list)

    def start(self) -> None:
        self.start_count += 1
        self.started = True

    def connect(self) -> Mapping[str, Any]:
        if not self.started:
            raise RuntimeError("start() was never called")
        self.connect_count += 1
        self.connected = True
        return {"protocolVersion": self.protocol_version, "serverInfo": dict(self.server_info)}

    def list_tools(self) -> Mapping[str, Any]:
        if not self.connected or self.closed:
            raise RuntimeError("list_tools requires a live connection")
        return {"tools": [dict(tool) for tool in self.tools]}

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.connected or self.closed:
            raise RuntimeError("call_tool requires a live connection")
        self.executed_calls.append((name, dict(arguments)))
        return {
            "content": [{"type": "text", "text": f"in-memory fake result for {name}"}]}

    def close(self) -> None:
        self.close_count += 1
        self.connected = False
        self.closed = True


@dataclass
class FaultInjectingManagedClient(InMemoryManagedClient):
    """In-memory double with configurable faults (**L0/L1**, drain tests).

    * ``start_error`` / ``connect_error`` / ``close_error`` - raise the
      given exception from that phase (unknown-outcome / cleanup-error
      paths);
    * ``call_gate`` - a ``threading.Event``; while unset, ``call_tool``
      blocks, simulating an in-flight call so ``close`` must drain/busy.
    """

    start_error: Optional[BaseException] = None
    connect_error: Optional[BaseException] = None
    close_error: Optional[BaseException] = None
    call_gate: Optional[Any] = None
    call_started: Optional[Any] = None

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        super().start()

    def connect(self) -> Mapping[str, Any]:
        if self.connect_error is not None:
            raise self.connect_error
        return super().connect()

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.call_started is not None:
            self.call_started.set()
        if self.call_gate is not None:
            self.call_gate.wait(timeout=10.0)
        return super().call_tool(name, arguments)

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        super().close()


# -- the manager ------------------------------------------------------------------


class ManagedSessionManager:
    """Sole managed-lane owner façade over the lease + catalog stores."""

    def __init__(
        self, *, definitions: McpDefinitionStore, leases: McpLeaseStore,
        catalogs: McpToolCatalogStore, client_factory: Optional[ClientFactory] = None,
        permission_authority: Optional[PermissionAuthority] = None,
        preauthorizations: Sequence = (),
        audit_sink: Optional[AuditSink] = None,
        drain_poll_interval: float = 0.005,
    ) -> None:
        self.definitions = definitions
        self.leases = leases
        self.catalogs = catalogs
        self.client_factory = client_factory
        self.permission_authority = permission_authority
        #: bounded unattended grants re-verified live by the permission seam
        #: (``backend.permissions.BoundedPreAuthorization``); with no
        #: authority injected they are the ONLY allow path, fail closed
        #: otherwise.
        self.preauthorizations = tuple(preauthorizations)
        self.audit_sink = audit_sink
        self._drain_poll_interval = drain_poll_interval
        self._clients: dict = {}
        self._inflight: dict = {}
        self._closing: set = set()
        self._calls_lock = threading.Lock()

    # -- lease lifecycle -------------------------------------------------------------

    def open_lease(
        self, *, caller: LeaseCaller, server_scope: str, definition_id: str,
        revision: int, credential_revision: Optional[str] = None,
    ) -> McpConnectionLease:
        """Bind a new managed lease to a *stored, digest-verified* revision.

        The uniqueness check (one active lease per
        ``(generation, sessionRef, fingerprint)``, native/managed mutual
        exclusion, unique owner id, unknown-blocks-retry) is inside the
        store's lock, next to the write.
        """
        model = self.definitions.read_revision(
            server_scope=server_scope, definition_id=definition_id, revision=revision)
        lease = self.leases.create_lease(
            caller=caller, server_scope=server_scope, definition_id=definition_id,
            revision=model.revision, endpoint_fingerprint=endpoint_fingerprint(model),
            credential_revision=credential_revision)
        self._audit(caller, lease.lease_id,
                    {"kind": "lease-opened", "state": "defined",
                     "definitionId": definition_id, "revision": lease.revision})
        return lease

    def plan_connection(
        self, *, caller: LeaseCaller, lease_id: str, submission_id: Optional[str] = None,
    ) -> McpConnectionLease:
        """defined -> selected -> planned. Each entry is its own fact."""
        lease = self._advance(caller, lease_id, "selected",
                              {"submissionId": submission_id})
        return self._advance(caller, lease.lease_id, "planned",
                             {"submissionId": submission_id})

    def start_connection(
        self, *, caller: LeaseCaller, lease_id: str,
    ) -> McpConnectionLease:
        """planned -> connecting -> connected via the injected client port.

        A factory fault or a start() error before the client was adopted is
        a confirmed ``refused`` (nothing ever lived). A connect() failure
        is NOT confirmable - the lease parks in ``unknown`` and the key
        stays occupied until :meth:`reconcile` (counterexample 7).
        """
        lease = self._advance(caller, lease_id, "connecting", {"phase": "client-start"})
        if self.client_factory is None:
            self.leases.transition(
                lease_id, caller, "refused",
                evidence={"code": MCP_CLIENT_FACTORY_MISSING,
                          "reason": "no managed client implementation is wired"})
            raise McpError(
                MCP_CLIENT_FACTORY_MISSING,
                "no managed client implementation is wired; the real SDK client "
                "is a G2/G4 dependency batch - nothing was started (L0/L1)",
            )
        try:
            client = self.client_factory(lease)
        except BaseException as exc:
            # a factory fault is CONFIRMED (nothing was ever started): the
            # documented behaviour of this method ("a factory fault or a
            # start() error before the client was adopted is a confirmed
            # refused"). A typed domain refusal keeps its own code.
            self.leases.transition(
                lease_id, caller, "refused",
                evidence={"phase": "factory", "error": type(exc).__name__})
            self._audit(caller, lease_id, {"kind": "lease-refused",
                                           "phase": "factory"})
            if isinstance(exc, McpError):
                raise
            raise McpError(
                CONNECTION_FAILED,
                "the managed client factory failed; nothing is running",
            ) from exc
        try:
            client.start()
        except BaseException as exc:
            self.leases.transition(
                lease_id, caller, "refused",
                evidence={"phase": "start", "error": type(exc).__name__})
            self._audit(caller, lease_id, {"kind": "lease-refused", "phase": "start"})
            raise McpError(
                CONNECTION_FAILED,
                "the managed client did not start; nothing is running",
            ) from exc
        with self._calls_lock:
            self._clients[lease_id] = client
        try:
            answer = client.connect()
        except BaseException as exc:
            self.leases.transition(
                lease_id, caller, "unknown",
                evidence={"phase": "connect", "error": type(exc).__name__})
            self._audit(caller, lease_id, {"kind": "lease-unknown", "phase": "connect"})
            raise McpError(
                UNKNOWN_OUTCOME,
                "the connect attempt failed with an unconfirmed client outcome; "
                "reconcile this lease before any retry - no second lease may be "
                "created betting the old client exited",
            ) from exc
        protocol_version = answer.get("protocolVersion") if isinstance(answer, Mapping) else None
        info = answer.get("serverInfo") if isinstance(answer, Mapping) else None
        info = dict(info) if isinstance(info, Mapping) else None
        return self.leases.transition(
            lease_id, caller, "connected",
            evidence={"phase": "connect",
                      "negotiatedProtocolVersion": protocol_version,
                      "serverInfo": ({"name": info.get("name"),
                                      "version": info.get("version")}
                                     if info else None)})

    def observe_catalog(
        self, *, caller: LeaseCaller, lease_id: str,
    ) -> McpToolCatalog:
        """Run ``tools/list`` over the live client and record the observation.

        The only way a catalog exists. Re-observation detects drift: the
        previous digest stops being current and a ``catalog-changed`` fact
        is booked; approvals frozen against the old digest go stale.
        """
        lease = self.leases.get_lease(lease_id, caller)
        if lease.state not in ("connected", "catalog-observed"):
            raise McpError(
                MCP_NOT_CONNECTED,
                f"a catalog may only be observed over a connected lease "
                f"(state {lease.state!r})",
            )
        client = self._require_client(lease_id)
        # drift baseline is this lease's own previous observation (a second
        # session observing a different tool set is isolation, not drift);
        # approval staleness below is judged against the global current
        # digest of (definitionId, revision), matching the resolve seam.
        previous = self.catalogs.latest_for_lease(lease_id)
        try:
            listing = client.list_tools()
        except BaseException as exc:
            raise McpError(
                UNKNOWN_OUTCOME,
                "the tools/list attempt failed with an unconfirmed outcome",
            ) from exc
        tools = list(listing.get("tools", [])) if isinstance(listing, Mapping) else []
        connect_evidence = self._connect_evidence(caller, lease_id)
        info = (listing.get("serverInfo")
                if isinstance(listing, Mapping) and listing.get("serverInfo")
                else connect_evidence.get("serverInfo"))
        protocol = (listing.get("protocolVersion")
                    if isinstance(listing, Mapping) and listing.get("protocolVersion")
                    else connect_evidence.get("negotiatedProtocolVersion"))
        catalog = self.catalogs.record_observation(
            lease, tools=tools,
            protocol_version=str(protocol or "unknown"),
            server_info=dict(info or {}))
        if lease.state == "connected":
            self.leases.transition(
                lease_id, caller, "catalog-observed",
                evidence={"catalogDigest": catalog.catalog_digest})
        else:
            self.leases.add_fact(
                lease_id, caller, "tool-catalog-reobserved",
                {"catalogDigest": catalog.catalog_digest})
        if previous is not None and previous.catalog_digest != catalog.catalog_digest:
            self.leases.add_fact(
                lease_id, caller, "catalog-changed",
                {"fromDigest": previous.catalog_digest, "toDigest": catalog.catalog_digest})
            self._audit(caller, lease_id,
                        {"kind": "catalog-changed",
                         "fromDigest": previous.catalog_digest,
                         "toDigest": catalog.catalog_digest})
        else:
            self._audit(caller, lease_id,
                        {"kind": "tool-catalog-observed",
                         "catalogDigest": catalog.catalog_digest})
        return catalog

    def approve_tools(
        self, *, caller: LeaseCaller, lease_id: str, owner_id: str,
        tool_names: Sequence[str],
    ) -> McpConnectionLease:
        """Explicitly freeze the callable subset against the current digest.

        Newly discovered tools never join automatically (FR-04); after a
        drift the owner must approve again against the new digest, and the
        approval still only covers names present in the live catalog.
        """
        lease = self.leases.get_lease(lease_id, caller)
        self.leases.require_owner(lease, owner_id)
        current = self.catalogs.latest(
            definition_id=lease.definition_id, revision=lease.revision)
        if current is None:
            raise McpError(
                MCP_CATALOG_MISSING,
                "approval needs a live catalog observation for this revision",
            )
        observed = set(current.tool_names)
        for name in tool_names:
            if name not in observed:
                raise McpError(
                    MCP_TOOL_NOT_OBSERVED,
                    f"tool {name!r} is not in the currently observed catalog",
                )
        approved = self.leases.set_approved_catalog_snapshot(
            lease_id, caller, tool_names=tuple(tool_names),
            catalog_digest=current.catalog_digest)
        self._audit(caller, lease_id,
                    {"kind": "tools-approved", "catalogDigest": current.catalog_digest,
                     "toolNames": sorted(tool_names)})
        return approved

    # -- the single side-effect door ----------------------------------------------------

    def call_tool(
        self, *, caller: LeaseCaller, lease_id: str, owner_id: str, tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict:
        """One managed ``tools/call``, gated in this exact order:

        lease visibility -> sole owner -> lease state (``catalog-observed``)
        -> live catalog exists -> approval digest still current (drift
        fails closed) -> tool in approved subset -> tool observed ->
        Permission authority decision. Only then the client port runs the
        call, inside the in-flight registry the drain phase waits for.
        """
        lease = self.leases.get_lease(lease_id, caller)
        self.leases.require_owner(lease, owner_id)
        if lease.state != "catalog-observed":
            raise McpError(
                MCP_NOT_CONNECTED,
                "tool calls are only accepted on a catalog-observed lease "
                f"(state {lease.state!r}); the definition record alone is not a connection",
            )
        current = self.catalogs.latest(
            definition_id=lease.definition_id, revision=lease.revision)
        if current is None:
            raise McpError(
                MCP_CATALOG_MISSING,
                "no live tools/list observation backs this lease; refusing to "
                "present a definition entry as a connected catalog",
            )
        if not lease.approved_tool_names or lease.approved_catalog_digest is None:
            raise McpError(
                MCP_TOOL_NOT_APPROVED,
                "nothing is approved for this lease yet; the callable subset "
                "must be frozen explicitly against an observed catalog",
            )
        if lease.approved_catalog_digest != current.catalog_digest:
            raise McpError(
                CATALOG_CHANGED,
                "the observed catalog drifted; the frozen approval is stale "
                "and re-approval is required before any call",
            )
        if tool_name not in lease.approved_tool_names:
            raise McpError(
                MCP_TOOL_NOT_APPROVED,
                f"tool {tool_name!r} is not in this lease's approved subset "
                "(newly discovered tools are never auto-approved)",
            )
        if tool_name not in set(current.tool_names):
            raise McpError(
                MCP_TOOL_NOT_OBSERVED,
                f"tool {tool_name!r} is not in the observed catalog",
            )
        args_digest = definition_digest({"tool": tool_name, "arguments": dict(arguments)})
        # -- the unified permission seam (D5): the SAME
        # backend.permissions.check_tool_callable double gate the native
        # lane answers from - catalog-subset gate plus the Permission
        # authority's ToolCallDecision final ruling. There is exactly one
        # PermissionAuthority protocol in this package (the bool-shaped
        # managed-local twin was removed); refusal is typed and raised
        # before a single frame can reach the client.
        authority = self.permission_authority
        gate_snapshot = {
            "allowed_tool_names": tuple(lease.approved_tool_names),
            "definition_revisions": [{
                "definition_id": lease.definition_id,
                "revision": lease.revision,
                "canonical_digest": None,
            }],
            # the managed lane enforces every call through THIS door, so
            # per-call enforcement is proven by construction, unlike an
            # unproven native projection (contracts §4).
            "lane_by_definition": {lease.definition_id: {"lane": "managed",
                                                         "enforcement": "proven"}},
        }
        decision = check_tool_callable(
            gate_snapshot, authority, tool_name, args_digest, time.time(),
            principal=caller.principal, session_ref=caller.session_ref,
            lease_id=lease_id, definition_id=lease.definition_id,
            policy_revision=getattr(authority, "policy_revision", None),
            preauthorizations=self.preauthorizations)
        if decision.status != STATUS_ALLOWED:
            raise decision.as_error()
        descriptor = {"lease_id": lease_id, "tool": tool_name, "args_digest": args_digest}
        with self._calls_lock:
            if lease_id in self._closing:
                raise McpError(
                    MCP_NOT_CONNECTED, "the lease is draining; no new calls are accepted")
            client = self._clients.get(lease_id)
            if client is None:
                raise McpError(
                    MCP_NOT_CONNECTED, "no live managed client is owned for this lease")
            self._inflight.setdefault(lease_id, []).append(descriptor)
        try:
            try:
                result = client.call_tool(tool_name, arguments)
            except McpError:
                raise
            except BaseException as exc:
                self.leases.add_fact(
                    lease_id, caller, "call-outcome-unknown",
                    {"tool": tool_name, "argsDigest": args_digest,
                     "error": type(exc).__name__})
                raise McpError(
                    UNKNOWN_OUTCOME,
                    "the tool call outcome is unconfirmed; no automatic retry",
                ) from exc
            self.leases.add_fact(
                lease_id, caller, "tool-call-executed",
                {"tool": tool_name, "argsDigest": args_digest})
            return {"result": dict(result), "argsDigest": args_digest,
                    "catalogDigest": current.catalog_digest, "tool": tool_name}
        finally:
            with self._calls_lock:
                pending = self._inflight.get(lease_id, [])
                if descriptor in pending:
                    pending.remove(descriptor)

    # -- close / drain / reconcile -------------------------------------------------------

    def close_lease(
        self, *, caller: LeaseCaller, lease_id: str, owner_id: str,
        drain_timeout: float = 1.0,
    ) -> dict:
        """Owner-only close: stop new calls -> bounded drain -> release once.

        * replay: an already closed/refused lease returns the recorded
          evidence without touching the client again (close is effective
          exactly once, idempotently retryable);
        * drain-timeout: in-flight work past the limit keeps the lease in
          ``closing`` (new calls already gated), books the pending manifest
          as a ``drain-timeout`` fact and raises ``MCP_LEASE_BUSY`` - the
          retry path;
        * cleanup errors never mask the primary error (counterexample 9):
          a failing client close surfaces ``UNKNOWN_OUTCOME`` and parks
          the lease in ``unknown`` for reconcile, a failing audit sink is
          booked into ``cleanup_errors`` and the primary error still
          propagates.
        """
        lease = self.leases.get_lease(lease_id, caller)
        self.leases.require_owner(lease, owner_id)
        if lease.state in ("closed", "refused"):
            return {"replayed": True, "state": lease.state, "leaseId": lease_id,
                    "cleanupEvidence": dict(lease.cleanup_evidence or {})}
        if lease.state == "unknown":
            raise McpError(
                MCP_RECONCILE_REQUIRED,
                "the previous managed client's fate is unconfirmed; reconcile "
                "before closing - a close now would be another unconfirmed bet",
            )
        cleanup_errors: list = []
        if lease.state != "closing":
            lease = self.leases.transition(
                lease_id, caller, "closing", evidence={"by": owner_id})
            self._audit(caller, lease_id, {"kind": "lease-state", "to": "closing"})
        with self._calls_lock:
            self._closing.add(lease_id)
            pending = list(self._inflight.get(lease_id, ()))
        deadline = time.monotonic() + max(0.0, drain_timeout)
        while pending and time.monotonic() < deadline:
            time.sleep(self._drain_poll_interval)
            with self._calls_lock:
                pending = list(self._inflight.get(lease_id, ()))
        primary: Optional[McpError] = None
        if pending:
            manifest = [{"tool": item["tool"], "argsDigest": item["args_digest"]}
                        for item in pending]
            self.leases.add_fact(
                lease_id, caller, "drain-timeout",
                {"pending": manifest, "drainTimeout": drain_timeout})
            self._audit(caller, lease_id,
                        {"kind": "drain-timeout", "pendingCount": len(manifest)})
            primary = McpError(
                MCP_LEASE_BUSY,
                f"the lease still has {len(manifest)} in-flight call(s); close is "
                "retryable after they finish (or hand the manifest to a trusted drain)",
            )
        else:
            client = self._clients.get(lease_id)
            try:
                if client is not None:
                    client.close()
            except BaseException as exc:
                cleanup_errors.append({"phase": "client-close",
                                       "error": type(exc).__name__})
                self.leases.add_fact(
                    lease_id, caller, "cleanup-error",
                    {"phase": "client-close", "error": type(exc).__name__})
                primary = McpError(
                    UNKNOWN_OUTCOME,
                    "the managed client close outcome is unconfirmed; reconcile "
                    "this lease before retrying",
                )

        if primary is None:
            self.leases.transition(
                lease_id, caller, "closed",
                evidence={"by": owner_id, "cleanupErrors": []})
            with self._calls_lock:
                self._clients.pop(lease_id, None)
                self._closing.discard(lease_id)
            self.leases.record_close_result(
                lease_id, caller, state="closed", cleanup_errors=())
            self._audit(caller, lease_id, {"kind": "lease-closed", "state": "closed"})
            refreshed = self.leases.get_lease(lease_id, caller)
            return {"replayed": False, "state": "closed", "leaseId": lease_id,
                    "cleanupEvidence": dict(refreshed.cleanup_evidence or {}),
                    "closedAt": refreshed.closed_at}
        if primary.code == UNKNOWN_OUTCOME:
            self.leases.transition(
                lease_id, caller, "unknown", evidence={"phase": "client-close"})
            with self._calls_lock:
                self._closing.discard(lease_id)
                self._clients.pop(lease_id, None)
        try:
            self.leases.record_close_result(
                lease_id, caller,
                state=self.leases.get_lease(lease_id, caller).state,
                cleanup_errors=tuple(cleanup_errors))
        except McpError as exc:  # never mask the primary error
            cleanup_errors.append({"phase": "close-evidence", "error": exc.code})
        self._audit(caller, lease_id,
                    {"kind": "close-failed", "code": primary.code,
                     "cleanupErrors": len(cleanup_errors)})
        raise primary

    def reconcile(
        self, *, caller: LeaseCaller, lease_id: str, owner_id: str, outcome: str,
        evidence: Mapping[str, Any],
    ) -> McpConnectionLease:
        """The only way out of ``unknown``: a queried reconciliation record.

        ``terminated`` closes the lease and releases the key (a NEW lease
        may then be opened); ``alive`` returns the same lease to
        ``connected`` - never a second lease "betting" on the old exit.
        """
        lease = self.leases.get_lease(lease_id, caller)
        self.leases.require_owner(lease, owner_id)
        reconciled = self.leases.reconcile(
            lease_id, caller, outcome=outcome, evidence=dict(evidence))
        if outcome == "terminated":
            # the reconciliation record says nothing is alive; the manager
            # drops its (unconfirmed) client reference and stops draining.
            with self._calls_lock:
                self._clients.pop(lease_id, None)
                self._closing.discard(lease_id)
        self._audit(caller, lease_id,
                    {"kind": "reconcile", "outcome": outcome,
                     "state": reconciled.state})
        return reconciled

    # -- public read paths ---------------------------------------------------------------

    def list_tools_for_definition(
        self, *, caller: LeaseCaller, server_scope: str, definition_id: str, revision: int,
    ) -> dict:
        """The ``listTools`` service read: live-lease catalogs only.

        With no connected lease of *this caller's session* observing the
        revision, the answer is a typed refusal - a stored definition can
        never be dressed up as a live connection (contracts.md §1).
        """
        for lease in self.leases.list_leases(caller):
            if (lease.server_scope != server_scope or lease.definition_id != definition_id
                    or lease.revision != revision or lease.state != "catalog-observed"):
                continue
            current = self.catalogs.latest_for_lease(lease.lease_id)
            if current is not None:
                return {"leaseId": lease.lease_id, "catalog": current}
        raise McpError(
            MCP_CATALOG_MISSING,
            "no live managed connection is observing this definition; a stored "
            "definition entry is not a connection and is never returned as one",
        )

    def inspect_connection(self, *, caller: LeaseCaller, lease_id: str) -> dict:
        """Lease facts + per-level state evidence (levels stay separate)."""
        lease = self.leases.get_lease(lease_id, caller)
        facts = self.leases.facts(lease_id, caller)
        state_facts: dict = {}
        for fact in facts:
            if fact.get("kind") == "state-entry" and fact.get("to"):
                state_facts.setdefault(str(fact["to"]), dict(fact))
        levels = {
            state: (dict(state_facts[state]) if state in state_facts
                    else {"observed": False, "reason": "no fact entry for this level"})
            for state in ("defined", "selected", "planned", "connecting",
                          "connected", "catalog-observed")
        }
        catalog = self.catalogs.latest_for_lease(lease_id)
        return {
            "leaseId": lease.lease_id, "state": lease.state, "lane": lease.lane,
            "ownerId": lease.owner_id, "definitionId": lease.definition_id,
            "revision": lease.revision, "endpointFingerprint": lease.endpoint_fingerprint,
            "credentialRevision": lease.credential_revision,
            "startedAt": lease.started_at, "closedAt": lease.closed_at,
            "cleanupEvidence": dict(lease.cleanup_evidence or {}),
            "facts": [dict(f) for f in facts],
            "levels": levels,
            "catalogDigest": catalog.catalog_digest if catalog else None,
        }

    def project_native(
        self, *, caller: LeaseCaller, server_scope: str, definition_id: str,
        revision: int, projection_digest: str,
    ) -> Mapping[str, Any]:
        """Register a native-lane projection for an endpoint (mutual exclusion)."""
        model = self.definitions.read_revision(
            server_scope=server_scope, definition_id=definition_id, revision=revision)
        entry = self.leases.project_native(
            caller=caller, definition_id=definition_id, revision=model.revision,
            endpoint_fingerprint=endpoint_fingerprint(model),
            projection_digest=projection_digest)
        self._audit(caller, None, {"kind": "native-projected",
                                   "definitionId": definition_id, "revision": revision})
        return entry

    def request_unload(self, *, reason: str) -> dict:
        """Backend unload gate: busy while any managed lease is active.

        A foreign caller cannot drain someone else's lease, so the honest
        first-version answer is the busy refusal listing lease ids/states/
        owners (no endpoint or credential content).
        """
        active = self.leases.active_leases()
        if active:
            manifest = [{"leaseId": lease.lease_id, "state": lease.state,
                         "ownerId": lease.owner_id} for lease in active]
            raise McpError(
                MCP_LEASE_BUSY,
                "unload refused: managed leases are still active "
                f"({', '.join(item['leaseId'] for item in manifest)}); their "
                "owners must close or a trusted drain must run",
            )
        return {"unloadAllowed": True, "reason": reason}

    # -- plumbing --------------------------------------------------------------------------

    def _advance(
        self, caller: LeaseCaller, lease_id: str, to_state: str,
        evidence: Mapping[str, Any],
    ) -> McpConnectionLease:
        lease = self.leases.transition(lease_id, caller, to_state, evidence=evidence)
        self._audit(caller, lease_id, {"kind": "lease-state", "to": to_state})
        return lease

    def _connect_evidence(self, caller: LeaseCaller, lease_id: str) -> Mapping[str, Any]:
        """The connect-handshake fact (negotiated version, serverInfo).

        ``tools/list`` itself carries neither; reading them off the connect
        fact keeps the catalog's provenance honest (no re-derivation, no
        invention).
        """
        for fact in reversed(self.leases.facts(lease_id, caller)):
            if (fact.get("kind") == "state-entry" and fact.get("to") == "connected"):
                return dict(fact.get("evidence") or {})
        return {}

    def _require_client(self, lease_id: str) -> ManagedClientPort:
        with self._calls_lock:
            client = self._clients.get(lease_id)
        if client is None:
            raise McpError(
                MCP_LEASE_MISSING,
                "no live managed client is owned by this manager for that lease",
            )
        return client

    def _audit(self, caller: Optional[LeaseCaller], lease_id: Optional[str],
               event: Mapping[str, Any]) -> None:
        """Write to the injected audit sink; a sink failure is booked as a
        ``cleanup-error`` fact and NEVER masks the operation's primary error
        (contracts.md §5). Events carry ids/digests/states only."""
        if self.audit_sink is None:
            return
        payload = {
            **dict(event),
            "leaseId": lease_id,
            "actorPrincipal": caller.principal if caller else None,
            "sessionRef": caller.session_ref if caller else None,
        }
        try:
            self.audit_sink.write(payload)
        except BaseException as exc:
            if caller is not None and lease_id is not None:
                try:
                    self.leases.add_fact(
                        lease_id, caller, "cleanup-error",
                        {"phase": "audit-sink", "error": type(exc).__name__,
                         "eventKind": event.get("kind")})
                except BaseException:
                    # the audit ledger is best-effort; it must never replace
                    # the operation's own outcome
                    pass
