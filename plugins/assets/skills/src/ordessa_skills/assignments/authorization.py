"""Content-ownership and workspace-identity authorization (FR03/FR09;
verification.md G07; data-model.md §内容与版本).

The rule set, straight from the data model:

* 公共库可用于已授权项目 — a `public` origin is selectable by any target
  whose project identity the Workspace registry authorizes.
* 项目专用仅该 projectId — a `project` origin is usable only while the
  resolution targets exactly that project, and only through that project's
  own layers (or the session override of that same project).
* Profile 专用仅该 Profile — a `profile` origin is usable only through
  that Profile's own facet layer; it never leaks into a project or
  user-global row, and —  Profile 的 harnessId 固定 — never across harnesses
  (the resolver's ``PROFILE_HARNESS_MISMATCH`` refusal plus the origin
  check here close G07 「跨 Harness 引用 Profile 专用项」).

Origin source of truth (deviation, authorized by AGENTS.md rule 5):
data-model.md lists `originScope`/`originOwner` on SkillRecord, but the
shared ``server_assets`` table has no such column and this slice may not
edit the pacthold migration chain. The domain therefore derives the origin
from the server-side ``source`` string with a documented encoding —
``project:<projectId>`` / ``profile:<profileId>`` / anything else
(``local:*``, ``git:…``) is public. Ownership is read **only** from the
asset row; a client-supplied owner or arbitrary path is never consulted
(FR09, contracts.md: 不接受自报 owner 或任意本地文件路径). When C0 adds
the real origin columns, :func:`origin_of` becomes the one place to switch.

Workspace identity: the project layer is consulted only after
:meth:`AssetAuthorization.authorize_project` confirms the projectId in
the injected :class:`~ordessa_skills.assignments.ports.WorkspaceLookup`
(api-requests §G5 独立路径: 「以 workspace.records.get() 存在性校验 + 本地
server_scope 列实现」). A fabricated or unknown projectId raises the typed
``WORKSPACE_UNKNOWN`` — never a silently empty effective set (G07).
"""
from __future__ import annotations

from typing import Any, Mapping

from ..api.errors import AssetDomainError
from ..library.records import SKILL_KIND
from .model import LAYER_PROFILE, LAYER_PROJECT_ANY, LAYER_PROJECT_HARNESS, \
    LAYER_SESSION_OVERRIDE, LAYER_MANDATORY
from .ports import WorkspaceLookup

ORIGIN_PUBLIC = "public"
ORIGIN_PROJECT_PRIVATE = "project"
ORIGIN_PROFILE_PRIVATE = "profile"
ORIGINS = (ORIGIN_PUBLIC, ORIGIN_PROJECT_PRIVATE, ORIGIN_PROFILE_PRIVATE)

#: Layers that may reference project-private content, and only when the
#: resolution target *is* that project (checked separately).
_PROJECT_LAYERS = frozenset((LAYER_PROJECT_ANY, LAYER_PROJECT_HARNESS,
                             LAYER_SESSION_OVERRIDE, LAYER_MANDATORY))


class AuthorizationError(AssetDomainError):
    """One assignment/read was refused by the ownership or identity rules
    (codes: ``WORKSPACE_UNKNOWN``, ``WORKSPACE_ARCHIVED``,
    ``RESOLUTION_FOREIGN_CONTENT``, ``PROFILE_UNKNOWN``,
    ``PROFILE_HARNESS_MISMATCH``, ``ASSIGNMENT_ASSET_UNKNOWN``)."""


def origin_of(source: str | None) -> tuple[str, str | None]:
    """The ``(origin_scope, origin_owner)`` pair encoded in the server-side
    ``source`` column (see module docstring for the encoding and its
    migration note)."""
    text = source or ""
    for prefix, origin in (("project:", ORIGIN_PROJECT_PRIVATE),
                           ("profile:", ORIGIN_PROFILE_PRIVATE)):
        if text.startswith(prefix):
            owner = text[len(prefix):].split("|", 1)[0]
            return origin, (owner or None)
    return ORIGIN_PUBLIC, None


class AssetAuthorization:
    """Answers, for one resolution request: is this asset's content usable
    here, and is this project identity real? Every decision reads the
    server-stored row or the injected registry — never a caller argument."""

    def __init__(self, *, workspace_lookup: WorkspaceLookup | None = None,
                 server_scope: str) -> None:
        self.workspace_lookup = workspace_lookup
        self.server_scope = server_scope

    # -- workspace identity -----------------------------------------------------

    def authorize_project(self, project_id: str) -> Mapping[str, Any]:
        """The stable, server-authorized project identity behind the
        project layer. Unknown/fabricated ids are refused with a type, not
        answered with an empty scope (G07 「客户端伪 projectId」)."""
        if self.workspace_lookup is None:
            # No registry injected: honest refusal beats pretending that
            # every id is (not) valid — the seam is disclosed, not faked.
            raise AuthorizationError(
                "WORKSPACE_UNKNOWN",
                "project resolution needs the WorkspaceLookup port injected "
                "(api-requests.md §G5)")
        record = self.workspace_lookup.get(project_id)
        if record is None:
            raise AuthorizationError(
                "WORKSPACE_UNKNOWN",
                f"projectId {project_id!r} is not an authorized workspace "
                "of this server data domain", detail=project_id)
        archived = (record.get("archived_at")
                    if isinstance(record, Mapping) else None)
        if archived:
            # ux.md §Settings: 项目消失/无权时停止编辑 — the same
            # authorization gate the edit surface uses covers resolution.
            raise AuthorizationError(
                "WORKSPACE_ARCHIVED",
                f"workspace {project_id!r} is archived", detail=project_id)
        return record

    # -- content ownership --------------------------------------------------------

    def assert_usable(self, *, asset_id: str, asset_row: Mapping[str, Any],
                      via_layer: str, project_id: str | None,
                      profile_id: str | None) -> tuple[str, str | None]:
        """Ownership check for one reference made by ``via_layer``.

        Returns the ``(origin_scope, origin_owner)`` for the resolution
        view; raises the typed ``RESOLUTION_FOREIGN_CONTENT`` when the
        content may not be used at that layer (G07 「A 专用内容给 B」/
        Profile 专用被公开). A missing/non-skill row is
        ``ASSIGNMENT_ASSET_UNKNOWN`` — 引用缺失 is a refusal, not a filter.
        """
        if asset_row is None:
            raise AuthorizationError(
                "ASSIGNMENT_ASSET_UNKNOWN",
                "the assignment references an unknown asset", detail=asset_id)
        if str(asset_row["kind"]) != SKILL_KIND:
            raise AuthorizationError(
                "ASSIGNMENT_ASSET_UNKNOWN",
                "the assignment references a non-skill asset", detail=asset_id)
        origin, owner = origin_of(asset_row["source"])
        if origin == ORIGIN_PUBLIC:
            return origin, owner
        if origin == ORIGIN_PROJECT_PRIVATE:
            if via_layer not in _PROJECT_LAYERS or not owner \
                    or owner != project_id:
                raise AuthorizationError(
                    "RESOLUTION_FOREIGN_CONTENT",
                    f"project-private skill {asset_id} is usable only by "
                    f"project {owner!r} through its own layers",
                    detail=f"{via_layer}/{project_id}")
            return origin, owner
        # profile-private: only that Profile's facet layer, and the Profile
        # harness pin was already enforced by the resolver before it read
        # the layer (data-model: Profile 的 harnessId 固定).
        if via_layer != LAYER_PROFILE or not owner or owner != profile_id:
            raise AuthorizationError(
                "RESOLUTION_FOREIGN_CONTENT",
                f"profile-private skill {asset_id} is usable only by "
                f"profile {owner!r} through its own facet",
                detail=f"{via_layer}/{profile_id}")
        return origin, owner
