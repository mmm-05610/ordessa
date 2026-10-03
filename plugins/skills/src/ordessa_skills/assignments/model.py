"""The `SkillAssignment` row (docs/design/skills-v2/data-model.md §内容与版本).

Row shape, verbatim from the data model::

    SkillAssignment: serverScope, principal, scopeKind, scopeId,
                     harnessId | any, assetId, decision: enable | disable,
                     revision?, rowVersion

Rules this model makes unforgeable (they are validated at construction, so
no caller — store, resolver or wire — can build an illegal row):

* ``enable`` **requires** a revision — 分配引用版本必须为已经安装、校验并批
  准的 revision. The *approval* check itself lives in
  :class:`ordessa_skills.library.revisions.RevisionApprovalStore` and is
  applied by the store through the injected :class:`RevisionGate`
  (assignment-time refusal, verification.md G06 「启用未批准版」).
* ``disable`` **requires** no revision — a pure tri-state exclusion.
* An asset that appears nowhere at a layer is *inherit*; that is an
  absence, never a row (G06 「inherit 被当 disable」 — the resolver carries
  inherit as "no entry", not as a disable row).
* Duplicate same-layer same-asset rows are refused: the layer identity is
  the tuple :attr:`SkillAssignment.layer_key`, and the store enforces it
  with a UNIQUE index on top of this validation.
* ``harnessId | any`` — ``None`` is the "所有 Harness" scope (FR04); a
  concrete string is brand-specific. The two are *different layers* of the
  six-layer order (user-global/any then user-global/harness …), which is
  what makes G05 「品牌通用范围被错判」 testable.

``operation_key`` is the client-supplied idempotency key stored with the
settled write (data-model: 写 CAS/操作键；重试不能重复升级); ``row_version``
is the monotonic per-row CAS version owned by the store.

Server-side scope: ``server_scope``/``principal`` are injected into the
store by the auth layer (api-requests.md §G5, FR09); this model never
derives them from a client path or owner string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from ..api.errors import AssetDomainError
from ..api.identity import ASSET_ID

#: The two assignment scope kinds this domain owns (FR04). The Profile layer
#: is NOT one of them: its storage stays in Profile's own contribution facet
#: (contracts.md §Profile / Workspace / Settings) and rides in as an
#: injected :class:`~ordessa_skills.assignments.ports.ProfileLayerPort`.
SCOPE_USER_GLOBAL = "user_global"
SCOPE_PROJECT = "project"
SCOPE_KINDS = (SCOPE_USER_GLOBAL, SCOPE_PROJECT)

#: The tri-state decisions stored as rows. `inherit` is deliberately absent:
#: it is the *absence* of a row at a layer (data-model: 未出现的项即 inherit).
DECISION_ENABLE = "enable"
DECISION_DISABLE = "disable"
DECISIONS = (DECISION_ENABLE, DECISION_DISABLE)

#: Sentinel for ``harness_id=None`` ("所有 Harness") inside stored keys.
ANY_HARNESS = "*"

#: The six resolution layers, in the one order FR06 pins. A seventh,
#: non-overridable layer sits on top of all of them (G06 管理员强制规则).
LAYER_USER_GLOBAL_ANY = "user_global_any"
LAYER_USER_GLOBAL_HARNESS = "user_global_harness"
LAYER_PROJECT_ANY = "project_any"
LAYER_PROJECT_HARNESS = "project_harness"
LAYER_PROFILE = "profile"
LAYER_SESSION_OVERRIDE = "session_override"
LAYER_ORDER = (
    LAYER_USER_GLOBAL_ANY,
    LAYER_USER_GLOBAL_HARNESS,
    LAYER_PROJECT_ANY,
    LAYER_PROJECT_HARNESS,
    LAYER_PROFILE,
    LAYER_SESSION_OVERRIDE,
)
LAYER_MANDATORY = "mandatory_policy"

#: Stable id regex for a principal/scope/project identifier: same bound as
#: asset ids; refuses path-shaped or oversized client input.
SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class AssignmentError(AssetDomainError):
    """One assignment/layer operation was refused (codes registered here,
    once: ``ASSIGNMENT_INVALID``, ``ASSIGNMENT_DUPLICATE``,
    ``ASSIGNMENT_NOT_FOUND``, ``ASSIGNMENT_VERSION_CONFLICT``,
    ``ASSIGNMENT_SCHEMA_UNAVAILABLE``, ``ASSIGNMENT_ASSET_UNKNOWN``,
    ``PROFILE_HARNESS_MISMATCH``, ``PROFILE_UNKNOWN``,
    ``WORKSPACE_UNKNOWN``, ``RESOLUTION_ASSET_UNKNOWN``,
    ``RESOLUTION_FOREIGN_CONTENT``, ``SESSION_OVERRIDE_INVALID``).
    """


@dataclass(frozen=True)
class SkillAssignment:
    """One durable assignment row (see module docstring for the rules)."""

    server_scope: str
    principal: str
    scope_kind: str
    scope_id: str
    harness_id: str | None      # None == any harness (FR04)
    asset_id: str
    decision: str               # enable | disable
    revision: int | None = None
    row_version: int = 0
    operation_key: str | None = None

    def __post_init__(self) -> None:
        if self.scope_kind not in SCOPE_KINDS:
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                f"unknown scope kind {self.scope_kind!r}")
        if self.decision not in DECISIONS:
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                f"unknown decision {self.decision!r}; inherit is the "
                "absence of a row, never a stored decision")
        if not self.server_scope or not self.principal:
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                "server_scope and principal are injected by the auth layer "
                    "and must be non-empty")
        if ASSET_ID.fullmatch(self.asset_id) is None:
            raise AssignmentError(
                "ASSIGNMENT_INVALID", "asset_id must be a lowercase slug",
                detail=self.asset_id)
        if self.scope_kind == SCOPE_PROJECT:
            if not self.scope_id or SCOPE_ID.fullmatch(self.scope_id) is None:
                raise AssignmentError(
                    "ASSIGNMENT_INVALID",
                    "a project assignment needs a bounded scope_id")
        elif self.scope_id not in ("", self.principal):
            # user-global is scoped by the principal column; a second owner
            # spelling in scope_id would let two names denote one layer.
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                "a user_global assignment's scope_id must be empty or the "
                "principal itself")
        if self.harness_id is not None:
            if not self.harness_id or SCOPE_ID.fullmatch(self.harness_id) is None:
                raise AssignmentError(
                    "ASSIGNMENT_INVALID", "harness_id must be a bounded token",
                    detail=str(self.harness_id))
        # 分配三态: enable 记录 revision；disable 不要求 revision.
        if self.decision == DECISION_ENABLE:
            if not isinstance(self.revision, int) or self.revision < 1:
                raise AssignmentError(
                    "ASSIGNMENT_INVALID",
                    "an enable assignment must record a revision "
                    "(已安装、校验并批准的 revision)")
        elif self.revision is not None:
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                "a disable assignment carries no revision")
        if self.row_version < 0:
            raise AssignmentError(
                "ASSIGNMENT_INVALID", "row_version must be >= 0")

    @property
    def layer_key(self) -> tuple:
        """The layer identity: two rows with the same key are duplicates
        (data-model: 重复同层同 assetId 拒绝)."""
        return (
            self.server_scope, self.principal, self.scope_kind,
            self._stored_scope_id(),
            self.harness_id if self.harness_id is not None else ANY_HARNESS,
            self.asset_id,
        )

    def _stored_scope_id(self) -> str:
        return "" if self.scope_kind == SCOPE_USER_GLOBAL else self.scope_id

    def with_version(self, row_version: int,
                     operation_key: str | None = None) -> "SkillAssignment":
        return replace(self, row_version=row_version,
                       operation_key=operation_key if operation_key is not None
                       else self.operation_key)

    def view(self) -> dict[str, Any]:
        """The camelCase wire view (contracts.md §Skills service spelling,
        aligned with :func:`ordessa_skills.library.records.asset_view`)."""
        return {
            "serverScope": self.server_scope,
            "principal": self.principal,
            "scopeKind": self.scope_kind,
            "scopeId": self.scope_id,
            "harnessId": self.harness_id,
            "assetId": self.asset_id,
            "decision": self.decision,
            "revision": self.revision,
            "rowVersion": self.row_version,
        }

    @classmethod
    def from_row(cls, row: Any) -> "SkillAssignment":
        harness = row["harness_key"]
        return cls(
            server_scope=row["server_scope"],
            principal=row["principal"],
            scope_kind=row["scope_kind"],
            scope_id=row["scope_id"],
            harness_id=None if harness == ANY_HARNESS else harness,
            asset_id=row["asset_id"],
            decision=row["decision"],
            revision=None if row["revision"] is None else int(row["revision"]),
            row_version=int(row["row_version"]),
            operation_key=row["operation_key"],
        )
