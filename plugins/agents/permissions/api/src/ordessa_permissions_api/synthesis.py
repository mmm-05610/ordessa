"""Adjudication synthesis: the five rules, in the order that makes them hold.

The whole point of this module is that no input can move *up*. The order is the
argument:

1. attribute first - an unknown tool, a missing trusted field or a revision pin
   that no longer matches is a refusal, never an inherited default;
2. the ceiling is applied and is non-widenable - a hard denial is final, an
   approval requirement is never relaxed into an allow, and several ceilings
   intersect (never "last one wins");
3. the intent then selects *within* that bound, and no intent is not `allow`:
   an unmatched (tool, target) asks;
4. among equal-priority intent rules the strictest wins (deny > ask > allow);
   an exception that overrides a stricter rule needs a verifiable
   `AdminAuthorization` bound to this exact operation, and a generic wildcard
   never qualifies;
5. the approval token binds to the same operation digest, target, policy
   revision and native generation; a mismatch refuses instead of re-binding,
   and nothing is called "granted" before the native owner confirmed it.

The result carries the effective snapshot it was computed under, so a consumer
can re-verify rather than re-decide.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Final, Sequence

from .ceilings import (
    EffectiveCeiling,
    PolicyCeiling,
    TOOL_EXPOSURE,
    intersect_ceilings,
)
from .codes import PolicyDenyCode, PolicyRefusal, RefusalCode
from .decisions import (
    GRANT_TTL,
    AllowedOnce,
    ApprovalDecision,
    ApprovalStateKind,
    AuthorizationDecision,
    BoundGrant,
    DecisionReason,
    Denied,
    PendingApproval,
    approval_id_for,
)
from .intents import NO_INTENT_REVISION, PermissionIntent
from .request_facts import ExecutionState, OperationRequest
from .rules import TOOL_KEYS, RuleAction, TypedRule
from .snapshots import EffectivePolicySnapshot

__all__ = [
    "DECISION_TTL",
    "PolicyRefused",
    "PolicySynthesized",
    "SynthesisResult",
    "evaluate_authorization",
    "select_intent_action",
    "synthesize",
]

DECISION_TTL: Final[dt.timedelta] = dt.timedelta(minutes=5)


class SynthesisResult:
    """Either the policy spoke about this operation, or it refused it."""

    action: RuleAction | None = None
    decision: AuthorizationDecision | None = None
    snapshot: EffectivePolicySnapshot | None = None
    denied: Denied | None = None

    @property
    def outcome(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class PolicySynthesized(SynthesisResult):
    """A ruling: `allow`, `ask` or `deny`, with its binding snapshot."""

    def __init__(self, *, action: RuleAction, decision: AuthorizationDecision,
                 snapshot: EffectivePolicySnapshot) -> None:
        self.action = action
        self.decision = decision
        self.snapshot = snapshot

    @property
    def outcome(self) -> str:
        return "synthesized"


class PolicyRefused(SynthesisResult):
    """No ruling was possible; `denied.code` says why, and nothing ran."""

    def __init__(self, *, denied: Denied) -> None:
        self.denied = denied

    @property
    def outcome(self) -> str:
        return "refused"


def select_intent_action(rules: Sequence[TypedRule], *, tool: str,
                         target: str | None) -> tuple[RuleAction | None, TypedRule | None]:
    """The intent's own answer for one (tool, target): strictest at top priority.

    Order is deliberately irrelevant - a rule later in the list cannot reverse
    one before it, which is exactly what the legacy resolver did.
    """
    matched = [rule for rule in rules if rule.matches_tool(tool) and rule.matches(target)]
    if not matched:
        return None, None
    top = max(rule.priority for rule in matched)
    leaders = [rule for rule in matched if rule.priority == top]
    winner = max(leaders, key=lambda rule: rule.action.strictness)
    return winner.action, winner


def synthesize(*, ceilings: Sequence[PolicyCeiling], intent: PermissionIntent | None,
               request: OperationRequest, now: dt.datetime) -> SynthesisResult:
    """Rule 1: trust. Rule 2: the ceiling. Rules 3-4: the intent within it."""
    if not isinstance(request, OperationRequest):
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source="synthesis.synthesize",
                            target=None if request is None else type(request).__name__)
    _require_moment(now, source="synthesis.synthesize")

    items = _ceiling_sequence(ceilings)
    if not items:
        return _refused(RefusalCode.POLICY_ADAPTER_MISSING, source="authorizer",
                        target=f"{request.tool_key} {request.session_id}")
    effective = intersect_ceilings(items)
    if not effective.is_trusted:
        return _refused(RefusalCode.POLICY_SCOPE_UNVERIFIED, source=f"ceiling {effective.revision_digest}",
                        target=request.tool_key)
    if request.tool_key not in TOOL_KEYS:
        return _refused(RefusalCode.PERMISSION_UNKNOWN_TOOL, source="permission vocabulary",
                        target=request.tool_key)
    if request.ceiling_revision != effective.revision_digest:
        # The caller decided under a different upper bound than the one in force.
        return _refused(RefusalCode.POLICY_CEILING_VIOLATION,
                        source=f"pinned ceiling {request.ceiling_revision}",
                        target=f"in force: {effective.revision_digest}")
    expected_policy = (NO_INTENT_REVISION if intent is None else intent.revision_digest)
    if request.policy_revision != expected_policy:
        return _refused(RefusalCode.POLICY_CEILING_VIOLATION,
                        source=f"pinned intent {request.policy_revision}",
                        target=f"in force: {expected_policy}")

    tool, target = request.tool_key, request.target
    if effective.blocks(tool, target):
        return _synthesized(RuleAction.DENY, request=request, now=now, effective=effective,
                            code=RefusalCode.POLICY_CEILING_VIOLATION,
                            message="the administrator ceiling denies this operation")

    action, winner = select_intent_action(() if intent is None else intent.rules,
                                          tool=tool, target=target)
    if action is None:
        # Rule 3: no intent, and no matching rule, is never an allow.
        return _synthesized(RuleAction.ASK, request=request, now=now, effective=effective,
                            code=None,
                            message="no intent rule covers this operation, so it needs approval")
    if winner is not None and winner.authorization is not None:
        authority = winner.authorization
        if not authority.covers(tool=tool, target=target,
                               ceiling_revision=effective.revision_digest, now=now):
            return _refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                            source=f"admin authorization by {authority.issuer}",
                            target=f"{tool} {authority.target}")
    if action is RuleAction.ALLOW:
        implied = TOOL_EXPOSURE[tool]
        if implied.rank > effective.maximum_exposure.rank:
            return _synthesized(
                RuleAction.DENY, request=request, now=now, effective=effective,
                code=RefusalCode.POLICY_CEILING_VIOLATION,
                message=f"the ceiling bounds this Harness to {effective.maximum_exposure.value}"
                        f" exposure and {tool} reaches {implied.value}")
        if effective.requires_approval(tool, target):
            return _synthesized(
                RuleAction.ASK, request=request, now=now, effective=effective, code=None,
                message="the ceiling requires approval for this operation, so an intent"
                        " allow cannot stand in for it")
    code: RefusalCode | PolicyDenyCode | None
    if action is RuleAction.DENY:
        code = PolicyDenyCode.POLICY_DENY
        message = "the effective policy denies this operation"
    elif action is RuleAction.ASK:
        code = None
        message = "the intent asks for approval on this operation"
    else:
        code = None
        message = "the intent allows this operation within the ceiling in force"
    return _synthesized(action, request=request, now=now, effective=effective, code=code,
                        message=message)


def evaluate_authorization(*, ceilings: Sequence[PolicyCeiling],
                           intent: PermissionIntent | None, request: OperationRequest,
                           now: dt.datetime, grant: BoundGrant | None = None,
                           approval: Any = None, receipt: Any = None,
                           execution_state: Any = None,
                           snapshot: EffectivePolicySnapshot | None = None) -> Any:
    """The §C1 `evaluate(...)` shape, as a pure function over the same model.

    One ruling per call, and no path where an unresolved fact becomes a `yes`.
    """
    _require_moment(now, source="synthesis.evaluate_authorization")
    if execution_state is not None:
        state = ExecutionState.of(execution_state)
        if not state.outcome_is_resolved:
            return _denied(RefusalCode.APPROVAL_RESULT_UNKNOWN, request,
                           "the execution outcome could not be resolved")
        if not state.actionable:
            return _denied(RefusalCode.APPROVAL_NOT_ACTIONABLE, request,
                           f"the execution is already {state.value}")
    if snapshot is not None:
        if not snapshot.valid_at(now):
            return _denied(RefusalCode.APPROVAL_STALE, request,
                           "the policy snapshot expired")
        if not snapshot.covers(server_instance_id=request.server_instance_id,
                               session_id=request.session_id,
                               native_session_id=request.native_session_id,
                               runtime_generation=request.native_generation,
                               principal=request.principal,
                               ceiling_revision=request.ceiling_revision,
                               intent_revision=request.policy_revision):
            return _denied(RefusalCode.APPROVAL_STALE, request,
                           "the policy snapshot belongs to another runtime identity")

    result = synthesize(ceilings=ceilings, intent=intent, request=request, now=now)
    if isinstance(result, PolicyRefused):
        assert result.denied is not None
        return result.denied
    assert result.decision is not None and result.action is not None
    if result.action is RuleAction.DENY:
        code = result.decision.reason.code
        assert code is not None
        return _denied(code, request, result.decision.reason.message)
    if result.action is RuleAction.ALLOW:
        issued = BoundGrant.of(approval_id=approval_id_for(
            operation_digest=request.operation_digest,
            native_request_id=request.native_request_id), request=request,
            expires_at=now + GRANT_TTL)
        return AllowedOnce(issued)

    # The decision is `ask`: only an approval of *this* operation can answer it.
    if grant is None:
        return PendingApproval(approval_id=approval_id_for(
            operation_digest=request.operation_digest,
            native_request_id=request.native_request_id))
    if approval is None:
        # A token with no recorded approval is not a decision anyone can vouch for.
        return _denied(RefusalCode.APPROVAL_RESULT_UNKNOWN, request,
                       "no approval record corroborates this grant")
    if approval.state is ApprovalStateKind.INVALID:
        return _denied(RefusalCode.APPROVAL_NOT_ACTIONABLE, request,
                       "the approval was invalidated before it could be used")
    if (approval.state is ApprovalStateKind.SETTLED
            and approval.decision is ApprovalDecision.DENY):
        # A recorded denial is final: a token cannot outvote the user's own no.
        return _denied(PolicyDenyCode.POLICY_DENY, request,
                       "the approval was settled as a denial")
    if grant.approval_id != approval.approval_id or not grant.matches(request):
        # Never re-bound onto a newer operation: a mismatch is staleness, not a hint.
        return _denied(RefusalCode.APPROVAL_STALE, request,
                       "the grant does not bind this operation, target and revision")
    if grant.consumed or now > grant.expires_at:
        return _denied(RefusalCode.APPROVAL_STALE, request,
                       "the grant is used or past its expiry")
    if receipt is None or not receipt.confirmed:
        return _denied(RefusalCode.APPROVAL_RESULT_UNKNOWN, request,
                       "the native owner has not confirmed this approval")
    if (receipt.approval_id != grant.approval_id
            or receipt.native_request_id != request.native_request_id):
        return _denied(RefusalCode.APPROVAL_STALE, request,
                       "the native receipt correlates to another approval or request")
    return AllowedOnce(grant)


def _ceiling_sequence(value: Any) -> list[PolicyCeiling]:
    if value is None:
        return []
    if isinstance(value, (PolicyCeiling, str, bytes)) or not isinstance(value, Sequence):
        raise PolicyRefusal("PERMISSION_CEILING_INVALID", source="synthesis.ceilings",
                            target=type(value).__name__)
    return list(value)


def _require_moment(moment: Any, *, source: str) -> None:
    if not isinstance(moment, dt.datetime) or moment.tzinfo is None \
            or moment.utcoffset() is None:
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source=f"{source}.now",
                            target=None if moment is None else type(moment).__name__)


def _evidence_ref(request: OperationRequest) -> str:
    return f"evid_{request.operation_digest[:16]}"


def _denied(code: Any, request: OperationRequest, message: str) -> Denied:
    return Denied(code=code, evidence_ref=_evidence_ref(request),
                  reason=DecisionReason(code, message))


def _refused(code: Any, *, source: str, target: str | None) -> PolicyRefused:
    refusal = PolicyRefusal(code, source=source, target=target)
    folded = hashlib.sha256(f"{code}\n{source}\n{target}".encode("utf-8")).hexdigest()
    return PolicyRefused(denied=Denied(
        code=code, evidence_ref=f"evid_{folded[:16]}",
        reason=DecisionReason(code, refusal.human_readable)))


def _synthesized(action: RuleAction, *, request: OperationRequest, now: dt.datetime,
                 effective: EffectiveCeiling, code: Any, message: str) -> PolicySynthesized:
    expires_at = now + DECISION_TTL
    decision = AuthorizationDecision.of(
        native_request_id=request.native_request_id,
        operation_digest=request.operation_digest, tool=request.tool_key,
        target=request.target, subject=request.principal, action=action,
        reason=DecisionReason(code, message),
        policy_digest=f"{effective.revision_digest}+{request.policy_revision}",
        expires_at=expires_at)
    snapshot = EffectivePolicySnapshot.issue(
        server_instance_id=request.server_instance_id, session_id=request.session_id,
        native_session_id=request.native_session_id, runtime_generation=request.native_generation,
        principal=request.principal, ceiling_revision=request.ceiling_revision,
        intent_revision=request.policy_revision, issued_at=now, expires_at=expires_at)
    return PolicySynthesized(action=action, decision=decision, snapshot=snapshot)
