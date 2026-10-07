"""T06 permission glue: the fail-closed double gate before any tool side effect.

This module is the MCP side's *consumer port* for the Permission domain
(``docs/design/mcp/contracts.md`` §4, FR-09, verification counterexample 6).
It decides "callable now?" from two independent gates and nothing else:

* **gate 1 - catalog subset** (:func:`check_tool_callable`): the tool must be
  in the effective snapshot's frozen ``allowed_tool_names`` (the
  ``backend/resolve.py`` field). Passing gate 1 never means "callable"; it
  only means the candidate set did not reject first, and a gate-1 refusal
  must not even consult the authority (no side effects, no audit noise);
* **gate 2 - final authority**: :class:`PermissionAuthority`
  (``authorize_tool_call(principal, sessionRef, leaseId, toolName,
  argsDigest, policyRevision)``) decides. The Q5 permissions-api lands as
  ``codex/011-permissions-api-ready``; until that checkpoint is consumed,
  production wiring is *absent* and absence is a typed refusal, never a
  default allow (FR-09: "未接上该权威时…不能声称跨品牌新策略已生效").

Fail-closed rules implemented here:

* ``authority is None`` (not injected) -> ``PERMISSION_AUTHORITY_ABSENT``
  unless an exactly-bound :class:`BoundedPreAuthorization` re-verifies live
  at call time (contracts §4 unattended clause: 无人值守不等于默认批准 -
  only a prior grant precisely bound to principal, definition revision,
  tool, args constraint, project, session/time window, side-effect levels
  and audit policy may continue without interactive approval);
* a preauthorization that is expired, crossed to another principal or
  project, bound to a changed revision/schema digest, bound to different
  args, or faced with an unknown/out-of-bound side-effect level does **not**
  cover the call; with no covering grant the call is refused (or stays
  ``pending-approval`` when the authority itself says so) - never allowed;
* server-self-reported tool ``annotations`` (``readOnlyHint`` etc.) are
  untrusted (contracts §4 links the MCP spec) and are **never an input to
  any allow path** - they are accepted here only so callers can pass their
  whole catalog record, and are deliberately not read for a decision;
* a native-lane entry whose per-call enforcement is ``unproven`` in the
  snapshot is refused with ``PERMISSION_ENFORCEMENT_UNPROVEN`` before the
  authority is consulted (contracts §4: 用 UI 隐藏代替 is not acceptable).

Audit: every decision carries a ``decision_id``; audit events must reference
that id, never the secret-bearing args (the full arguments never reach this
module at all - only ``args_digest``).

Display fact (T012, FR-09 / contracts §4 second half): while this authority
is absent, native-lane entries run under the harness-native permission
mechanism, and :class:`NativePermissionPosture` is the honest labelling
surface for *which* mechanism/policy that is (observation or declaration,
scope, policy id, provenance). It is a display fact source only - it never
authorises anything, never lifts the ``enforcement: "unproven"`` downgrade,
and never claims a unified cross-brand Ordessa policy.

Since T014 all codes live in the closed vocabulary of ``backend/errors.py``
and this module re-exports its family: ``PERMISSION_AUTHORITY_ABSENT``,
``PERMISSION_ENFORCEMENT_UNPROVEN``, ``PERMISSION_ARGS_DIGEST_REQUIRED``.
``PERMISSION_REFUSED`` is the FR-10 vocabulary code and stays the default
refusal code.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Mapping, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .errors import (
    PERMISSION_ARGS_DIGEST_REQUIRED,
    PERMISSION_AUTHORITY_ABSENT,
    PERMISSION_ENFORCEMENT_UNPROVEN,
    PERMISSION_REFUSED,
    McpError,
)

# T014 converge: the three gate codes are registered in backend/errors.py
# (this module keeps re-exporting them for its consumers);
# PERMISSION_ENFORCEMENT_UNPROVEN is contracts §4 "permission-enforcement-
# unproven". PERMISSION_REFUSED is the FR-10 vocabulary code and stays the
# default refusal code.

STATUS_ALLOWED = "allowed"
STATUS_REFUSED = "refused"
STATUS_PENDING_APPROVAL = "pending-approval"

GATE_CATALOG = "catalog-subset"
GATE_AUTHORITY = "authority"
GATE_PREAUTHORIZATION = "preauthorization"
GATE_ENFORCEMENT = "enforcement"

_BASIS_AUTHORITY = "authority"
_BASIS_PREAUTH = "preauthorized"


@dataclass(frozen=True)
class ToolCallDecision:
    """Typed allowed/refused/pending outcome of one authorization decision.

    Refusals carry ``code`` (an ``{CODE}: {message}`` McpError shape via
    :meth:`as_error`), a human ``reason``, the gate that spoke, the
    authority's ``policy_revision``, a pass-through ``expires_at`` when the
    grant or refusal is time-bounded, and - when bounded preauthorizations
    were offered but did not cover the call - the per-grant miss reasons.
    """

    status: str
    reason: str
    gate: Optional[str] = None
    code: Optional[str] = None
    decision_id: str = field(default_factory=lambda: f"decision_{uuid.uuid4().hex}")
    policy_revision: Optional[str] = None
    expires_at: Optional[float] = None
    preauth_id: Optional[str] = None
    basis: Optional[str] = None
    preauth_misses: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in (STATUS_ALLOWED, STATUS_REFUSED, STATUS_PENDING_APPROVAL):
            raise ValueError(f"unknown decision status {self.status!r}")
        if self.status == STATUS_ALLOWED and self.basis not in (_BASIS_AUTHORITY, _BASIS_PREAUTH):
            raise ValueError("an allowed decision needs basis 'authority' or 'preauthorized'")
        if self.status != STATUS_ALLOWED and self.code is None:
            raise ValueError("a refusal must carry a typed code")

    @classmethod
    def allowed(cls, *, basis: str, gate: str, policy_revision: Optional[str] = None,
                preauth_id: Optional[str] = None,
                expires_at: Optional[float] = None) -> "ToolCallDecision":
        return cls(status=STATUS_ALLOWED, reason="authorized before side effects",
                   gate=gate, policy_revision=policy_revision, preauth_id=preauth_id,
                   basis=basis, expires_at=expires_at)

    @classmethod
    def refused(cls, *, code: str, reason: str, gate: str,
                policy_revision: Optional[str] = None,
                expires_at: Optional[float] = None,
                preauth_misses: Tuple[Tuple[str, str], ...] = ()) -> "ToolCallDecision":
        return cls(status=STATUS_REFUSED, reason=reason, gate=gate, code=code,
                   policy_revision=policy_revision, expires_at=expires_at,
                   preauth_misses=preauth_misses)

    @classmethod
    def pending(cls, *, reason: str, gate: str, code: str = PERMISSION_REFUSED,
                policy_revision: Optional[str] = None,
                expires_at: Optional[float] = None) -> "ToolCallDecision":
        return cls(status=STATUS_PENDING_APPROVAL, reason=reason, gate=gate, code=code,
                   policy_revision=policy_revision, expires_at=expires_at)

    def as_error(self) -> McpError:
        """The ``{CODE}: {message}`` refusal for callers that raise before
        forwarding ``tools/call``. Never callable on an allowed decision."""
        if self.status == STATUS_ALLOWED:
            raise ValueError("an allowed decision has no refusal error")
        return McpError(self.code or PERMISSION_REFUSED, f"{self.gate}: {self.reason}")


@runtime_checkable
class PermissionAuthority(Protocol):
    """Consumer port for the Permission domain service (contracts §4).

    Production wiring waits for the ``codex/011-permissions-api-ready``
    checkpoint (gap G3, ``specs/011-q4-mcp/api-requests.md``); this batch
    tests only against fakes. Implementations must decide from
    ``principal``/``session_ref``/``lease_id``/``tool_name``/``args_digest``/
    ``policy_revision`` and return a :class:`ToolCallDecision`; the full
    call arguments never cross this seam.
    """

    def authorize_tool_call(self, *, principal: Optional[str], session_ref: Optional[str],
                            lease_id: Optional[str], tool_name: str, args_digest: str,
                            policy_revision: Optional[str]) -> ToolCallDecision: ...


@dataclass(frozen=True)
class BoundedPreAuthorization:
    """A prior, precisely-bounded unattended grant (contracts §4).

    Every field is part of the binding and is re-verified at call time:
    principal, definition id/revision (and, when given, the canonical
    digest - a schema/digest change revokes), tool name, the argument
    constraint digest (or an explicit ``allow_any_args`` declaration),
    project id, optional session ref, the validity time window
    (``expires_at`` is mandatory - there is no open-ended grant), the
    allowed side-effect levels, and a non-empty audit policy ref. An
    annotation-suggested "read only" level is never a substitute: the
    levels here are what the Permission domain approved.
    """

    preauth_id: str
    principal: str
    definition_id: str
    definition_revision: int
    tool_name: str
    project_id: str
    expires_at: float
    allowed_side_effect_levels: FrozenSet[str]
    audit_policy: str
    definition_digest: Optional[str] = None
    args_digest: Optional[str] = None
    args_constraint_digest: Optional[str] = None
    allow_any_args: bool = False
    session_ref: Optional[str] = None
    not_before: Optional[float] = None
    policy_revision: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("preauth_id", "principal", "definition_id", "tool_name", "project_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"a bounded preauthorization needs a non-empty {name}")
        if not isinstance(self.definition_revision, int) or self.definition_revision < 1:
            raise ValueError("definition_revision must be a positive int")
        if not isinstance(self.expires_at, (int, float)):
            raise ValueError("a bounded preauthorization needs a numeric expires_at")
        if self.not_before is not None and self.expires_at <= self.not_before:
            raise ValueError("expires_at must be after not_before")
        if (not isinstance(self.allowed_side_effect_levels, frozenset)
                or not self.allowed_side_effect_levels
                or any(not isinstance(v, str) or not v
                       for v in self.allowed_side_effect_levels)):
            raise ValueError("allowed_side_effect_levels must be a non-empty frozenset of strings")
        if not isinstance(self.audit_policy, str) or not self.audit_policy:
            raise ValueError("a bounded preauthorization needs a non-empty audit_policy")
        if (self.args_digest is None and self.args_constraint_digest is None
                and not self.allow_any_args):
            raise ValueError(
                "the argument constraint must be bound (args_digest / args_constraint_digest) "
                "or explicitly declared as allow_any_args")

    # -- call-time re-verification --------------------------------------------

    def miss_reason(self, *, principal: Optional[str], project_id: Optional[str],
                    session_ref: Optional[str], now: float, tool_name: str,
                    args_digest: Optional[str], side_effect_level: Optional[str],
                    definition_id: Optional[str],
                    bound_entry: Optional[Mapping[str, Any]]) -> Optional[str]:
        """``None`` when this grant covers the call; else why it does not.

        ``bound_entry`` is the snapshot ``definition_revisions`` entry for
        the called definition (``revision`` / ``canonical_digest`` fields)
        when the caller supplied a ``definition_id``.
        """
        if principal is None or principal != self.principal:
            return "cross-principal (no default approval across subjects)"
        if project_id is None or project_id != self.project_id:
            return "cross-project (grant is project-bound)"
        if session_ref is not None and self.session_ref is not None and session_ref != self.session_ref:
            return "cross-session (grant is session-bound)"
        if definition_id is None:
            # every grant is definition-bound; a call that does not name its
            # definition cannot have that binding re-verified -> no coverage
            return "call does not attribute a definition id"
        if definition_id != self.definition_id:
            return "cross-definition (grant names another definition)"
        if tool_name != self.tool_name:
            return "tool name is outside the bound grant"
        if side_effect_level is None:
            return "unknown side-effect level (an unclassified call is never pre-approved)"
        if side_effect_level not in self.allowed_side_effect_levels:
            return "side-effect level outside the bound set"
        if self.not_before is not None and now < self.not_before:
            return "grant not yet valid"
        if now > self.expires_at:
            return "grant expired"
        if (self.args_digest is not None and args_digest is not None
                and args_digest != self.args_digest):
            return "args digest differs from the bound digest"
        if (self.args_constraint_digest is not None and args_digest is not None
                and not args_digest.startswith(self.args_constraint_digest)):
            return "args digest differs from the bound constraint"
        if bound_entry is not None:
            if int(bound_entry.get("revision", -1)) != self.definition_revision:
                return "definition revision changed since the grant (schema revalidation needed)"
            digest = bound_entry.get("canonical_digest")
            if self.definition_digest is not None and digest != self.definition_digest:
                return "definition canonical digest changed since the grant (schema revalidation needed)"
        return None


def _snapshot_field(snapshot: Any, name: str, camel: str, default: Any) -> Any:
    if isinstance(snapshot, Mapping):
        return snapshot.get(name, snapshot.get(camel, default))
    return getattr(snapshot, name, default)


def _definition_entry(snapshot: Any, definition_id: Optional[str]) -> Optional[Mapping[str, Any]]:
    if definition_id is None:
        return None
    entries = _snapshot_field(snapshot, "definition_revisions", "definitionRevisions", ()) or ()
    for entry in entries:
        entry_id = entry.get("definition_id", entry.get("definitionId")) if isinstance(entry, Mapping) \
            else getattr(entry, "definition_id", None)
        if entry_id == definition_id:
            return entry if isinstance(entry, Mapping) else {
                "revision": getattr(entry, "revision", None),
                "canonical_digest": getattr(entry, "canonical_digest", None),
            }
    return {}  # known-definitely absent: distinct from "caller gave no definition_id"


def check_tool_callable(
    snapshot: Any,
    authority: Optional[PermissionAuthority],
    tool_name: str,
    args_digest: Optional[str],
    now: float,
    *,
    principal: Optional[str] = None,
    session_ref: Optional[str] = None,
    lease_id: Optional[str] = None,
    project_id: Optional[str] = None,
    definition_id: Optional[str] = None,
    policy_revision: Optional[str] = None,
    side_effect_level: Optional[str] = None,
    annotations: Optional[Mapping[str, Any]] = None,
    preauthorizations: Sequence[BoundedPreAuthorization] = (),
) -> ToolCallDecision:
    """The double gate every ``tools/call`` forward must pass, before any
    side effect. Returns a structured decision; raises nothing for refusals
    (use :meth:`ToolCallDecision.as_error` to raise at the call site).

    ``snapshot`` is a ``backend.resolve.McpEffectiveSnapshot`` (or the same
    fields as a mapping). Gate order is load-bearing: the catalog gate
    refuses first and the authority is then never consulted. ``annotations``
    is accepted for caller convenience and **never read for a decision** -
    server self-reported hints (``readOnlyHint`` and friends) are untrusted
    (contracts §4). ``now`` is epoch seconds; time windows of bounded
    preauthorizations are checked against it at call time, not at plan time.
    """
    del annotations  # untrusted by design (contracts §4 / FR 非目标): never an allow input
    if not isinstance(tool_name, str) or not tool_name:
        return ToolCallDecision.refused(
            code=PERMISSION_REFUSED, reason="a tool call names a tool", gate=GATE_CATALOG)
    if not isinstance(args_digest, str) or not args_digest:
        # the digest is what the authority and the grants bind; an
        # unattributed call can never be authorised.
        return ToolCallDecision.refused(
            code=PERMISSION_ARGS_DIGEST_REQUIRED,
            reason="args_digest is required before any decision", gate=GATE_CATALOG)

    # -- gate 1: frozen catalog subset ----------------------------------------
    allowed_names = _snapshot_field(snapshot, "allowed_tool_names", "allowedToolNames", ()) or ()
    if tool_name not in set(allowed_names):
        return ToolCallDecision.refused(
            code=PERMISSION_REFUSED,
            reason=(f"{tool_name!r} is outside the snapshot's frozen tool subset; "
                    "the catalog gate refuses before the authority is consulted"),
            gate=GATE_CATALOG, policy_revision=policy_revision)

    # -- native-lane enforcement proof (contracts §4) --------------------------
    if definition_id is not None:
        lanes = _snapshot_field(snapshot, "lane_by_definition", "laneByDefinition", {}) or {}
        lane_info = lanes.get(definition_id) if isinstance(lanes, Mapping) else None
        enforcement = lane_info.get("enforcement") if isinstance(lane_info, Mapping) else None
        if enforcement == "unproven":
            return ToolCallDecision.refused(
                code=PERMISSION_ENFORCEMENT_UNPROVEN,
                reason=(f"native lane of {definition_id!r} cannot prove per-call enforcement; "
                        "refusing to run instead of hiding the tool behind UI"),
                gate=GATE_ENFORCEMENT, policy_revision=policy_revision)

    # -- gate 2: final authority / bounded preauthorization --------------------
    if authority is not None:
        try:
            decision = authority.authorize_tool_call(
                principal=principal, session_ref=session_ref, lease_id=lease_id,
                tool_name=tool_name, args_digest=args_digest, policy_revision=policy_revision)
        except Exception as exc:  # fail closed: a broken authority is a refusal, never an allow
            return ToolCallDecision.refused(
                code=PERMISSION_REFUSED,
                reason=f"authority raised {type(exc).__name__}: refused before side effects",
                gate=GATE_AUTHORITY, policy_revision=policy_revision)
        if not isinstance(decision, ToolCallDecision):
            return ToolCallDecision.refused(
                code=PERMISSION_REFUSED, reason="authority returned a non-decision",
                gate=GATE_AUTHORITY, policy_revision=policy_revision)
        if decision.status == STATUS_ALLOWED:
            return ToolCallDecision.allowed(
                basis=_BASIS_AUTHORITY, gate=GATE_AUTHORITY,
                policy_revision=decision.policy_revision or policy_revision,
                expires_at=decision.expires_at)
        if decision.status == STATUS_PENDING_APPROVAL:
            # approval pending is not approval: the call still stops here.
            return ToolCallDecision.pending(
                reason=decision.reason, gate=GATE_AUTHORITY,
                code=decision.code or PERMISSION_REFUSED,
                policy_revision=policy_revision, expires_at=decision.expires_at)
        # refused - the authority's own words, never widened
        return ToolCallDecision.refused(
            code=decision.code or PERMISSION_REFUSED, reason=decision.reason,
            gate=GATE_AUTHORITY, policy_revision=policy_revision,
            expires_at=decision.expires_at)

    # No authority injected (production today: G3 open until
    # codex/011-permissions-api-ready). Only an exact, live re-verified
    # bounded preauthorization may continue; anything else fails closed.
    misses = []
    entry = _definition_entry(snapshot, definition_id)
    if definition_id is not None and not entry:
        # the called definition is not in this snapshot: no grant bound to
        # it can be re-verified against frozen revisions/digests -> no cover
        for grant in preauthorizations:
            if grant.tool_name == tool_name:
                misses.append((grant.preauth_id,
                               "definition is absent from the snapshot (nothing to re-verify)"))
    for grant in preauthorizations:
        miss = grant.miss_reason(
            principal=principal, project_id=project_id, session_ref=session_ref, now=now,
            tool_name=tool_name, args_digest=args_digest,
            side_effect_level=side_effect_level,
            definition_id=definition_id, bound_entry=entry)
        if miss is None:
            return ToolCallDecision.allowed(
                basis=_BASIS_PREAUTH, gate=GATE_PREAUTHORIZATION,
                policy_revision=grant.policy_revision or policy_revision,
                preauth_id=grant.preauth_id, expires_at=grant.expires_at)
        misses.append((grant.preauth_id, miss))
    return ToolCallDecision.refused(
        code=PERMISSION_AUTHORITY_ABSENT,
        reason=("no Permission authority is wired (G3) and no bounded preauthorization "
                "covers this call; unattended is not implicit consent - refusing "
                "before any side effect (no UI, no default allow)"),
        gate=GATE_AUTHORITY, policy_revision=policy_revision,
        preauth_misses=tuple(misses))


# -- T012: native permission posture (FR-09 / contracts §4 second half) ----------
#
# While the Ordessa Permission authority is absent (G3 open), a native-lane
# entry runs under the harness-native permission mechanism, and the product
# must SHOW that mechanism honestly instead of pretending a cross-brand
# policy is in force. The posture is the display fact source: where the
# governance comes from (a harness-native *observation* or *declaration*),
# which scope it covers, its policy identifier, and how the domain learned
# it (provenance). It is deliberately not a decision type: no gate reads it,
# it carries no allow/status vocabulary, and it never upgrades a snapshot's
# ``enforcement`` - an unproven lane stays unproven next to its posture.

#: the mechanism was read from the harness runtime (C3 observation plane)
POSTURE_PROVENANCE_NATIVE_OBSERVED = "native-observed"
#: the mechanism/policy is what the brand adapter declares (T04 brand facts)
POSTURE_PROVENANCE_NATIVE_DECLARED = "native-declared"
#: neither an observation nor a declaration was injected: the honest default
#: while the authority is absent - governed by the harness-native mechanism,
#: mechanism and policy id NOT known (never fabricated)
POSTURE_PROVENANCE_UNATTRIBUTED = "unattributed"
POSTURE_PROVENANCES: FrozenSet[str] = frozenset({
    POSTURE_PROVENANCE_NATIVE_OBSERVED,
    POSTURE_PROVENANCE_NATIVE_DECLARED,
    POSTURE_PROVENANCE_UNATTRIBUTED,
})

#: source words for the unattributed default (contracts §4: 显示其实际策略 -
#: when the actual strategy is unknowable, the truthful display is "unknown")
POSTURE_UNKNOWN_MECHANISM = "harness-native"
POSTURE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class NativePermissionPosture:
    """One native-lane entry's honest permission posture (display fact).

    ``source`` names the harness-native mechanism that actually governs the
    entry (observation- or declaration-grade), ``scope`` where it governs
    (e.g. instance / session), ``policy_ref`` is the mechanism's own policy
    identifier (name or revision as the harness reports it), ``provenance``
    says how the domain learned all of this - see POSTURE_PROVENANCES.
    A posture never authorises: it carries no decision fields, and this
    module's gates never read it (FR-09 counterexample).
    """

    definition_id: str
    source: str
    scope: str
    policy_ref: str
    provenance: str

    def __post_init__(self) -> None:
        for name in ("definition_id", "source", "scope", "policy_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"a posture needs a non-empty {name}")
        if self.provenance not in POSTURE_PROVENANCES:
            raise ValueError(
                f"unknown posture provenance {self.provenance!r}; the "
                "vocabulary is closed (native-observed / native-declared / "
                "unattributed)")


def native_permission_posture(definition_id: str,
                              fact: Optional[Mapping[str, Any]] = None) -> NativePermissionPosture:
    """One entry's posture from one injected native fact record.

    ``fact`` is a caller/harness-supplied mapping (``source``/``scope``/
    ``policyRef``/``provenance``); absence is the honest unattributed
    default - the mechanism stays "harness-native" and the policy id stays
    "unknown", never a guess. Declarations are taken at their word for the
    display and are NOT enforcement proof (a declared posture coexists with
    ``enforcement: "unproven"``; proving enforcement is
    ``resolve_preview(native_enforcement_proven=...)``, whose input this
    function never feeds).
    """
    if fact is None:
        return NativePermissionPosture(
            definition_id=definition_id, source=POSTURE_UNKNOWN_MECHANISM,
            scope=POSTURE_UNKNOWN, policy_ref=POSTURE_UNKNOWN,
            provenance=POSTURE_PROVENANCE_UNATTRIBUTED)
    provenance = fact.get("provenance", POSTURE_PROVENANCE_NATIVE_DECLARED)
    if provenance not in POSTURE_PROVENANCES \
            or provenance == POSTURE_PROVENANCE_UNATTRIBUTED:
        # "unattributed" is the domain's own default word; an injected fact
        # must say observed or declared (an attributed claim is never absent)
        raise ValueError(f"posture facts cannot be unattributed: {provenance!r}")
    def required(key: str, default: str) -> str:
        value = fact.get(key, default)
        if not isinstance(value, str) or not value:
            raise ValueError(f"a posture fact needs a non-empty {key}")
        return value
    return NativePermissionPosture(
        definition_id=definition_id,
        source=required("source", POSTURE_UNKNOWN_MECHANISM),
        scope=required("scope", POSTURE_UNKNOWN),
        policy_ref=required("policyRef", POSTURE_UNKNOWN),
        provenance=provenance)


def native_permission_postures(
    snapshot: Any,
    facts_by_definition: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Tuple[NativePermissionPosture, ...]:
    """One posture per NATIVE-lane entry of one resolve snapshot.

    Managed-lane entries never get a posture (their calls run through this
    module's gates; a posture would mislabel them as native-governed). With
    no facts injected every native entry is labelled ``unattributed`` - the
    truthful sentence under an absent authority, not a fabricated policy.
    """
    lanes = _snapshot_field(snapshot, "lane_by_definition", "laneByDefinition", {}) or {}
    facts = facts_by_definition or {}
    postures = []
    for definition_id in sorted(lanes):
        info = lanes.get(definition_id)
        lane = info.get("lane") if isinstance(info, Mapping) else None
        if lane != "native":
            continue
        fact = facts.get(definition_id)
        if fact is not None and not isinstance(fact, Mapping):
            raise ValueError(f"posture facts for {definition_id!r} must be a mapping")
        postures.append(native_permission_posture(definition_id, fact))
    return tuple(postures)


def posture_view(posture: NativePermissionPosture) -> dict:
    """The camelCase display row for one posture (the T08-r2 presentation
    consumes it; the UI is out of this batch's scope).

    ``claimsOrdessaAuthority`` is the FR-09 honesty bit pinned to False by
    construction: the row states what the harness-native mechanism does,
    and can never be read as "the Ordessa cross-brand policy governs here".
    """
    return {
        "definitionId": posture.definition_id,
        "source": posture.source,
        "scope": posture.scope,
        "policyRef": posture.policy_ref,
        "provenance": posture.provenance,
        "claimsOrdessaAuthority": False,
    }
