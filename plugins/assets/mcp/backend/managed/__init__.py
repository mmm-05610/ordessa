"""T05 managed domain package (**L0/L1** - no real SDK client, no Pi bridge).

Exports the connection-lease state machine (:mod:`.lease`), the tool
catalog observation store (:mod:`.catalog`) and the session manager with
its injectable ports and in-memory fakes
(:mod:`.session_manager`). The real MCP SDK client and the Pi tool bridge
are G2/G4 dependency batches; nothing in here has ever connected to a
real MCP server and no API here may be documented as doing so.
"""
from __future__ import annotations

from .catalog import (
    CATALOG_STATUS_CURRENT,
    CATALOG_STATUS_SUPERSEDED,
    MCP_CATALOG_UNOBSERVABLE,
    McpToolCatalog,
    McpToolCatalogStore,
    catalog_digest_of,
    make_catalog_provider,
    tool_schema_digest,
)
from .lease import (
    ACTIVE_STATES,
    CLOSABLE_STATES,
    LEGAL_TRANSITIONS,
    LEASE_STATES,
    MCP_LEASE_BUSY,
    MCP_LEASE_MISSING,
    MCP_NOT_CONNECTED,
    MCP_RECONCILE_REQUIRED,
    MCP_STATE_TRANSITION_INVALID,
    MCP_TOOL_NOT_APPROVED,
    LANE_MANAGED,
    LANE_NATIVE,
    LeaseCaller,
    McpConnectionLease,
    McpLeaseStore,
    endpoint_fingerprint,
    lease_key,
    new_lease_id,
    new_owner_id,
)
from .session_manager import (
    MCP_CLIENT_FACTORY_MISSING,
    AuditSink,
    FaultInjectingManagedClient,
    InMemoryManagedClient,
    ManagedClientPort,
    ManagedSessionManager,
    PermissionAuthority,
)

__all__ = [
    "ACTIVE_STATES", "AuditSink", "CATALOG_STATUS_CURRENT",
    "CATALOG_STATUS_SUPERSEDED", "CLOSABLE_STATES",
    "FaultInjectingManagedClient", "InMemoryManagedClient", "LANE_MANAGED",
    "LANE_NATIVE", "LEASE_STATES", "LEGAL_TRANSITIONS", "LeaseCaller",
    "MCP_CATALOG_UNOBSERVABLE", "MCP_CLIENT_FACTORY_MISSING", "MCP_LEASE_BUSY",
    "MCP_LEASE_MISSING", "MCP_NOT_CONNECTED", "MCP_RECONCILE_REQUIRED",
    "MCP_STATE_TRANSITION_INVALID", "MCP_TOOL_NOT_APPROVED",
    "ManagedClientPort", "ManagedSessionManager",
    "McpConnectionLease", "McpLeaseStore", "McpToolCatalog",
    "McpToolCatalogStore", "PermissionAuthority", "catalog_digest_of",
    "endpoint_fingerprint", "lease_key", "make_catalog_provider",
    "new_lease_id", "new_owner_id", "tool_schema_digest",
]
