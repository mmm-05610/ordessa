"""Plugin registration for the permissions backend (public seam only).

`descriptor()` + `build(context)` speak `server_plugin_api` and nothing else:
the authorizer is contributed as the provided port
`permissions.authorizer@1`, and the same authority behind the public ACP
admission port `acp.admission.gate` (T07/G1): composition installs the
adapter as the host's admission authority, and the harness gate calls it with
the neutral DTOs. The adapter's readiness is derived, never assumed: without
an injected authoritative native-session/runtime-generation evidence source
the composed port honestly answers `ready=False` (exactly the checkpoint's
registered limitation). The two approval wire methods exist only for the
approval UI's decide/query; the third wire method `permissions.policy.describe`
is the Settings region's read-only summary of the policy stores (rules source,
organizational ceiling read-only summary, user default intent, legacy-import
review findings) - a read with no authority in any of its fields. There is
deliberately no wire method that produces a ruling: a desktop client cannot
ask for, let alone forge, `allow`.

The database arrives through the host's `database` port, typed here by the
local Protocol only; this plugin never imports a host, a compat layer or the
harness to reach it.

Two integration bindings close C0's two open items for this package (see the
README for the migration sequence they serve):

* T018 - the `busy()` fact is bound to the platform's real teardown surface:
  a `stop_hooks` entry (run by the host's stop phase in reverse activation
  order, before any disposal, with refusals propagating to the caller) and a
  `disposal` for unload paths that skipped the phase. An open or
  native-unreconciled approval REFUSES the deactivation while this provider
  is still active and serving - it can never disappear quietly with the
  provider - and only a fully settled stop closes the decision routes so no
  new grant can be decided against a leaving authority;
* T019 - the OLD `approvals.decide` wire method is available gated behind
  `approval_route="legacy-delegated"`, served by the SAME authorizer (see
  `delegate.py`); the default build declares no legacy route at all.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_permissions_api import (
    AlreadyRecorded,
    ApprovalScope,
    InvalidApproval,
    PolicyRefusal,
    QueriedApproval,
    QueryUnknown,
    Recorded,
    UnknownApproval,
)
from server_plugin_api import (
    ACP_ADMISSION_PORT,
    ContributionOwnerBusyError,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .admission import PermissionsAcpAdmission
from .authority import AUTHORITY_METHOD, AUTHORITY_OPTIONAL_PARAMS, PermissionsAuthority
from .authorizer import Authorizer
from .delegate import (LEGACY_DECIDE_METHOD, LEGACY_DECIDE_OPTIONAL,
                       LEGACY_DECIDE_REQUIRED, LegacyApprovalDelegate)
from .describe import (DESCRIBE_OPTIONAL_PARAMS, DESCRIBE_REQUIRED_PARAMS,
                       POLICY_DESCRIBE_METHOD, PolicyDescribe)
from .errors import ApprovalRouteClosedError, DualAuthorityError, PermissionsBackendBusyError
from .facts import ApprovalFacts, VersionConflict
from .policies import PolicyRepository

__all__ = ["AUTHORITY_PORT", "AUTHORIZER_PORT", "PLUGIN_ID", "PermissionsBackendPlugin"]

PLUGIN_ID = "permissions-backend"
AUTHORIZER_PORT = "permissions.authorizer@1"
#: The authority FACT query port (PE1, 016; api twin
#: `ordessa_permissions_api.AUTHORITY_QUERY_PORT` - a guard test binds the
#: two literals). Read-only facts, never a ruling; the in-process object is
#: also the `permissions.authority.query@1` provided port.
AUTHORITY_PORT = "permissions.authority.query@1"
#: Composition-facing port names for the admission adapter's optional
#: authority sources. Absent wiring keeps the port honestly unready.
NATIVE_EVIDENCE_PORT = "acp.admission.native_evidence"
PRINCIPAL_PORT = "acp.admission.principal"
INSTANCE_PORT = "server.instance_id"
DECIDE_METHOD = "permissions.approvals.decide"
QUERY_METHOD = "permissions.approvals.query"
#: The two gated shapes of the old wire route (T019). `q5-only` (the default)
#: declares no `approvals.decide` at all; `legacy-delegated` mounts it onto
#: this plugin's own `Authorizer.decide` - one authority, one store, one
#: event stream. Retiring the compat writer itself remains composition's step.
APPROVAL_ROUTE_Q5_ONLY = "q5-only"
APPROVAL_ROUTE_LEGACY_DELEGATED = "legacy-delegated"
_APPROVAL_ROUTES = frozenset({APPROVAL_ROUTE_Q5_ONLY, APPROVAL_ROUTE_LEGACY_DELEGATED})
#: Ports owned by the old approval writer. If composition ever hands them to
#: this plugin while the delegated route is on, that is the dual writer.
_LEGACY_WRITER_PORTS = ("approvals.records", "compat.handlers")
_DECIDE_REQUIRED = frozenset(
    {"requestId", "approvalId", "expectedVersion", "decision", "scope", "sessionId"})
_QUERY_REQUIRED = frozenset({"approvalId", "nativeRequestId"})


def _decide_body(result: Any) -> dict[str, Any]:
    if isinstance(result, Recorded):
        return {"outcome": "recorded", "version": result.version,
                "decision": result.decision.value}
    if isinstance(result, AlreadyRecorded):
        return {"outcome": "already_recorded", "version": result.version,
                "decision": result.decision.value, "requestId": result.request_id}
    if isinstance(result, InvalidApproval):
        return {"outcome": "invalid", "reason": result.reason}
    if isinstance(result, VersionConflict):
        return {"outcome": "version_conflict", "version": result.version,
                "reason": result.reason}
    if isinstance(result, UnknownApproval):
        return {"outcome": "unknown", "reason": result.reason}
    return {"outcome": "unknown", "reason": "unrecognised decide result"}


def _query_body(outcome: Any) -> dict[str, Any]:
    if isinstance(outcome, QueriedApproval):
        state = outcome.state
        return {
            "outcome": "resolved",
            "state": {
                "approvalId": state.approval_id, "sessionId": state.session_id,
                "executionId": state.execution_id, "version": state.version,
                "state": state.state.value,
                "decision": None if state.decision is None else state.decision.value,
                "scope": None if state.scope is None else state.scope.as_record(),
                "requestId": state.request_id, "nativeRequestId": state.native_request_id,
            },
            "receipt": None if outcome.receipt is None else {
                "nativeRequestId": outcome.receipt.native_request_id,
                "approvalId": outcome.receipt.approval_id,
                "confirmed": outcome.receipt.confirmed,
                "observedAt": None if outcome.receipt.observed_at is None
                else outcome.receipt.observed_at.isoformat(),
            },
            # `resolved` states the approval fact; only a confirmed receipt may
            # ever read as execution proceeding, and this body never claims it.
            "grantsExecution": bool(outcome.native_confirmed),
        }
    if isinstance(outcome, QueryUnknown):
        return {"outcome": "unknown", "reason": outcome.reason, "grantsExecution": False}
    return {"outcome": "unknown", "reason": "unrecognised query result",
            "grantsExecution": False}


def _decide_handler(authorizer: Authorizer) -> Callable[[Mapping[str, Any]], dict]:
    def handle(params: Mapping[str, Any]) -> dict[str, Any]:
        missing = _DECIDE_REQUIRED - set(params)
        if missing:
            raise ValueError(f"missing required params: {sorted(missing)}")
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
        result = authorizer.decide(
            approval_id=str(params["approvalId"]), expected_version=expected_version,
            decision=str(decision), scope=dict(scope),
            operation_key=str(params["requestId"]), session_id=str(params["sessionId"]))
        return _decide_body(result)
    return handle


def _query_handler(authorizer: Authorizer) -> Callable[[Mapping[str, Any]], dict]:
    def handle(params: Mapping[str, Any]) -> dict[str, Any]:
        missing = _QUERY_REQUIRED - set(params)
        if missing:
            raise ValueError(f"missing required params: {sorted(missing)}")
        return _query_body(authorizer.reconcile(str(params["approvalId"]),
                                                str(params["nativeRequestId"])))
    return handle


class _RouteLifecycle:
    """The per-registration route state the deactivation binding reads.

    Two facts, one owner: `closed` (the accepted stop round has shut the
    decision routes - reads stay served) and `in_flight` (a decide/admission
    call is executing across the contributed ports right now). The plugin's
    `stop_hooks` refuse on those facts and the handlers consult them; nothing
    else in the package mutates them.
    """

    def __init__(self) -> None:
        self._closed = False
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def tracked(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Count one public call as in-flight for exactly its own duration."""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._in_flight += 1
            try:
                return fn(*args, **kwargs)
            finally:
                self._in_flight -= 1
        return wrapper


def _guarded(lifecycle: _RouteLifecycle, method_id: str,
             handler: Callable[[Mapping[str, Any]], dict]) -> Callable[..., dict]:
    """A decide handler that refuses once the deactivation has been accepted.

    The check runs inside the in-flight window, so a stop hook re-entrant
    with a request sees the truth (`ContributionOwnerBusyError`), and a
    request that arrives after the accepted stop never reaches the store.
    """
    def wrapper(params: Mapping[str, Any]) -> dict[str, Any]:
        tracked = lifecycle.tracked(handler)
        return tracked(params) if not lifecycle.is_closed() else _refuse_closed(method_id)
    return wrapper


def _refuse_closed(method_id: str) -> dict:
    raise ApprovalRouteClosedError(method_id)


class PermissionsBackendPlugin:
    """A `ServerPlugin` (structural protocol) contributing the authorizer and
    the ACP admission adapter built over it.

    Its lifecycle binding (C0 request #1, T018): the registration declares
    one `stop_hooks` entry and a `disposal`, both reading the `busy()` fact.
    A busy stop refuses loudly - the provider stays active, every approval
    row stays queryable, and the decide routes stay open so the operator can
    settle; an in-flight decision refuses with the platform's own
    `ContributionOwnerBusyError`; only after every fact is settled and
    reconciled does the accepted stop close the decision routes, and the
    matching `disposal` repeats the refusal for any teardown that skipped
    the stop phase. An open approval cannot disappear with the provider.
    """

    def __init__(self, *, admission_native_evidence: Callable[[], Any] | None = None,
                 admission_principal_provider: Callable[[Any], Any] | None = None,
                 admission_server_instance_id: Any = None,
                 approval_route: str = APPROVAL_ROUTE_Q5_ONLY) -> None:
        # Constructor injection wins over the named ports; both are optional,
        # and their absence keeps the admission port honestly unready instead
        # of assuming authority that composition never wired.
        self._admission_evidence = admission_native_evidence
        self._admission_principal = admission_principal_provider
        self._admission_instance = admission_server_instance_id
        if approval_route not in _APPROVAL_ROUTES:
            raise ValueError(
                f"unknown approval_route {approval_route!r}; the old wire "
                f"route is gated - {APPROVAL_ROUTE_Q5_ONLY!r} declares no "
                f"approvals.decide, {APPROVAL_ROUTE_LEGACY_DELEGATED!r} "
                "mounts it on this plugin's single authorizer")
        self._approval_route = approval_route

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Ordessa Permissions", version="0.1.0")

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        database = ports["database"]
        if self._approval_route == APPROVAL_ROUTE_LEGACY_DELEGATED:
            shadowed = sorted(name for name in _LEGACY_WRITER_PORTS if name in ports)
            if shadowed:
                raise DualAuthorityError(
                    "the old approval writer is live on this composition's ports"
                    f" ({', '.join(shadowed)}); two authorities would write"
                    " server_approvals")
        facts = ApprovalFacts(database, append_event=ports.get("approvals.appendEvent"))
        policies = PolicyRepository(database)
        authorizer = Authorizer(facts=facts, policies=policies,
                                ceiling_provider=policies.ceilings_current,
                                intent_provider=lambda: None)
        lifecycle = _RouteLifecycle()
        admission = PermissionsAcpAdmission(
            authorizer=authorizer,
            native_evidence=self._admission_evidence or ports.get(NATIVE_EVIDENCE_PORT),
            principal_provider=self._admission_principal or ports.get(PRINCIPAL_PORT),
            server_instance_id=self._admission_instance if self._admission_instance is not None
            else ports.get(INSTANCE_PORT),
            closed=lifecycle.is_closed)
        # The grant routes are counted in-flight so a stop re-entrant with an
        # admission call refuses through the platform's own busy error.
        admission.authorize_submission = lifecycle.tracked(admission.authorize_submission)
        admission.authorize_permission = lifecycle.tracked(admission.authorize_permission)

        def ensure_schema() -> None:
            import sys
            print(f"[ensure_schema] called, db={database.path}", file=sys.stderr)
            facts.ensure_schema()
            policies.ensure_schema()

        describe = PolicyDescribe(policies, ready=lambda: admission.ready)
        # The authority FACT surface (PE1): one read-only query method plus
        # the provided port. Reads stay served after an accepted stop - the
        # authority port is deliberately NOT in `held_points`, so an operator
        # can still see who approved what while the decision routes are down.
        authority = PermissionsAuthority(facts, policies)
        methods = [
            ServerMethodDescriptor(method_id=DECIDE_METHOD, required_params=_DECIDE_REQUIRED,
                                   optional_params=frozenset(),
                                   handler=_guarded(lifecycle, DECIDE_METHOD,
                                                    _decide_handler(authorizer)),
                                   owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id=QUERY_METHOD, required_params=_QUERY_REQUIRED,
                                   optional_params=frozenset(),
                                   handler=_query_handler(authorizer), owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id=POLICY_DESCRIBE_METHOD,
                                   required_params=DESCRIBE_REQUIRED_PARAMS,
                                   optional_params=DESCRIBE_OPTIONAL_PARAMS,
                                   handler=describe.describe, owner=PLUGIN_ID,
                                   availability=describe.availability),
            ServerMethodDescriptor(method_id=AUTHORITY_METHOD,
                                   required_params=frozenset(),
                                   optional_params=AUTHORITY_OPTIONAL_PARAMS,
                                   handler=authority.query, owner=PLUGIN_ID,
                                   availability=authority.availability),
        ]
        held_points = (AUTHORIZER_PORT, ACP_ADMISSION_PORT)
        if self._approval_route == APPROVAL_ROUTE_LEGACY_DELEGATED:
            # the old wire method, served by the SAME authorizer: one CAS,
            # one `decideRequestId` idempotency, one store, one event stream
            delegate = LegacyApprovalDelegate(authorizer,
                                              accepting=lambda: not lifecycle.is_closed())
            methods.append(ServerMethodDescriptor(
                method_id=LEGACY_DECIDE_METHOD, required_params=LEGACY_DECIDE_REQUIRED,
                optional_params=LEGACY_DECIDE_OPTIONAL,
                handler=_guarded(lifecycle, LEGACY_DECIDE_METHOD, delegate.decide),
                owner=PLUGIN_ID))
            held_points = held_points + (LEGACY_DECIDE_METHOD,)

        def refuse_deactivation() -> None:
            """The host's stop phase consults the real facts, in the order
            that can never drop one: an in-flight call first (a live
            reference must not be stolen - the platform's own refusal), then
            unresolved approvals (the T02 busy fact; refusing here keeps the
            provider serving, so the rows stay queryable and settleable),
            and only a settled world closes the decision routes."""
            if lifecycle.in_flight:
                raise ContributionOwnerBusyError(PLUGIN_ID, held_points)
            busy = facts.busy()
            if busy:
                raise PermissionsBackendBusyError(busy, open_count=facts.open_count())
            lifecycle.close()

        def dispose() -> None:
            """The unload/shutdown disposal repeats the refusal for any path
            that bypassed the stop phase: a provider with unresolved facts
            says so rather than disposing quietly."""
            lifecycle.close()
            busy = facts.busy()
            if busy:
                raise PermissionsBackendBusyError(busy, open_count=facts.open_count())

        return ServerPluginRegistration(
            methods=tuple(methods),
            provided_ports={AUTHORIZER_PORT: authorizer, ACP_ADMISSION_PORT: admission,
                            AUTHORITY_PORT: authority},
            start_hooks=(ensure_schema,),
            stop_hooks=(refuse_deactivation,),
            disposal=dispose)
