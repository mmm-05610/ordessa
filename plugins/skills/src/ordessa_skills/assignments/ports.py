"""Injected ports of the assignments domain (specs/011-q1-skills/api-requests.md
§G3/§G5 adjudication).

The Profile facet (`assets.skills`), the session item overrides and the
workspace-identity registry are cross-domain inputs this domain must not
own; the admin/mandatory policy layer now has a REAL supplier (see the
status note below). Requirement 1 of this slice therefore rules the shape of
every cross-domain input: it is a **typed protocol defined here**, supplied
by an injected implementation — the real Z1 profile-api, C0 workspace records
and Q5 permissions-api plug into these exact signatures in the integration
wave. This module must never import `ordessa_server_compat` or any host
internals to reach them (AGENTS.md rule 3).

Status note (permissions-api checkpoint, publication `bcd4387bec` / r3
`6ac8f54a14`): :class:`MandatoryPolicyPort` is supplied for real by
:mod:`ordessa_skills.mandatory_policy`, which reads the published
administrator `PolicyCeiling` surface through the provided port object the
composition injects. The port keeps its injected shape on purpose: what that
surface can and cannot express (no mandatory ENABLE, no project/harness/
revision dimension) is documented there, not hidden behind this protocol.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .model import DECISIONS

#: Who supplies each port once this slice leaves the test bench:
#:
#: * :class:`ProfileLayerPort`   — Z1 (profile-api, request G3)
#: * :class:`SessionOverride`    — Z1 (existing Profile session-item
#:   mechanism, request G3(b); contracts.md: 会话覆盖按 Profile 已有 item
#:   机制执行，不新建会话覆盖库)
#: * :class:`WorkspaceLookup`    — C0 (workspace records; request G5 独立
#:   路径: 「Q1 以 workspace.records.get() 存在性校验 + 本地 server_scope
#:   列实现」)
#: * :class:`MandatoryPolicyPort` — Q5 permissions-api, REAL since the
#:   checkpoint (`ordessa_skills.mandatory_policy`; verification.md G06
#:   管理员强制规则); the in-test fakes stay for the resolver seam only.
#: * :class:`RevisionGate`       — already real:
#:   :class:`ordessa_skills.library.revisions.RevisionApprovalStore`
#:   satisfies it structurally (``assert_usable_for_assignment``).


@runtime_checkable
class RevisionGate(Protocol):
    """The installed+approved check an `enable` assignment must pass.

    Satisfied today by :class:`...revisions.RevisionApprovalStore`; the
    resolver re-applies the same gate at read time so an approval that
    disappeared (or drifted) is a typed refusal, never a silent filter
    (contracts.md: 不可用不以静默过滤达成"成功").
    """

    def assert_usable_for_assignment(self, asset_id: str,
                                     revision: int) -> Any: ...


@runtime_checkable
class WorkspaceLookup(Protocol):
    """Server-side workspace identity (FR09, G07).

    ``get(workspace_id)`` returns the authorized workspace record (a
    Mapping-like object) or ``None`` when no such workspace exists in this
    data domain. A fabricated/unknown projectId must be refused with a
    typed error by the caller — never answered with a silent empty result
    (verification.md G07 「客户端伪 projectId」). The record is trusted only
    for identity checks; no path from it is ever opened by this domain.
    """

    def get(self, workspace_id: str) -> Mapping[str, Any] | None: ...


class ProfileSkillEntry(Mapping[str, Any]):
    """One Profile-facet item: ``inherit`` is the absence of the assetId."""

    def __init__(self, asset_id: str, decision: str,
                 revision: int | None = None) -> None:
        if decision not in DECISIONS and decision != "inherit":
            raise ValueError(f"unknown profile decision {decision!r}")
        self.asset_id = asset_id
        self.decision = decision
        self.revision = revision

    def __getitem__(self, key: str) -> Any:
        return {"assetId": self.asset_id, "decision": self.decision,
                "revision": self.revision}[key]

    def __iter__(self):
        return iter(("assetId", "decision", "revision"))

    def __len__(self) -> int:
        return 3


class ProfileLayerPort(Protocol):
    """The Profile facet `assets.skills` as a read-only resolution input.

    Supplied by Z1 (G3(a)/(c)). The harness a Profile belongs to is fixed
    (data-model: Profile 的 harnessId 固定), so the port must expose it and
    the resolver refuses a target whose harness differs
    (``PROFILE_HARNESS_MISMATCH``) instead of silently skipping the layer.
    ``revision_identity`` is the (profileId, configRevision,
    configObjectDigest) triple G3(c) requires inside the frozen snapshot.
    """

    def skill_entries(self, profile_id: str) -> Sequence[ProfileSkillEntry]:
        ...

    def harness_id(self, profile_id: str) -> str | None: ...

    def revision_identity(self, profile_id: str) -> Mapping[str, Any]: ...


class SessionOverride:
    """One per-commit session choice (layer 6).

    Read from the session's pending send-intent overrides by the caller
    (Z1 mechanism, G3(b)); a session override takes effect on the next
    commit only and is never written back to the Profile (data-model:
    会话临时选择下一次提交生效，不能永久回写 Profile).
    """

    __slots__ = ("asset_id", "decision", "revision")

    def __init__(self, asset_id: str, decision: str,
                 revision: int | None = None) -> None:
        if decision not in DECISIONS and decision != "inherit":
            raise ValueError(f"unknown session override {decision!r}")
        self.asset_id = asset_id
        self.decision = decision
        self.revision = revision


class MandatoryRule:
    """One admin/mandatory policy rule (the non-overridable layer).

    ``revision=None`` on an enable rule means "the policy pins no specific
    revision" — the resolver then keeps the revision the covered layers
    chose, or refuses if none was chosen; a policy enable with an explicit
    revision goes through the same :class:`RevisionGate`.
    """

    __slots__ = ("asset_id", "decision", "revision")

    def __init__(self, asset_id: str, decision: str,
                 revision: int | None = None) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"unknown mandatory decision {decision!r}")
        self.asset_id = asset_id
        self.decision = decision
        self.revision = revision


class MandatoryPolicyPort(Protocol):
    """Admin policy that the profile/session layers cannot override.

    Real supplier since the permissions-api checkpoint:
    :class:`ordessa_skills.mandatory_policy.PermissionsCeilingMandatoryPolicy
    Port` (the published administrator `PolicyCeiling`), with
    :class:`ordessa_skills.mandatory_policy.NotConfiguredMandatoryPolicyPort`
    as the typed "unreadable layer" default. The resolver consults this port
    AFTER the six user-overridable layers and its outcome is final
    (verification.md G06 counter-example 「管理员强制规则被覆盖」; data-model:
    若将来要组织/机器强制安装，须用单独管理政策层，不纳入这套可覆盖三态).

    The port deliberately accepts `enable` rules even though the published
    ceiling can only DENY (a `CeilingEntry` refuses an allow,
    ceilings.py:104-108): the enable half of the signature is the seam waiting
    for a real "force-install" authority, and nothing in this tree emits one.
    """

    def rules(self, *, principal: str, project_id: str | None,
              harness_id: str | None) -> Sequence[MandatoryRule]: ...
