"""Server decision admission over the SAME verified instance identity.

The authority is the original ``InstanceAccessAuthority``; this adapter creates no
principal, grant, catalog or evidence ACL. Every check re-verifies the principal
(so revocation applies immediately) and requires the exact ``decisions.*`` grant
for the operation. It is the production ``decision_access`` the authorization
wrapper expects; without it the Server refuses decision calls.
"""
from __future__ import annotations

from collections.abc import Mapping

from ordessa_decision import DecisionError
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessError,
    InstanceAccessAuthority,
)
from ordessa_server.composition.invocation import ServerInvocation


class ServerDecisionAccess:
    """Decision policy for the Server's single instance identity."""

    def __init__(self, authority: InstanceAccessAuthority) -> None:
        if type(authority) is not InstanceAccessAuthority:
            raise TypeError('original instance authority required')
        self._authority = authority

    def _verified(self, invocation, operation: str) -> ServerInvocation:
        if type(invocation) is not ServerInvocation:
            raise DecisionError('permission_denied')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise DecisionError('authority_unavailable') from None
        granted = {capability for grant in invocation.principal.grants
                   for capability in grant.capabilities}
        if operation not in granted:
            raise DecisionError('permission_denied')
        return invocation

    def authorize_operation(self, invocation, operation_id: str, request: Mapping) -> bool:
        self._verified(invocation, str(operation_id))
        return True

    def authorize_evidence_store(self, invocation, original_store, purpose) -> bool:
        # The evidence store is scoped by the same instance identity; a write is
        # the run grant and a read is the get grant.
        self._verified(invocation, 'decisions.run' if purpose == 'write' else 'decisions.get')
        return True

    def authorize_evidence(self, invocation, original_store, digest: str) -> bool:
        self._verified(invocation, 'decisions.get')
        return True


__all__ = ['ServerDecisionAccess']
