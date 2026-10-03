"""Stable Server plugin contract (`server_plugin_api`).

This package is the boundary plugins program against: it must never import
`ordessa_server`, `pacthold` product code, or any plugin. It carries only the
types the contract needs — descriptors, the activation context, the
registration a plugin returns, and the typed errors a host rejects startup
with. Nothing here dispatches, stores, or composes; a host implements those.

Versioning: `SERVER_PLUGIN_API_VERSION` is the integer a plugin descriptor
declares compatibility with. A host refusing a descriptor it cannot honour is
the contract working, not a failure.

Since T014-S2c the package also carries the vocabulary the host and the plugins
*share* rather than one side owning: `ServerError` (what a plugin raises), the
canonical record encoding, the wire/1 family set with its static code→family
table and the `WireError` object, and the four param-shape primitives. Those
moved out of `ordessa_server.errors`, `.records` and `.wire.{errors,handlers}`
because a plugin importing a host internal is the breach AGENTS rule 3 forbids,
and moving them into one sibling plugin instead would have made the other two
plugins import that sibling. The host imports them from here too — one
implementation, so a frozen refusal string cannot drift between sides. What
stays host-side is per-composition state (the contributed family aggregate).
"""
from __future__ import annotations

from .acp_admission import (
    ACP_ADMISSION_PORT,
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionPort,
    AcpAdmissionResult,
    AcpAttachmentReference,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
)
from .contract import (
    PLUGIN_METHOD_ID,
    SERVER_PLUGIN_API_VERSION,
    HttpRouteDescriptor,
    ServerCliPlan,
    ServerFlagSpec,
    ServerMethodDescriptor,
    ServerPlugin,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)
from .contributions import (
    CLI_SERVER_FLAGS_API_VERSION,
    CLI_SERVER_FLAGS_POINT_ID,
    CONTRIBUTION_POINT_ID,
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
    WIRE_DISCOVERY_FACETS_API_VERSION,
    WIRE_DISCOVERY_FACETS_POINT_ID,
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    AbsentContribution,
    Contribution,
    ContributionBatch,
    ContributionPointSpec,
    ServerContributionHandler,
    StagedBatch,
    stage_contributions,
    unique_contribution_point_specs,
)
from .internal_errors import ServerError, unavailable
from .record_encoding import (
    MAX_CANONICAL_BYTES,
    canonical,
    digest,
    reject_sensitive_keys,
)
from .wire_errors import (
    FAMILIES,
    STATIC_ERROR_FAMILIES,
    FamilyResolver,
    WireError,
    converge_family,
    family_for,
)
from .wire_shape import bounded, request_id, require, version
from .errors import (
    CleanupError,
    ContributionAccessError,
    ContributionAmbiguousError,
    ContributionBatchCleanupError,
    ContributionCleanupError,
    ContributionDeclarationError,
    ContributionOwnerBusyError,
    ContributionPointHeldError,
    ContributionPointUnboundError,
    ContributionRollbackRefusedError,
    ContributionStateError,
    ContributionVersionRefusedError,
    CyclicDependencyError,
    DependencyError,
    DependentActiveError,
    DuplicateContributionError,
    DuplicateHttpRouteError,
    DuplicateMethodError,
    DuplicatePluginError,
    DuplicateStreamRouteError,
    HostAdmissionClosedError,
    HttpRouteShapeChangedError,
    HttpRouteUnmountedError,
    InvalidDeclarationError,
    PluginCleanupError,
    PortConflictError,
    RequiredContributionMissingError,
    ServerPluginError,
)

__all__ = [
    "ACP_ADMISSION_PORT",
    "ACP_ADMISSION_PORT_VERSION",
    "AcpAdmissionPort",
    "AcpAdmissionResult",
    "AcpAttachmentReference",
    "AcpChannelBinding",
    "AcpPermissionDecision",
    "AcpSubmissionRequest",
    "SERVER_PLUGIN_API_VERSION",
    "PLUGIN_METHOD_ID",
    "HttpRouteDescriptor",
    "ServerMethodDescriptor",
    "ServerPlugin",
    "ServerPluginContext",
    "ServerPluginDescriptor",
    "ServerPluginRegistration",
    "StreamRouteDescriptor",
    "CONTRIBUTION_POINT_ID",
    "PACTHOLD_CONTRIBUTIONS_API_VERSION",
    "PACTHOLD_CONTRIBUTIONS_POINT_ID",
    "WIRE_ERROR_FAMILIES_API_VERSION",
    "WIRE_ERROR_FAMILIES_POINT_ID",
    "WIRE_DISCOVERY_FACETS_API_VERSION",
    "WIRE_DISCOVERY_FACETS_POINT_ID",
    "AbsentContribution",
    "Contribution",
    "ContributionBatch",
    "ContributionPointSpec",
    "ServerContributionHandler",
    "StagedBatch",
    "stage_contributions",
    "unique_contribution_point_specs",
    "ServerPluginError",
    "DuplicateMethodError",
    "DuplicatePluginError",
    "DuplicateStreamRouteError",
    "DuplicateHttpRouteError",
    "HttpRouteShapeChangedError",
    "HttpRouteUnmountedError",
    "DependencyError",
    "CyclicDependencyError",
    "DependentActiveError",
    "PortConflictError",
    "InvalidDeclarationError",
    "PluginCleanupError",
    "CleanupError",
    "ContributionDeclarationError",
    "DuplicateContributionError",
    "RequiredContributionMissingError",
    "ContributionStateError",
    "ContributionRollbackRefusedError",
    "ContributionCleanupError",
    "ContributionBatchCleanupError",
    "ContributionPointUnboundError",
    "ContributionVersionRefusedError",
    "ContributionPointHeldError",
    "HostAdmissionClosedError",
    "ContributionOwnerBusyError",
    "ContributionAccessError",
    "ContributionAmbiguousError",
    "ServerError",
    "unavailable",
    "MAX_CANONICAL_BYTES",
    "canonical",
    "digest",
    "reject_sensitive_keys",
    "FAMILIES",
    "STATIC_ERROR_FAMILIES",
    "FamilyResolver",
    "WireError",
    "converge_family",
    "family_for",
    "bounded",
    "request_id",
    "require",
    "version",
]
