"""The Skills assignments domain (docs/design/skills-v2/data-model.md).

One domain-owned slice of the product data root: durable `SkillAssignment`
rows, the deterministic six-layer resolver, content-ownership authorization
and the frozen commit snapshot. Profile-layer input and the admin policy
layer arrive through the injected ports in :mod:`ports` (api-requests.md
§G3/§G5 — the real profile-api and permissions-api do not exist yet, so
this package never imports them; a typed protocol is the seam).

Import boundaries hold as everywhere in this package
(tests/test_dependency_direction.py): only the stdlib, `pacthold` and
sibling areas of `ordessa_skills` are reached; no host, no plugin sibling,
no `ordessa_server_compat`.
"""
from __future__ import annotations

from .model import (
    ANY_HARNESS,
    DECISION_DISABLE,
    DECISION_ENABLE,
    LAYER_MANDATORY,
    LAYER_ORDER,
    SCOPE_PROJECT,
    SCOPE_USER_GLOBAL,
    SCOPE_KINDS,
    AssignmentError,
    SkillAssignment,
)
from .store import AssignmentStore, AssignmentScope
from .authorization import (
    AssetAuthorization,
    AuthorizationError,
    ORIGIN_PROFILE_PRIVATE,
    ORIGIN_PROJECT_PRIVATE,
    ORIGIN_PUBLIC,
    origin_of,
)
from .resolver import (
    Resolution,
    ResolutionTarget,
    ResolverDeps,
    SkillsResolutionService,
    resolve_effective,
)
from .snapshot import (
    SkillSnapshot,
    SnapshotError,
    build_snapshot,
    matches_frozen,
    assert_apply_eligible,
)
from .ports import (
    MandatoryPolicyPort,
    MandatoryRule,
    ProfileLayerPort,
    ProfileSkillEntry,
    RevisionGate,
    SessionOverride,
    WorkspaceLookup,
)

__all__ = [
    # model
    "SkillAssignment", "AssignmentError", "SCOPE_KINDS", "SCOPE_USER_GLOBAL",
    "SCOPE_PROJECT", "DECISION_ENABLE", "DECISION_DISABLE", "ANY_HARNESS",
    "LAYER_ORDER", "LAYER_MANDATORY",
    # store
    "AssignmentStore", "AssignmentScope",
    # ports (injected seams)
    "ProfileLayerPort", "ProfileSkillEntry", "MandatoryPolicyPort",
    "MandatoryRule", "SessionOverride", "WorkspaceLookup", "RevisionGate",
    # authorization
    "AssetAuthorization", "AuthorizationError", "ORIGIN_PUBLIC",
    "ORIGIN_PROJECT_PRIVATE", "ORIGIN_PROFILE_PRIVATE", "origin_of",
    # resolver
    "resolve_effective", "Resolution", "ResolutionTarget", "ResolverDeps",
    "SkillsResolutionService",
    # snapshot
    "SkillSnapshot", "SnapshotError", "build_snapshot", "matches_frozen",
    "assert_apply_eligible",
]
