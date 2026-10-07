"""Shared L0/L1 test doubles for the managed-domain tests.

No sockets, no subprocesses, no real MCP client: the only "clients" are the
in-memory fakes exported by ``backend.managed.session_manager`` (the real
SDK client is a G2/G4 dependency batch).
"""
from __future__ import annotations

from backend.errors import PERMISSION_REFUSED
from backend.permissions import ToolCallDecision
from backend.assignment import McpAssignmentStore
from backend.definition_store import McpDefinitionStore
from backend.managed import (
    FaultInjectingManagedClient,
    InMemoryManagedClient,
    LeaseCaller,
    ManagedSessionManager,
    McpLeaseStore,
    McpToolCatalogStore,
)

SERVER_SCOPE = "scope-1"

TOOL_ECHO = {"name": "echo", "inputSchema": {"type": "object",
                                             "properties": {"text": {"type": "string"}}}}
TOOL_LIST = {"name": "list", "inputSchema": {"type": "object"}}
TOOLS_ONE = [TOOL_ECHO]
TOOLS_TWO = [TOOL_ECHO, TOOL_LIST]


class RecordingAuditSink:
    """AuditSink fake; ``raise_on`` makes named event kinds fail (masking tests)."""

    def __init__(self) -> None:
        self.events: list = []
        self.raise_on: set = set()

    def write(self, event) -> None:
        if event.get("kind") in self.raise_on:
            raise RuntimeError("audit sink is down")
        self.events.append(dict(event))

    def kinds(self) -> list:
        return [event["kind"] for event in self.events]


class AllowingAuthority:
    """PermissionAuthority fake that allows and records every decision input.

    D5: the seam answers with the unified ``ToolCallDecision`` (the bool
    shape was retired together with the manager-local protocol twin).
    """

    policy_revision = "pol-1"

    def __init__(self) -> None:
        self.seen: list = []

    def authorize_tool_call(self, **kwargs) -> ToolCallDecision:
        self.seen.append(kwargs)
        return ToolCallDecision.allowed(basis="authority", gate="authority",
                                        policy_revision=self.policy_revision)


class DenyingAuthority(AllowingAuthority):
    def authorize_tool_call(self, **kwargs) -> ToolCallDecision:
        self.seen.append(kwargs)
        return ToolCallDecision.refused(
            code=PERMISSION_REFUSED,
            reason="denied by the fake authority before any side effect",
            gate="authority")


#: shorthand for tests that need a fresh allowing/denying authority instance
ALLOWING = AllowingAuthority
DENYING = DenyingAuthority

#: sentinel distinguishing "not passed" from an explicit ``None`` factory
_UNSET = object()


class FakeClientFactory:
    """Produces one fresh in-memory fake per lease - there is no pooling path.

    ``set(session_ref, definition_id, tools=..., **faults)`` configures the
    client for that (session, definition) pair; faults are passed to
    :class:`FaultInjectingManagedClient`.
    """

    def __init__(self) -> None:
        self.specs: dict = {}
        self.default_spec: dict = {"tools": []}
        self.produced: list = []

    def set(self, session_ref: str, definition_id: str, **spec) -> None:
        self.specs[(session_ref, definition_id)] = dict(spec)

    def __call__(self, lease) -> InMemoryManagedClient:
        spec = dict(self.default_spec)
        spec.update(self.specs.get((lease.target_session, lease.definition_id), {}))
        faults = {key: value for key, value in spec.items()
                  if key.endswith("_error") or key in ("call_gate", "call_started")}
        plain = {key: value for key, value in spec.items() if key not in faults}
        if faults:
            client = FaultInjectingManagedClient(**plain, **faults)
        else:
            client = InMemoryManagedClient(**plain)
        self.produced.append(client)
        return client

    @property
    def production_count(self) -> int:
        return len(self.produced)


class ManagedHarness:
    """One set of domain stores + helpers to build managers and live leases."""

    def __init__(self, tmp_path) -> None:
        self.root = tmp_path
        self.definitions = McpDefinitionStore(tmp_path / "defs")
        self.assignments = McpAssignmentStore(tmp_path / "assigns", self.definitions)
        self.leases = McpLeaseStore(tmp_path / "managed")
        self.catalogs = McpToolCatalogStore(tmp_path / "managed")
        self.sink = RecordingAuditSink()
        self.factory = FakeClientFactory()

    # -- stores / managers -------------------------------------------------------------

    def fresh_lease_store(self) -> McpLeaseStore:
        """A second store object on the same root: proves file-backed state."""
        return McpLeaseStore(self.root / "managed")

    def manager(self, *, authority=None, factory=_UNSET, sink=None,
                lease_store=None) -> ManagedSessionManager:
        return ManagedSessionManager(
            definitions=self.definitions,
            leases=lease_store if lease_store is not None else self.leases,
            catalogs=self.catalogs,
            client_factory=self.factory if factory is _UNSET else factory,
            permission_authority=authority,
            audit_sink=sink if sink is not None else self.sink)

    @staticmethod
    def caller(principal: str = "u-a", session: str = "sess-a",
               generation: int = 1) -> LeaseCaller:
        return LeaseCaller(principal=principal, session_ref=session,
                           runtime_generation=generation)

    # -- definitions ---------------------------------------------------------------------

    def install_remote(self, definition_id: str = "srv-a", *,
                       url: str = "https://mcp.example.test/a",
                       headers: dict | None = None) -> int:
        result = self.definitions.save_revision(
            server_scope=SERVER_SCOPE, definition_id=definition_id,
            definition={"name": definition_id,
                        "transport": {"remote": {"url": url, "headers": headers or {}}}},
            expected_version=0, operation_key=f"save-{definition_id}")
        self.definitions.approve_revision(
            server_scope=SERVER_SCOPE, definition_id=definition_id,
            revision=result["revision"], actor="admin-1")
        return result["revision"]

    def install_stdio(self, definition_id: str = "srv-stdio", *,
                      command: str = "/usr/bin/fake-server",
                      args: list | None = None) -> int:
        result = self.definitions.save_revision(
            server_scope=SERVER_SCOPE, definition_id=definition_id,
            definition={"name": definition_id,
                        "transport": {"stdio": {"command": command,
                                                "args": args or [], "env": {}}}},
            expected_version=0, operation_key=f"save-{definition_id}")
        self.definitions.approve_revision(
            server_scope=SERVER_SCOPE, definition_id=definition_id,
            revision=result["revision"], actor="admin-1")
        return result["revision"]

    # -- chains ------------------------------------------------------------------------------

    def bring_up(self, manager: ManagedSessionManager, caller: LeaseCaller,
                 definition_id: str, revision: int, *,
                 credential_revision: str | None = None):
        """open -> plan -> start -> observe; returns (lease, catalog, client)."""
        lease = manager.open_lease(
            caller=caller, server_scope=SERVER_SCOPE, definition_id=definition_id,
            revision=revision, credential_revision=credential_revision)
        manager.plan_connection(caller=caller, lease_id=lease.lease_id,
                                submission_id="sub-1")
        manager.start_connection(caller=caller, lease_id=lease.lease_id)
        catalog = manager.observe_catalog(caller=caller, lease_id=lease.lease_id)
        client = self.factory.produced[-1]
        return lease, catalog, client
