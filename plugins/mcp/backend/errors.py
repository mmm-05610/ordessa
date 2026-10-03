"""The closed error-code vocabulary of the MCP asset domain (T014 converge).

This module is the ONE registration surface for every code the domain
raises. The codes were registered module-locally during the feature build
(probe.py t03, permissions.py/secret.py t06/t07, managed/* t05,
service.py t09, native_intents.py t04, native_binding.py t013 — see
``specs/011-q4-mcp/reports/``) and are consolidated here per Constitution
III (契约先行). **Consolidation moved definitions only: every string value
is byte-identical to the module-local original**, so the wire shape stays
``"{code}: {message}"``, ``backend/plugin.MCP_ERROR_FAMILIES`` keeps its
rows, and every legacy-compat mutual proof keeps matching.

The owning modules now ``import`` their family from here and keep
re-exporting the names (consumer imports like ``backend.permissions
PERMISSION_*`` stay valid). ``ALL_CODES`` is closed: a new code is added
here first, and the guard tests in ``tests/codes/`` hold the invariants
(unique values, name == value, zero overlap with the legacy compat
vocabulary outside the carried-over rows).
"""
from __future__ import annotations

from types import MappingProxyType

# =============================================================================
# family: legacy compat store codes, carried over verbatim (V01/V09 mutual
# proof against sp ``plugins/server-compat/src/ordessa_server_compat/assets/
# mcp.py`` — these six strings ARE the legacy store's codes; the zero-overlap
# guard treats them as the documented shared subset, see tests/codes/).
# =============================================================================
MCP_NAME_INVALID = "MCP_NAME_INVALID"
MCP_DEFINITION_INVALID = "MCP_DEFINITION_INVALID"
MCP_TRANSPORT_UNSUPPORTED = "MCP_TRANSPORT_UNSUPPORTED"
MCP_CREDENTIAL_REFERENCE_REQUIRED = "MCP_CREDENTIAL_REFERENCE_REQUIRED"
MCP_REVISION_EXISTS = "MCP_REVISION_EXISTS"
MCP_ASSET_MISSING = "MCP_ASSET_MISSING"

#: the six legacy store codes carried verbatim above (guard-test vocabulary)
LEGACY_CARRIED_MCP_STORE_CODES = frozenset({
    MCP_NAME_INVALID, MCP_DEFINITION_INVALID, MCP_TRANSPORT_UNSUPPORTED,
    MCP_CREDENTIAL_REFERENCE_REQUIRED, MCP_REVISION_EXISTS, MCP_ASSET_MISSING,
})

# =============================================================================
# family: definition store / assignment domain codes (added by T01/T02)
# =============================================================================
MCP_CAS_CONFLICT = "MCP_CAS_CONFLICT"
MCP_OPERATION_CONFLICT = "MCP_OPERATION_CONFLICT"
MCP_SERVER_SCOPE_CONFLICT = "MCP_SERVER_SCOPE_CONFLICT"
MCP_OWNER_CONFLICT = "MCP_OWNER_CONFLICT"
MCP_REVISION_NOT_APPROVED = "MCP_REVISION_NOT_APPROVED"
MCP_DEFINITION_ARCHIVED = "MCP_DEFINITION_ARCHIVED"
MCP_ASSIGNMENT_INVALID = "MCP_ASSIGNMENT_INVALID"
MCP_TOOL_NOT_OBSERVED = "MCP_TOOL_NOT_OBSERVED"
MCP_CATALOG_MISSING = "MCP_CATALOG_MISSING"

# =============================================================================
# family: FR-10 refusal vocabulary (reserved at T01/T02; consumed from T03 on)
# =============================================================================
DEFINITION_INVALID = "DEFINITION_INVALID"
SECRET_UNRESOLVED = "SECRET_UNRESOLVED"
AUTH_REQUIRED = "AUTH_REQUIRED"
CONNECTION_FAILED = "CONNECTION_FAILED"
PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
CATALOG_CHANGED = "CATALOG_CHANGED"
PERMISSION_REFUSED = "PERMISSION_REFUSED"
OWNER_CONFLICT = "OWNER_CONFLICT"
ISOLATION_UNPROVEN = "ISOLATION_UNPROVEN"
UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"

# =============================================================================
# family: probe codes (registered in backend/probe.py through T03, reports/
# t03.md). The five legacy probe strings keep their exact values: the probe
# path replaced ``ordessa_server_compat.assets.mcp_probe`` whose five codes
# are the documented carried-over subset of this family.
# =============================================================================
PROBE_COMMAND_INVALID = "PROBE_COMMAND_INVALID"        # legacy-carried
PROBE_SPAWN_FAILED = "PROBE_SPAWN_FAILED"              # legacy-carried
PROBE_TIMEOUT = "PROBE_TIMEOUT"                        # legacy-carried
PROBE_FORMAT_INVALID = "PROBE_FORMAT_INVALID"          # legacy-carried
PROBE_RESPONSE_TOO_LARGE = "PROBE_RESPONSE_TOO_LARGE"  # legacy-carried
PROBE_AUTH_REQUIRED = "PROBE_AUTH_REQUIRED"
PROBE_CONNECTION_FAILED = "PROBE_CONNECTION_FAILED"
PROBE_CANCELLED = "PROBE_CANCELLED"
PROBE_PROTOCOL_MISMATCH = "PROBE_PROTOCOL_MISMATCH"
PROBE_REDIRECT_REFUSED = "PROBE_REDIRECT_REFUSED"
PROBE_URL_NOT_ALLOWED = "PROBE_URL_NOT_ALLOWED"

#: the five legacy probe codes carried verbatim (the six remaining PROBE_*
#: codes are T03 additions with no legacy counterpart; guard-test vocabulary)
LEGACY_CARRIED_PROBE_CODES = frozenset({
    PROBE_COMMAND_INVALID, PROBE_SPAWN_FAILED, PROBE_TIMEOUT,
    PROBE_FORMAT_INVALID, PROBE_RESPONSE_TOO_LARGE,
})

# =============================================================================
# family: permission-gate codes (registered in backend/permissions.py
# through T06, reports/t06-wiring.md; FR-09 / contracts §4)
# =============================================================================
PERMISSION_AUTHORITY_ABSENT = "PERMISSION_AUTHORITY_ABSENT"
PERMISSION_ENFORCEMENT_UNPROVEN = "PERMISSION_ENFORCEMENT_UNPROVEN"  # contracts §4 "permission-enforcement-unproven"
PERMISSION_ARGS_DIGEST_REQUIRED = "PERMISSION_ARGS_DIGEST_REQUIRED"

# =============================================================================
# family: credential-plan codes (registered in backend/secret.py through
# T07, reports/t05-domain.md-adjacent secret notes)
# =============================================================================
PLAN_STALE = "PLAN_STALE"
MCP_PLAN_BINDING_INVALID = "MCP_PLAN_BINDING_INVALID"

# =============================================================================
# family: managed-connection codes (registered in backend/managed/* through
# T05/T011, reports/t05-domain.md, t05-client.md, t011-http-client.md)
# =============================================================================
# lease state machine (managed/lease.py)
MCP_STATE_TRANSITION_INVALID = "MCP_STATE_TRANSITION_INVALID"
MCP_LEASE_MISSING = "MCP_LEASE_MISSING"
MCP_LEASE_BUSY = "MCP_LEASE_BUSY"
MCP_RECONCILE_REQUIRED = "MCP_RECONCILE_REQUIRED"
MCP_NOT_CONNECTED = "MCP_NOT_CONNECTED"
MCP_TOOL_NOT_APPROVED = "MCP_TOOL_NOT_APPROVED"
# tool catalog store (managed/catalog.py)
MCP_CATALOG_UNOBSERVABLE = "MCP_CATALOG_UNOBSERVABLE"
# session manager factory seam (managed/session_manager.py)
MCP_CLIENT_FACTORY_MISSING = "MCP_CLIENT_FACTORY_MISSING"
# limited-substitute stdio client (managed/client_stdio.py)
MCP_CLIENT_NOT_STARTED = "MCP_CLIENT_NOT_STARTED"
MCP_CLIENT_NOT_CONNECTED = "MCP_CLIENT_NOT_CONNECTED"
MCP_CLIENT_CLOSED = "MCP_CLIENT_CLOSED"
MCP_CLIENT_SPAWN_FAILED = "MCP_CLIENT_SPAWN_FAILED"
MCP_CLIENT_RESPONSE_INVALID = "MCP_CLIENT_RESPONSE_INVALID"
MCP_CLIENT_CLEANUP_FAILED = "MCP_CLIENT_CLEANUP_FAILED"
# managed HTTP client (managed/client_http.py)
MCP_HTTP_URL_NOT_ALLOWED = "MCP_HTTP_URL_NOT_ALLOWED"
MCP_HTTP_REDIRECT_REFUSED = "MCP_HTTP_REDIRECT_REFUSED"
MCP_HTTP_REQUEST_REFUSED = "MCP_HTTP_REQUEST_REFUSED"
MCP_HTTP_HOST_ORIGIN_MISMATCH = "MCP_HTTP_HOST_ORIGIN_MISMATCH"
MCP_HTTP_TRANSPORT_DOWN = "MCP_HTTP_TRANSPORT_DOWN"

# =============================================================================
# family: service/wire seam codes (registered in backend/service.py through
# T09/T013, reports/t09-service.md — provider-absence and permit fences)
# =============================================================================
APPLICATION_PORT_ABSENT = "APPLICATION_PORT_ABSENT"
SUBMISSION_PERMIT_REQUIRED = "SUBMISSION_PERMIT_REQUIRED"
EXPECTED_REVISION_REQUIRED = "EXPECTED_REVISION_REQUIRED"
SUBMISSION_GATE_AMBIGUOUS = "SUBMISSION_GATE_AMBIGUOUS"

# =============================================================================
# family: native-lane intent codes (registered in backend/native_intents.py
# through T04, reports/t04-adapters.md; raised through the composition-
# injected planner on the submission path)
# =============================================================================
MCP_NATIVE_NAME_CONFLICT = "MCP_NATIVE_NAME_CONFLICT"
MCP_CREDENTIAL_PROVENANCE_UNPROVEN = "MCP_CREDENTIAL_PROVENANCE_UNPROVEN"
MCP_NATIVE_TARGET_UNSUPPORTED = "MCP_NATIVE_TARGET_UNSUPPORTED"
MCP_PERMISSION_ENFORCEMENT_UNPROVEN = "MCP_PERMISSION_ENFORCEMENT_UNPROVEN"

# =============================================================================
# family: Harness C4 binding codes (registered in backend/native_binding.py
# through T013, reports/t013-harness-wiring.md — the eight T013 additions)
# =============================================================================
MCP_GATE_CAPABILITY_UNSUPPORTED = "MCP_GATE_CAPABILITY_UNSUPPORTED"
MCP_GATE_FRAGMENT_INVALID = "MCP_GATE_FRAGMENT_INVALID"
MCP_GATE_BUSY = "MCP_GATE_BUSY"
MCP_GATE_RESUME_UNAVAILABLE = "MCP_GATE_RESUME_UNAVAILABLE"
MCP_VERIFICATION_MISMATCH = "MCP_VERIFICATION_MISMATCH"
MCP_ISOLATION_UNPROVEN = "MCP_ISOLATION_UNPROVEN"
MCP_GATE_REFUSED = "MCP_GATE_REFUSED"
NATIVE_PLANNER_ABSENT = "NATIVE_PLANNER_ABSENT"

#: the eleven codes this domain shares with the legacy compat surface by
#: design (wire compatibility): the six MCP store codes and the five probe
#: codes. The zero-overlap guard asserts that OUTSIDE this set the closed
#: vocabulary collides with nothing registered by compat, workspace or the
#: host's static table.
LEGACY_CARRIED_CODES = frozenset(
    LEGACY_CARRIED_MCP_STORE_CODES | LEGACY_CARRIED_PROBE_CODES)

_CODE_NAMES: "tuple[str, ...]" = (
    # legacy compat store (carried verbatim)
    "MCP_NAME_INVALID", "MCP_DEFINITION_INVALID", "MCP_TRANSPORT_UNSUPPORTED",
    "MCP_CREDENTIAL_REFERENCE_REQUIRED", "MCP_REVISION_EXISTS",
    "MCP_ASSET_MISSING",
    # definition store / assignment domain
    "MCP_CAS_CONFLICT", "MCP_OPERATION_CONFLICT", "MCP_SERVER_SCOPE_CONFLICT",
    "MCP_OWNER_CONFLICT", "MCP_REVISION_NOT_APPROVED",
    "MCP_DEFINITION_ARCHIVED", "MCP_ASSIGNMENT_INVALID",
    "MCP_TOOL_NOT_OBSERVED", "MCP_CATALOG_MISSING",
    # FR-10 vocabulary
    "DEFINITION_INVALID", "SECRET_UNRESOLVED", "AUTH_REQUIRED",
    "CONNECTION_FAILED", "PROTOCOL_MISMATCH", "CATALOG_CHANGED",
    "PERMISSION_REFUSED", "OWNER_CONFLICT", "ISOLATION_UNPROVEN",
    "UNKNOWN_OUTCOME",
    # probe
    "PROBE_COMMAND_INVALID", "PROBE_SPAWN_FAILED", "PROBE_TIMEOUT",
    "PROBE_FORMAT_INVALID", "PROBE_RESPONSE_TOO_LARGE", "PROBE_AUTH_REQUIRED",
    "PROBE_CONNECTION_FAILED", "PROBE_CANCELLED", "PROBE_PROTOCOL_MISMATCH",
    "PROBE_REDIRECT_REFUSED", "PROBE_URL_NOT_ALLOWED",
    # permission gates
    "PERMISSION_AUTHORITY_ABSENT", "PERMISSION_ENFORCEMENT_UNPROVEN",
    "PERMISSION_ARGS_DIGEST_REQUIRED",
    # credential plan
    "PLAN_STALE", "MCP_PLAN_BINDING_INVALID",
    # managed connections
    "MCP_STATE_TRANSITION_INVALID", "MCP_LEASE_MISSING", "MCP_LEASE_BUSY",
    "MCP_RECONCILE_REQUIRED", "MCP_NOT_CONNECTED", "MCP_TOOL_NOT_APPROVED",
    "MCP_CATALOG_UNOBSERVABLE", "MCP_CLIENT_FACTORY_MISSING",
    "MCP_CLIENT_NOT_STARTED", "MCP_CLIENT_NOT_CONNECTED", "MCP_CLIENT_CLOSED",
    "MCP_CLIENT_SPAWN_FAILED", "MCP_CLIENT_RESPONSE_INVALID",
    "MCP_CLIENT_CLEANUP_FAILED", "MCP_HTTP_URL_NOT_ALLOWED",
    "MCP_HTTP_REDIRECT_REFUSED", "MCP_HTTP_REQUEST_REFUSED",
    "MCP_HTTP_HOST_ORIGIN_MISMATCH", "MCP_HTTP_TRANSPORT_DOWN",
    # service/wire seam
    "APPLICATION_PORT_ABSENT", "SUBMISSION_PERMIT_REQUIRED",
    "EXPECTED_REVISION_REQUIRED", "SUBMISSION_GATE_AMBIGUOUS",
    # native-lane intents
    "MCP_NATIVE_NAME_CONFLICT", "MCP_CREDENTIAL_PROVENANCE_UNPROVEN",
    "MCP_NATIVE_TARGET_UNSUPPORTED", "MCP_PERMISSION_ENFORCEMENT_UNPROVEN",
    # Harness C4 binding
    "MCP_GATE_CAPABILITY_UNSUPPORTED", "MCP_GATE_FRAGMENT_INVALID",
    "MCP_GATE_BUSY", "MCP_GATE_RESUME_UNAVAILABLE",
    "MCP_VERIFICATION_MISMATCH", "MCP_ISOLATION_UNPROVEN", "MCP_GATE_REFUSED",
    "NATIVE_PLANNER_ABSENT",
)

#: the closed vocabulary: every code this domain may raise. A code not in
#: this frozenset is not an MCP domain code (tests/codes/ guards it).
ALL_CODES: "frozenset[str]" = frozenset(
    globals()[name] for name in _CODE_NAMES)

#: code constant name -> string value, the unique-value guard's material:
#: two names sharing one value are a registration collision and red here.
CODE_BY_NAME: MappingProxyType = MappingProxyType(
    {name: globals()[name] for name in _CODE_NAMES})


class McpError(RuntimeError):
    """A typed refusal of one MCP definition, revision or scope operation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
