"""Ownership and server-verified scope (FR02/FR03, gate G07/G08).

The service injects an `AuthorizationContext` whose project binding is the
one the server verified; a client-supplied project assertion that the
context cannot back is refused before any lookup. A foreign-scoped read
returns the same `NOT_FOUND` sentinel as a genuinely missing one, so the
answer never distinguishes "hidden" from "absent".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from . import errors, limits


class ScopeKind(str, Enum):
    """Assignment layers, lowest first (data-model §范围解释)."""

    USER_GLOBAL = "user_global"
    USER_GLOBAL_HARNESS = "user_global_harness"
    PROJECT = "project"
    PROJECT_HARNESS = "project_harness"
    PROFILE = "profile"
    SESSION = "session"


LAYER_ORDER: tuple[ScopeKind, ...] = (
    ScopeKind.USER_GLOBAL,
    ScopeKind.USER_GLOBAL_HARNESS,
    ScopeKind.PROJECT,
    ScopeKind.PROJECT_HARNESS,
    ScopeKind.PROFILE,
    ScopeKind.SESSION,
)

#: The only non-brand harness binding; it applies at the current brand and
#: never changes it (FR03 "Harness 绑定不混品牌").
ANY_HARNESS = "any"


def _check_id(value: str, field_name: str, max_chars: int) -> None:
    if not isinstance(value, str) or not value:
        raise errors.refused(errors.DEFINITION_INVALID, item_id=field_name,
                             detail="identifier must be a non-empty string")
    if len(value) > max_chars:
        raise errors.refused(errors.DEFINITION_INVALID, item_id=field_name,
                             detail=f"identifier exceeds {max_chars} characters")


@dataclass(frozen=True)
class Principal:
    id: str

    def __post_init__(self) -> None:
        _check_id(self.id, "principal", limits.MAX_PRINCIPAL_CHARS)


@dataclass(frozen=True)
class ServerScope:
    id: str

    def __post_init__(self) -> None:
        _check_id(self.id, "server_scope", limits.MAX_DEFINITION_ID_CHARS)


@dataclass(frozen=True)
class ProjectId:
    id: str

    def __post_init__(self) -> None:
        _check_id(self.id, "project_id", limits.MAX_DEFINITION_ID_CHARS)


@dataclass(frozen=True)
class ProfileId:
    id: str

    def __post_init__(self) -> None:
        _check_id(self.id, "profile_id", limits.MAX_DEFINITION_ID_CHARS)


@dataclass(frozen=True)
class SessionId:
    id: str

    def __post_init__(self) -> None:
        _check_id(self.id, "session_id", limits.MAX_DEFINITION_ID_CHARS)


@dataclass(frozen=True)
class AuthorizationContext:
    """Issued by the service only; a client cannot construct a verified one.

    `verified_project` is the project identity the server checked itself.
    `require_project` is the single gate for "may this request act on
    project P": a claim without a matching verification is refused
    (G07 counter-example: 客户端伪 projectId).
    """

    principal: Principal
    server_scope: ServerScope
    verified_project: ProjectId | None = None

    @staticmethod
    def issued_by_service(
        principal: Principal,
        server_scope: ServerScope,
        verified_project: ProjectId | None = None,
    ) -> "AuthorizationContext":
        return AuthorizationContext(principal, server_scope, verified_project)

    def require_project(self, claimed_project_id: str | None) -> ProjectId | None:
        if claimed_project_id is None:
            return None
        if self.verified_project is None or self.verified_project.id != claimed_project_id:
            raise errors.refused(
                errors.PERMISSION_EXCEEDS_CEILING,
                item_id="project_id",
                detail="project assertion is not server-verified for this context",
            )
        return self.verified_project


class _NotFound:
    """One shared marker: not-found and hidden-read-not-found are identical."""

    _singleton: "_NotFound | None" = None

    def __new__(cls) -> "_NotFound":
        if cls._singleton is None:
            cls._singleton = super().__new__(cls)
        return cls._singleton

    def __repr__(self) -> str:
        return "NOT_FOUND"


NOT_FOUND = _NotFound()


@dataclass(frozen=True)
class Diagnostic:
    """An item-level finding that is reported, not raised."""

    code: str
    item_id: str
    detail: str

    def as_mapping(self) -> dict[str, str]:
        return {"code": self.code, "item_id": self.item_id, "detail": self.detail}


@dataclass(frozen=True)
class DefinitionOwnership:
    """The ownership facts a visibility decision needs, nothing more."""

    definition_id: str
    server_scope: ServerScope
    owner_principal: Principal
    origin_scope: str
    origin_owner: str


@dataclass(frozen=True)
class ViewerScope:
    principal: Principal
    server_scope: ServerScope
    project: ProjectId | None
    profile_id: ProfileId | None
    session_id: SessionId | None
    session_profile_id: ProfileId | None
    session_harness_id: str | None
    harness_id: str


#: Attribute stamping a `ViewerScope` as issued by a service's own
#: authorization path (§C1: a client must not name a viewer it is not
#: attested as). The stamp value is the issuing service's private token, so a
#: viewer issued by one service is not valid at another; only
#: `DefinitionService.authorize_viewer` ever applies it.
ISSUED_VIEWER_ATTR = "_ordessa_issued_viewer_token"


def issue_viewer(viewer: ViewerScope, token: object) -> ViewerScope:
    """Stamp `viewer` as issued under `token`; returns the same object."""
    object.__setattr__(viewer, ISSUED_VIEWER_ATTR, token)
    return viewer


def viewer_issuance(viewer: object) -> object | None:
    """The issuing service's token, or None for a viewer never issued."""
    return getattr(viewer, ISSUED_VIEWER_ATTR, None)


def harness_binding_matches(*, target_harness_id: str, assignment_harness_id: str) -> bool:
    if assignment_harness_id == ANY_HARNESS or target_harness_id == ANY_HARNESS:
        return True
    return target_harness_id == assignment_harness_id


def profile_definition_usable(
    *,
    origin_owner_profile_id: str,
    viewer: ViewerScope,
) -> bool:
    """A profile-origin definition serves only that profile and its
    legitimate same-harness sessions (G08). A session that cannot prove it
    is on this harness fails closed."""
    if origin_owner_profile_id == "":
        return False
    if viewer.profile_id is not None and viewer.profile_id.id == origin_owner_profile_id:
        return True
    return (
        viewer.session_profile_id is not None
        and viewer.session_profile_id.id == origin_owner_profile_id
        and viewer.session_harness_id == viewer.harness_id
    )


def visible_to(definition: DefinitionOwnership, viewer: ViewerScope) -> bool:
    if definition.server_scope.id != viewer.server_scope.id:
        return False
    if definition.origin_scope == "project":
        return (
            definition.origin_owner != ""
            and viewer.project is not None
            and viewer.project.id == definition.origin_owner
            and definition.owner_principal.id == viewer.principal.id
        )
    if definition.origin_scope == "profile":
        return (
            definition.owner_principal.id == viewer.principal.id
            and profile_definition_usable(
                origin_owner_profile_id=definition.origin_owner, viewer=viewer
            )
        )
    if definition.origin_scope == "public":
        return definition.owner_principal.id == viewer.principal.id
    return False


def scoped_read(
    definition: DefinitionOwnership | None,
    viewer: ViewerScope,
) -> DefinitionOwnership | _NotFound:
    """Foreign-scoped and missing reads return the identical `NOT_FOUND`
    sentinel; a caller cannot tell the two apart (G07 existence leak)."""
    if definition is None:
        return NOT_FOUND
    if not visible_to(definition, viewer):
        return NOT_FOUND
    return definition


def visible_definition_ids(
    ownership_by_id: Mapping[str, "DefinitionOwnership | None"],
    viewer: ViewerScope,
) -> tuple[frozenset[str], tuple[Diagnostic, ...]]:
    """Split a mapping id -> DefinitionOwnership into viewable ids.

    Foreign-principal / foreign-project ids are dropped WITHOUT a
    diagnostic: an observable hidden set would let a caller infer that
    another principal's definitions exist. Only same-principal ownership
    problems (e.g. the viewer's own profile-scoped definition reached from
    a foreign brand's session) are reportable reasons.
    """
    viewable: set[str] = set()
    hidden: list[Diagnostic] = []
    for definition_id, ownership in ownership_by_id.items():
        if ownership is None:
            continue
        if ownership.owner_principal.id != viewer.principal.id:
            continue
        if not visible_to(ownership, viewer):
            hidden.append(
                Diagnostic(
                    code=errors.ASSIGNMENT_CONFLICT,
                    item_id=definition_id,
                    detail="definition ownership is outside the verified scope",
                )
            )
            continue
        viewable.add(definition_id)
    return frozenset(viewable), tuple(hidden)
