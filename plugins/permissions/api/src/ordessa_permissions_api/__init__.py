"""Ordessa Permissions API - the typed domain contract of the permissions domain.

Pure domain: strongly typed rules, a non-widenable administrator ceiling, a
narrowing-only intent, the snapshot a decision was made under, and the
§C1 decision and approval shapes. No storage, no service, no host import.

Two answers stay distinct throughout: `unsupported` (this cannot be honoured,
say so) and `unknown` (we cannot tell, so nothing with side effects proceeds).
"""
from __future__ import annotations

from . import authority, brand, ceilings, codes, decisions, intents, ports, \
    request_facts, rules, snapshots, synthesis, wire_family
from .authority import (
    AUTHORITY_QUERY_PORT,
    AUTHORITY_QUERY_PORT_VERSION,
    AuthorityRecord,
    AuthorityScope,
    AuthoritySourceKind,
    AuthorityStateKind,
    PermissionsAuthorityQueryPort,
    authority_id_for,
)
from .brand import BRAND_NATIVE_MODES, BrandMode, declared_native_modes
from .ceilings import (
    TOOL_EXPOSURE,
    CeilingEntry,
    CeilingSource,
    EffectiveCeiling,
    ExposureLevel,
    PolicyCeiling,
    intersect_ceilings,
)
from .codes import (
    DEFAULT_REMEDIES,
    MAX_DIAGNOSTIC_TEXT,
    SCHEMA_CODES,
    CodeKind,
    POLICY_DENY,
    PolicyDenyCode,
    PolicyRefusal,
    RefusalCode,
    code_kind,
    enforcement_codes,
    is_enforcement_code,
    probe,
)
from .decisions import (
    GRANT_TTL,
    AlreadyRecorded,
    AllowedOnce,
    ApprovalDecision,
    ApprovalFact,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
    ApprovalStateKind,
    AuthorizationDecision,
    BoundedApprovalScope,
    BoundGrant,
    DecideResult,
    DecisionReason,
    Denied,
    InvalidApproval,
    NativeReceipt,
    OnceApprovalScope,
    PendingApproval,
    QueriedApproval,
    QueryUnknown,
    QueryOutcome,
    Recorded,
    UnknownApproval,
    approval_id_for,
    scope_to_record,
)
from .intents import NO_INTENT_REVISION, PermissionIntent
from .ports import (
    PERMISSIONS_AUTHORIZER_PORT,
    PERMISSIONS_AUTHORIZER_PORT_VERSION,
    EvaluationOutcome,
    PermissionsAuthorizerPort,
)
from .request_facts import ArgumentDigest, ExecutionState, OperationRequest, \
    build_operation_request
from .rules import (
    MAX_PRIORITY,
    MAX_RULES,
    TOOL_KEYS,
    AdminAuthorization,
    RuleAction,
    Scope,
    TargetMatcher,
    ToolIdentity,
    TypedRule,
    known_tool_keys,
)
from .snapshots import MAX_SNAPSHOT_TTL, EffectivePolicySnapshot
from .synthesis import (
    DECISION_TTL,
    PolicyRefused,
    PolicySynthesized,
    SynthesisResult,
    evaluate_authorization,
    select_intent_action,
    synthesize,
)
from .wire_family import (
    PERMISSION_ERROR_FAMILIES,
    permissions_wire_family,
    wire_body_for,
)

__version__ = "0.1.0"

_MODULES = (codes, rules, ceilings, intents, brand, request_facts, decisions, snapshots,
            synthesis, wire_family, ports, authority)
# The published surface is exactly what the owning modules declare, so an export
# can never drift away from the module that defines it.
__all__ = tuple(sorted({name for module in _MODULES for name in module.__all__}))
