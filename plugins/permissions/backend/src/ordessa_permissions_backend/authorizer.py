"""`Authorizer` - the §C1 `permissions.authorizer@1` backend service.

The ruling is delegated to the pure domain (`synthesize` /
`evaluate_authorization` from `ordessa_permissions_api`); the record-keeping
is delegated to `ApprovalFacts` and `PolicyRepository`. This class owns no
second decision engine and no UI shortcut: the approval UI reaches it only
through `decide`/`reconcile`, and the authoritative answer for a tool call is
whatever the pre-effect gate (C0-owned seam, still blocked, G1) asks of
`evaluate`.

Fail-closed is the default, not the exception: a missing ceiling provider, a
provider that raises, an unknown tool, an unresolved execution, an approval
whose revision pins moved, a grant whose native receipt was never observed -
each answers with a stable C4 code or with `Unknown`, and none of them
answers "yes".
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Mapping

from ordessa_permissions_api import (
    GRANT_TTL,
    ApprovalStateKind,
    BoundGrant,
    Denied,
    ExecutionState,
    InvalidApproval,
    OperationRequest,
    PermissionIntent,
    PolicyCeiling,
    PolicyRefusal,
    RefusalCode,
    UnknownApproval,
    approval_id_for,
    evaluate_authorization,
    intersect_ceilings,
)

from .facts import ApprovalFacts
from .policies import PolicyRepository

__all__ = ["Authorizer"]

_NO_CEILINGS: tuple[PolicyCeiling, ...] = ()
_NO_INTENT: PermissionIntent | None = None


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Authorizer:
    """One service, two audiences: the gate calls `evaluate`, the UI calls
    `decide`/`reconcile`. Neither can forge the other's answer."""

    def __init__(self, *, facts: ApprovalFacts,
                 policies: PolicyRepository | None = None,
                 ceiling_provider: Callable[[], Any] | None = None,
                 intent_provider: Callable[[], Any] | None = None,
                 clock: Callable[[], dt.datetime] | None = None) -> None:
        self.facts = facts
        self.policies = policies
        self.ceiling_provider: Callable[[], Any] = (
            ceiling_provider if ceiling_provider is not None
            else (policies.ceilings_current if policies is not None else lambda: ()))
        self.intent_provider: Callable[[], Any] = (
            intent_provider if intent_provider is not None else lambda: _NO_INTENT)
        self.clock = clock or _utc_now

    # -- evaluate (the ruling the pre-effect gate consumes) ----------------------

    def evaluate(self, *, principal: Any, session_ref: Any, execution_ref: Any,
                 native_generation: Any, tool_identity: Any, target_facts: Any,
                 argument_digest: Any, ceiling_revision: Any, policy_revision: Any,
                 native_request_id: Any) -> Any:
        """§C1: `Denied | AllowedOnce(boundGrant) | PendingApproval(approvalId)`.

        Every trusted field arrives required; a missing one never inherits a
        default - it fails closed with the stable unknown-provenance code.
        """
        request = self._operation_request(
            principal=principal, session_ref=session_ref, execution_ref=execution_ref,
            native_generation=native_generation, tool_identity=tool_identity,
            target_facts=target_facts, argument_digest=argument_digest,
            ceiling_revision=ceiling_revision, policy_revision=policy_revision,
            native_request_id=native_request_id)
        if isinstance(request, Denied):
            return request
        return self._rule(request, now=self.clock())

    def evaluate_with_grant(self, *, operation: OperationRequest,
                            grant_fields: Mapping[str, Any]) -> Any:
        """The executor's use of an already-issued grant token.

        Structural defence: `evaluate` above never accepts a client-supplied
        grant - grants are loaded from the store only. This entry point exists
        for the executor re-validation path and still refuses a token with no
        recorded approval: a grant nobody vouches for is `APPROVAL_RESULT_
        UNKNOWN`, never a yes.
        """
        now = self.clock()
        try:
            grant = BoundGrant.from_record(grant_fields)
        except PolicyRefusal as refusal:
            return self._denied(refusal, operation)
        fact = self.facts.approval_fact(grant.approval_id)
        ceilings, denial = self._ceilings_or_denial(operation, now)
        if denial is not None:
            return denial
        intent = self._intent_or_denial(operation)
        if isinstance(intent, Denied):
            return intent
        outcome = evaluate_authorization(
            ceilings=ceilings, intent=intent, request=operation, now=now,
            grant=grant,
            approval=None if fact is None else fact.state,
            receipt=None if fact is None else fact.receipt,
            execution_state=self._execution_state(operation.execution_id))
        return self._finalize(outcome, operation, fact, now)

    # -- decide / reconcile (the approval UI's whole surface) ----------------------

    def decide(self, approval_id: str, expected_version: int, decision: str,
               scope: Mapping[str, Any], operation_key: str, *,
               session_id: str | None = None) -> Any:
        """CAS + idempotent record of the user's ruling, refused outright when
        the world the approval was asked under has moved."""
        now = self.clock()
        try:
            ceilings = self._call_ceiling_provider()
        except Exception:
            return UnknownApproval(reason="policy_provider_unavailable")
        if not ceilings:
            # Cannot re-verify the revision pin: fail closed, decide nothing.
            return UnknownApproval(reason="policy_provider_unavailable")
        row = self.facts.peek(approval_id)
        if row is not None and row["state"] == "open":
            stale = self._revision_staleness(row, ceilings)
            if stale is not None:
                return InvalidApproval(reason=stale)
        return self.facts.decide(approval_id=approval_id, decision=decision,
                                 scope=dict(scope), expected_version=expected_version,
                                 request_id=operation_key, session_id=session_id,
                                 now=now)

    def reconcile(self, approval_id: str, native_request_id: str):
        return self.facts.reconcile(approval_id, native_request_id)

    def busy(self) -> int:
        """Active approvals an unload must wait for (§C4): open facts plus
        settled-allow grants whose native receipt is still unreconciled."""
        return self.facts.busy()

    # -- internals ------------------------------------------------------------------

    def _operation_request(self, *, principal: Any, session_ref: Any, execution_ref: Any,
                           native_generation: Any, tool_identity: Any,
                           target_facts: Any, argument_digest: Any, ceiling_revision: Any,
                           policy_revision: Any, native_request_id: Any) -> Any:
        def field(box: Any, name: str) -> Any:
            if isinstance(box, Mapping):
                return box.get(name)
            return None
        try:
            return OperationRequest.from_record({
                "principal": principal,
                "serverInstanceId": field(session_ref, "serverInstanceId"),
                "sessionId": field(session_ref, "sessionId"),
                "nativeSessionId": field(session_ref, "nativeSessionId"),
                "executionId": execution_ref,
                "nativeGeneration": native_generation,
                "toolKey": getattr(tool_identity, "key", tool_identity),
                "target": field(target_facts, "target"),
                "argumentDigest": getattr(argument_digest, "value", argument_digest),
                "ceilingRevision": ceiling_revision,
                "policyRevision": policy_revision,
                "nativeRequestId": native_request_id,
            })
        except PolicyRefusal as refusal:
            # A missing trusted fact is a refusal naming its code, never a
            # default the caller did not write (FR-02).
            return Denied(code=RefusalCode.POLICY_SCOPE_UNVERIFIED,
                          evidence_ref="evid_unattributed",
                          reason=refusal.human_readable[:512])

    def _rule(self, operation: OperationRequest, *, now: dt.datetime) -> Any:
        ceilings, denial = self._ceilings_or_denial(operation, now)
        if denial is not None:
            return denial
        intent = self._intent_or_denial(operation)
        if isinstance(intent, Denied):
            return intent
        approval_id = approval_id_for(operation_digest=operation.operation_digest,
                                      native_request_id=operation.native_request_id)
        fact = self.facts.approval_fact(approval_id)
        grant: BoundGrant | None = None
        approval = None
        receipt = None
        if fact is not None and fact.state.state in (ApprovalStateKind.SETTLED,
                                                    ApprovalStateKind.INVALID):
            fields = self.facts.grant_fields(approval_id)
            if fields is not None:
                try:
                    grant = BoundGrant.from_record(fields)
                except PolicyRefusal:
                    grant = None
                approval = fact.state
                receipt = fact.receipt
        # An open fact keeps the pending answer: the ruling re-runs under the
        # current ceilings (a tightening can deny it; nothing re-binds a grant).
        try:
            outcome = evaluate_authorization(
                ceilings=ceilings, intent=intent, request=operation, now=now,
                grant=grant, approval=approval, receipt=receipt,
                execution_state=self._execution_state(operation.execution_id))
        except PolicyRefusal as refusal:
            return self._denied(refusal, operation)
        return self._finalize(outcome, operation, fact, now, approval_id=approval_id)

    def _finalize(self, outcome: Any, operation: OperationRequest, fact: Any,
                  now: dt.datetime, *,
                  approval_id: str | None = None) -> Any:
        if outcome.outcome == "pending_approval" and fact is None:
            created = self._record_pending(operation, now)
            if isinstance(created, Denied):
                return created
            return outcome
        if outcome.outcome == "allowed_once" and fact is not None \
                and fact.state.state is ApprovalStateKind.SETTLED:
            # The approval-bound grant is spent atomically here: a second use
            # of the same operation finds the grant consumed and refuses.
            spent = self.facts.consume_grant(
                approval_id=fact.approval_id,
                operation_digest=operation.operation_digest,
                native_request_id=operation.native_request_id, moment=now)
            if not spent:
                return Denied(code=RefusalCode.APPROVAL_STALE,
                              evidence_ref=f"evid_{operation.operation_digest[:16]}",
                              reason="the one-time grant for this operation is spent")
        del approval_id
        return outcome

    def _record_pending(self, operation: OperationRequest, now: dt.datetime) -> Any:
        approval_id = approval_id_for(operation_digest=operation.operation_digest,
                                      native_request_id=operation.native_request_id)
        record = {
            "approvalId": approval_id,
            "sessionId": operation.session_id, "executionId": operation.execution_id,
            "nativeRequestId": operation.native_request_id,
            "operationDigest": operation.operation_digest,
            "toolKey": operation.tool_key, "target": operation.target,
            "ceilingRevision": operation.ceiling_revision,
            "policyRevision": operation.policy_revision,
            "nativeGeneration": operation.native_generation,
            "requestedAt": now.isoformat(),
            "expiresAt": (now + GRANT_TTL).isoformat(), "version": 1,
        }
        try:
            self.facts.request(session_id=operation.session_id,
                               execution_id=operation.execution_id, request=record)
        except PolicyRefusal as refusal:
            return self._denied(refusal, operation)
        return record

    def _ceilings_or_denial(self, operation: OperationRequest, now: dt.datetime):
        try:
            raw = self._call_ceiling_provider()
        except Exception:
            return (), Denied(code=RefusalCode.POLICY_ADAPTER_MISSING,
                              evidence_ref=f"evid_{operation.operation_digest[:16]}",
                              reason="the ceiling provider failed; nothing proceeds")
        ceilings = tuple(raw or ())
        if not ceilings:
            return (), Denied(code=RefusalCode.POLICY_ADAPTER_MISSING,
                              evidence_ref=f"evid_{operation.operation_digest[:16]}",
                              reason="no trusted ceiling is in force")
        return ceilings, None

    def _call_ceiling_provider(self) -> Any:
        return self.ceiling_provider()

    def _intent_or_denial(self, operation: OperationRequest):
        try:
            intent = self.intent_provider()
        except PolicyRefusal as refusal:
            return self._denied(refusal, operation)
        except Exception:
            return Denied(code=RefusalCode.POLICY_ADAPTER_MISSING,
                          evidence_ref=f"evid_{operation.operation_digest[:16]}",
                          reason="the intent provider failed")
        return intent if isinstance(intent, PermissionIntent) else None

    def _execution_state(self, execution_id: str):
        state = self.facts.execution_state(execution_id)
        if state is None:
            return ExecutionState.UNKNOWN  # unresolved: never folded into a yes
        if state in {"accepted", "dispatching", "running", "capturing"}:
            return ExecutionState.RUNNING
        try:
            return ExecutionState.of(state)
        except PolicyRefusal:
            return ExecutionState.UNKNOWN

    def _revision_staleness(self, row: Mapping[str, Any],
                            ceilings: tuple[PolicyCeiling, ...]) -> str | None:
        try:
            digest = intersect_ceilings(list(ceilings)).revision_digest
        except PolicyRefusal:
            return "APPROVAL_STALE: the effective ceiling cannot be recomputed"
        pinned_ceiling = row.get("ceilingRevision")
        if pinned_ceiling is not None and pinned_ceiling != digest:
            return (f"APPROVAL_STALE: the ceiling moved ({pinned_ceiling}"
                    f" -> {digest}); re-request approval for this operation")
        return None

    @staticmethod
    def _denied(refusal: PolicyRefusal, operation: OperationRequest) -> Denied:
        code = refusal.refusal_code
        if code is None:
            code = RefusalCode.POLICY_SCOPE_UNVERIFIED
        return Denied(code=code,
                      evidence_ref=f"evid_{operation.operation_digest[:16]}",
                      reason=refusal.human_readable[:512])
