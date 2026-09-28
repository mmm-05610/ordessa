"""`LegacyApprovalDelegate` - the OLD `approvals.decide` wire route, served by
the one Q5 authorizer (T019, C0's single-writer migration request).

C0's counterexample verbatim: with both this backend and the compatibility
plugin active, `approvals.decide` and `permissions.approvals.decide` write
`server_approvals` as two authorities. "Product assembly must retire or
delegate the compat route before enabling Q5 Permissions backend" - this
module is the delegate option: the retained old wire method keeps its exact
declaration and answers, but every call lands on the SAME `Authorizer.decide`
that serves `permissions.approvals.decide`. There is no second store and no
second event stream here: the row, its minted id, the `approval.requested` /
`approval.settled` events, the CAS on `version` and the `decideRequestId`
idempotency are the ones `ApprovalFacts` already owns.

What is deliberately NOT preserved is the old writer's ability to settle a
row the grant cannot act on. The migration rule refuses it: a record without
the native operation/session/generation facts (a row the old authority minted
without correlation, or a half-migrated row missing any of them) is refused
type-wise BEFORE any decision is written - the typed `unknown` outcome, the
row untouched. The old wire shape carries no `sessionId` param, so the session
fact is read from the stored row, and its absence refuses too.

Registration is gated, never automatic: the route exists only for a plugin
built with `approval_route="legacy-delegated"`, and retiring the compat
writer itself stays C0's step (this package never edits or unregisters it).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_permissions_api import (
    AlreadyRecorded,
    ApprovalScope,
    InvalidApproval,
    PolicyRefusal,
    Recorded,
    UnknownApproval,
)

from .authorizer import Authorizer

__all__ = ["LEGACY_DECIDE_METHOD", "LEGACY_DECIDE_OPTIONAL", "LEGACY_DECIDE_REQUIRED",
           "LegacyApprovalDelegate"]

#: The old wire method id, kept exactly - the wire identity is data
#: (`plugins/server-compat`'s dispatch table and the desktop clients call
#: this name; the retirement document is in the package README).
LEGACY_DECIDE_METHOD = "approvals.decide"
#: The exact old param declaration, mirrored from the compat core's wire
#: table (`core_wire.py:327-329`): five required, no optional, NO sessionId -
#: the delegated route derives the session from the stored row or refuses.
LEGACY_DECIDE_REQUIRED = frozenset(
    {"requestId", "approvalId", "expectedVersion", "decision", "scope"})
LEGACY_DECIDE_OPTIONAL = frozenset()

#: The facts a grant needs in order to act (C1's grant binding): the native
#: request, the operation digest it pins, the generation it was asked under,
#: and the ledger session that owns the row. A missing one is a refusal, not
#: a permission.
_REQUIRED_GRANT_FACTS = ("sessionId", "nativeRequestId", "operationDigest",
                         "nativeGeneration")


class LegacyApprovalDelegate:
    """The old wire's handler face, wired onto the new single authority."""

    def __init__(self, authorizer: Authorizer, *,
                 accepting: Callable[[], bool] | None = None) -> None:
        self._authorizer = authorizer
        # `accepting` is the plugin's route lifecycle: False once the stop
        # round has accepted the deactivation. Delegate and Q5 route share it,
        # so the SAME close gates both spellings of decide.
        self._accepting = accepting if accepting is not None else (lambda: True)

    # -- the wire handler ------------------------------------------------------

    def decide(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if not self._accepting():
            from .errors import ApprovalRouteClosedError
            raise ApprovalRouteClosedError(LEGACY_DECIDE_METHOD)
        missing = LEGACY_DECIDE_REQUIRED - set(params)
        if missing:
            raise ValueError(f"missing required params: {sorted(missing)}")
        # The old wire's own validation rules, kept: a client must not see a
        # new-shaped refusal for an old-shaped mistake.
        decision = params["decision"]
        if decision not in {"allow", "deny"}:
            raise ValueError("decision must be allow or deny")
        expected_version = params["expectedVersion"]
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) \
                or expected_version < 1:
            raise ValueError("expectedVersion must be a positive integer")
        scope = params["scope"]
        if not isinstance(scope, Mapping):
            raise ValueError("scope must be an object")
        try:
            ApprovalScope.from_record(dict(scope))  # shape-checked before any write
        except PolicyRefusal as refusal:
            raise ValueError(refusal.human_readable) from refusal

        approval_id = str(params["approvalId"])
        request_id = str(params["requestId"])
        row = self._authorizer.facts.peek(approval_id)
        if row is None:
            # The old route raised APPROVAL_NOT_FOUND; the delegated answer is
            # the authority's typed unknown - never a recorded decision.
            return self._body(UnknownApproval(reason="approval_not_found"))
        absent = [name for name in _REQUIRED_GRANT_FACTS if not row.get(name)]
        if absent:
            # Refuse BEFORE the grant can act: no half-written settle.
            return self._body(UnknownApproval(
                reason="native_facts_missing:" + ",".join(absent)))
        result = self._authorizer.decide(
            approval_id=approval_id, expected_version=expected_version,
            decision=str(decision), scope=dict(scope), operation_key=request_id,
            session_id=str(row["sessionId"]))
        return self._body(result)

    # -- the old answer shape ---------------------------------------------------

    @staticmethod
    def _body(result: Any) -> dict[str, Any]:
        """`{"outcome", "decision"}` as the old route answered, plus the
        fail-closed fields this authority can never omit."""
        if isinstance(result, Recorded):
            return {"outcome": "recorded", "decision": result.decision.value,
                    "version": result.version, "grantsExecution": False}
        if isinstance(result, AlreadyRecorded):
            return {"outcome": "already_recorded", "decision": result.decision.value,
                    "version": result.version, "requestId": result.request_id,
                    "grantsExecution": False}
        if isinstance(result, InvalidApproval):
            return {"outcome": "invalid", "reason": result.reason,
                    "grantsExecution": False}
        if isinstance(result, UnknownApproval):
            return {"outcome": "unknown", "reason": result.reason,
                    "grantsExecution": False}
        kind = getattr(result, "kind", None)
        if kind == "version_conflict":
            return {"outcome": "version_conflict", "version": result.version,
                    "reason": result.reason, "grantsExecution": False}
        return {"outcome": "unknown", "reason": "unrecognised decide result",
                "grantsExecution": False}
