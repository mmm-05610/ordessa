"""Typed store-level failures of the permissions backend.

The §C1 result unions carry the decide/query outcomes; these exceptions name
the integrity violations that must never become a result value at all (a
corrupt write, a foreign correlation, an absent row the caller insisted on
reading), plus the two lifecycle refusals of C0's deactivation binding (T018)
and the legacy-route authority gate (T019).

The lifecycle refusals are `RuntimeError`s on purpose: that is the shape the
platform's teardown phases surface - `ServerPluginHost.run_stop_hooks` lets a
raising hook propagate to the caller (the compat plugin's own stop hook raises
`RuntimeError("SERVER_STOP_TIMEOUT")` the same way), and a raising `disposal`
reaches the unloader on the direct path / rides on the shutdown as the host's
carried cleanup fact. A refusal that could be swallowed would be exactly the
silent drop C0's request forbids.
"""
from __future__ import annotations

__all__ = ["ApprovalNotFound", "ApprovalRouteClosedError", "CorrelationConflict",
           "DualAuthorityError", "PermissionsBackendBusyError"]


class ApprovalNotFound(LookupError):
    """A row the caller asked about does not exist in the authority."""

    def __init__(self, approval_id: str) -> None:
        super().__init__(f"approval_not_found: {approval_id}")
        self.approval_id = approval_id


class CorrelationConflict(ValueError):
    """A receipt or consumption attempt that does not belong to this fact."""

    def __init__(self, approval_id: str, detail: str) -> None:
        super().__init__(f"native correlation conflict for {approval_id}: {detail}")
        self.approval_id = approval_id
        self.detail = detail


class PermissionsBackendBusyError(RuntimeError):
    """Deactivation refused while the authority still owns unresolved facts.

    `busy_count` is the T02 busy fact (open approvals plus settled-allow
    grants whose native receipt is unreconciled); `open_count` separates the
    still-answerable ones. Raised from the plugin's `stop_hooks` while the
    provider is still active - the routes stay live and every row stays
    queryable - and again from `disposal` so a teardown that bypassed the
    stop phase still hears the refusal. An open approval never disappears
    with the provider.
    """

    code = "PERMISSIONS_BACKEND_BUSY"

    def __init__(self, busy_count: int, *, open_count: int = 0) -> None:
        super().__init__(
            f"permissions-backend cannot deactivate while {busy_count} approval"
            f" fact(s) are unresolved ({open_count} open; the rest settled-allow"
            " without a reconciled native receipt); settle and reconcile first"
            " or keep the provider active")
        self.busy_count = busy_count
        self.open_count = open_count


class ApprovalRouteClosedError(RuntimeError):
    """The accepted stop has closed the decision routes.

    After a `stop_hooks` pass found the facts settled, the plugin stops
    accepting NEW decisions: a grant decided against a provider that is on
    its way out could never be reconciled. Reads (query/reconcile) stay
    served until the routes are actually revoked.
    """

    code = "APPROVAL_ROUTE_CLOSED"

    def __init__(self, method_id: str) -> None:
        super().__init__(
            f"{method_id} refused: the permissions backend is deactivating and"
            " accepts no new decisions")
        self.method_id = method_id


class DualAuthorityError(RuntimeError):
    """The legacy route was asked to delegate beside a live old writer.

    One `server_approvals` row may have exactly one decide authority. If the
    composition can hand this plugin the old writer's own port (the compat
    records/handler ports) while `approval_route="legacy-delegated"`, building
    the delegate would create the dual writer C0's counterexample names; the
    build refuses instead. The host-level guard is separate and always on: two
    owners of one wire method id is a `DuplicateMethodError` at activation.
    """

    code = "PERMISSIONS_DUAL_AUTHORITY"

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"legacy-delegated approval route refused: {detail}; retire or"
            " delegate the old writer first - activating both plugins is not"
            " the migration")
        self.detail = detail
