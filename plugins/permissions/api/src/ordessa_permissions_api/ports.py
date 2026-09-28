"""The neutral public port contract for `permissions.authorizer@1` (§C1, T017).

Before this module the authorizer's method surface existed only as the
concrete class `ordessa_permissions_backend.Authorizer`, so a consumer had to
either import backend internals or guess the signature (C0 integration
review, the api review note under specs/011-c0-foundation-harness). The
contract is published HERE - the package consumers are allowed to look at -
and stays pure domain: stdlib plus this package, exactly like every other
module here.

Carriers: no second DTO layer is invented. The real backend accepts, per
field, either a plain text value or this package's existing types -
`OperationRequest` (whose `build_operation_request` is the recommended way to
derive the revision pins), `ToolIdentity` (read via `.key`), `ArgumentDigest`
(read via `.value`) - plus two narrow Mapping fields whose exact keys are
spelled out in the method docstrings below (`session_ref`, `target_facts`).
Typed wrappers named PrincipalRef/SessionRef/... are deliberately NOT added:
the backend reads Mappings and strings, a dataclass carrier would be refused
by the very implementation this port describes, and a contract that the
producer does not accept is a second fiction, not a port.

Naming note: §C1 writes the read surface as "query/reconcile" as ONE
operation; the backend answers it with `reconcile` (its approval query wire
handler calls exactly that). This protocol therefore declares `reconcile`
and no phantom `query` member - a guard test re-reads the backend source to
keep that true. The backend's `evaluate_with_grant` executor re-validation
entry point is intentionally not part of the public port.
"""
from __future__ import annotations

from typing import Any, Final, Mapping, Protocol

from .decisions import AllowedOnce, DecideResult, Denied, PendingApproval, QueryOutcome

__all__ = [
    "PERMISSIONS_AUTHORIZER_PORT",
    "PERMISSIONS_AUTHORIZER_PORT_VERSION",
    "EvaluationOutcome",
    "PermissionsAuthorizerPort",
]

#: The provided-port name the backend registers the authorizer under
#: (`ordessa_permissions_backend.plugin.AUTHORIZER_PORT`; a guard test binds
#: this literal to that source text so the two cannot drift). Consumers fetch
#: the single ruling authority through this name and this contract only.
PERMISSIONS_AUTHORIZER_PORT: Final[str] = "permissions.authorizer@1"

#: Version 1 describes the §C1 method surface as the backend actually exposes
#: it. A future widening (new method, new required input) must bump this and
#: may not silently re-bind an existing member.
PERMISSIONS_AUTHORIZER_PORT_VERSION: Final[int] = 1

#: The §C1 evaluate result union, published spelling.
EvaluationOutcome = Denied | AllowedOnce | PendingApproval


class PermissionsAuthorizerPort(Protocol):
    """The `permissions.authorizer@1` surface: one service, two audiences.

    The pre-side-effect gate calls `evaluate`; the approval UI acts through
    `decide` and `reconcile`; the host consults `busy` before deactivation.

    This is deliberately not runtime-checkable: matching method names cannot
    distinguish an authority bound to trusted storage from an object that
    merely has the shape. Composition installs the backend-provided instance
    under `PERMISSIONS_AUTHORIZER_PORT`, and the version marker alone is
    never evidence that the ruling is available.

    Authority rules every consumer must keep:

    * the port, not a wire method or a UI button, is the authority: the only
      answer that lets a side effect proceed is an `AllowedOnce` whose grant
      the executor re-validates (target, revisions, expiry, digest, one use);
    * presence is not readiness - a registered port with no trusted ceiling
      in force must still answer by refusing, never by defaulting;
    * a missing, stale or unobserved input is a refusal before side effects
      (§C1/§C4): every `evaluate` field is required, and an unattributed or
      unresolvable operation comes back `Denied` or `Unknown`, never `yes`;
    * `busy` must be consulted before deactivation: an open approval or an
      unreconciled spent-grant fact may not disappear with the provider.

    The parameter names, kinds and defaults below are verified member by
    member against `ordessa_permissions_backend.Authorizer` by
    `tests/test_neutral_authorizer_port.py`; do not "clean up" one side
    without the other.
    """

    def evaluate(self, *, principal: Any, session_ref: Any, execution_ref: Any,
                 native_generation: Any, tool_identity: Any, target_facts: Any,
                 argument_digest: Any, ceiling_revision: Any, policy_revision: Any,
                 native_request_id: Any) -> EvaluationOutcome:
        """Rule on one already-bound operation, before any side effect.

        §C1: `Denied(code, evidenceRef) | AllowedOnce(boundGrant) |
        PendingApproval(approvalId)`. Every input is required and trusted
        from the caller's own authority layer (authenticated principal and
        session/execution from the Server; native generation, request id and
        normalized tool/target/argument digest from the ACP owner); nothing
        here may be a display string or a renderer assertion.

        Expected shapes, as the implementation reads them today:
        `principal`, `execution_ref`, `native_generation`,
        `ceiling_revision`, `policy_revision`, `native_request_id` are text;
        `tool_identity` is a `ToolIdentity` or a declared tool key;
        `argument_digest` is an `ArgumentDigest` or its 64-char hex string;
        `session_ref` is a Mapping carrying exactly the keys
        `serverInstanceId`, `sessionId`, `nativeSessionId`; `target_facts` is
        a Mapping carrying the key `target`. Build them through
        `build_operation_request` and pass its fields when you can: the
        revision pins are derived there, not typed in.
        """
        ...

    def decide(self, approval_id: str, expected_version: int, decision: str,
               scope: Mapping[str, Any], operation_key: str, *,
               session_id: str | None = None) -> DecideResult:
        """Record the user's ruling with CAS + idempotency (§C1).

        Returns the `DecideResult` union: `Recorded | AlreadyRecorded |
        InvalidApproval | UnknownApproval` - the §C1
        `Recorded | AlreadyRecorded | Invalid | Unknown` spelling. A moved
        revision pin makes the decision `InvalidApproval`, and an
        unresolvable policy state stays `UnknownApproval`: neither ever
        grants a stale operation.
        """
        ...

    def reconcile(self, approval_id: str, native_request_id: str) -> QueryOutcome:
        """The §C1 read surface (`query/reconcile`): the approval state plus
        the native receipt, or `QueryUnknown`.

        `QueryUnknown` is not `no`: a lost post-effect receipt keeps the
        operation unresolved and the provider `busy` until reconciled, and
        no caller may fold it into an allow.
        """
        ...

    def busy(self) -> int:
        """Unresolved approval facts (§C4): open approvals plus settled
        grants whose native receipt is unreconciled.

        A host deactivating or replacing this port must consult this first -
        an approval must not outlive its authority.
        """
        ...
