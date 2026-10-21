"""One verified instance caller plus the owner scope the lower owners address.

`RequestContext.invocation` carries the `VerifiedPrincipal` the instance authority
authenticated. Some owners (environments) additionally need the existing owner
scope that owns their rows; that scope is derived here from the same identity and
never invented per request. The wrapper is process-local and never serialized.
"""
from __future__ import annotations

from dataclasses import dataclass

from ordessa_environments.management.ownership import OwnerScope
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import VerifiedPrincipal

from ordessa_server.composition.agent_owner import AgentOwnerUnavailable


@dataclass(frozen=True)
class ServerInvocation:
    """The trusted caller and the existing subject scope of this request."""

    principal: VerifiedPrincipal
    owner_scope: OwnerScope

    @property
    def principal_scope(self) -> str:
        return 'principal:' + self.principal.principal_id


def server_invocation(principal: VerifiedPrincipal) -> ServerInvocation:
    if type(principal) is not VerifiedPrincipal:
        raise AgentOwnerUnavailable('verified instance caller required')
    # ONE vocabulary for this caller: the owner scope's ``kind:ref`` spelling IS
    # the principal scope the Agent owner records (``principal:<principal_id>``).
    # The Agent owner derives its record principal from the owner scope, so a
    # second spelling here would make the environment owner and the Agent owner
    # disagree about who the caller is.
    return ServerInvocation(principal, OwnerScope('principal', principal.principal_id))


def invocation_from_context(context) -> ServerInvocation:
    """Resolve the caller bound by the Server's context factory; absence refuses."""
    if type(context) is not RequestContext:
        raise AgentOwnerUnavailable('original request context required')
    principal = context.invocation
    if type(principal) is not VerifiedPrincipal:
        raise AgentOwnerUnavailable('request carries no verified instance caller')
    return server_invocation(principal)


def principal_from_invocation(invocation) -> VerifiedPrincipal:
    """For guards that only need the principal (Profile access)."""
    if type(invocation) is not ServerInvocation:
        raise AgentOwnerUnavailable('server invocation required')
    return invocation.principal


__all__ = ["ServerInvocation", "invocation_from_context", "principal_from_invocation",
           "server_invocation"]
