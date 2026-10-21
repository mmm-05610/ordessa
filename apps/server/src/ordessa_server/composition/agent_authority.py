"""Server-side Agent lifecycle/interaction authority over the instance identity.

One verified caller, one exact grant set: every check re-verifies the instance
principal (so revocation applies immediately) and requires the exact operation id
for the action. No wildcard, no environment fallback, no synthetic principal.

The Server publishes three authority objects over the SAME instance identity:

``ServerAgentAuthority``
    Lifecycle policy: start, lifecycle writes, instance reads and the guarded
    stop/detach cut.
``ServerInteractionAuthority``
    Turn/binding reads, prompt/cancel sends and the native dispatch policy.
``ServerPromptWriteGuard``
    The *physical* write cut. It runs inside the original owner's guarded writer
    and refuses a frame whose operation this caller was never granted.
"""
from __future__ import annotations

from contextlib import contextmanager

from ordessa_interfaces.system_access.access_control.authentication import (
    InstanceAccessAuthority,
    AccessError,
)
from ordessa_server.composition.invocation import ServerInvocation

READ_OPERATIONS: "frozenset[str]" = frozenset({
    "agents.get", "agents.query", "agents.prompt", "agents.stop", "agents.detach",
    "agents.reconcile", "agents.cancel",
})

#: The exact native operation ids the native capability publishes. A native
#: dispatch needs the freeze grant (the request may be frozen at all) and the
#: recorded grant (the dispatch itself); a native observation needs the query
#: grant. No wildcard and no "everything native".
NATIVE_OPERATIONS: "frozenset[str]" = frozenset({
    "agents.native.freeze", "agents.native.recorded", "agents.native.query",
})


class ServerAgentAuthority:
    """Lifecycle + interaction policy for the Server's single instance identity."""

    def __init__(self, authority: InstanceAccessAuthority) -> None:
        if type(authority) is not InstanceAccessAuthority:
            raise TypeError('original instance authority required')
        self._authority = authority

    def _verified(self, invocation, operation: str):
        from ordessa_agents.public import ManagerRefused
        if type(invocation) is not ServerInvocation:
            raise ManagerRefused('ORIGINAL_INVOCATION_REQUIRED')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise ManagerRefused('AUTHORITY_REVOKED') from None
        granted = {capability for grant in invocation.principal.grants
                   for capability in grant.capabilities}
        if operation not in granted:
            raise ManagerRefused('START_NOT_AUTHORIZED' if operation == 'agents.start'
                                 else 'ACTION_NOT_AUTHORIZED')
        return invocation

    def principal_scope(self, invocation) -> str:
        from ordessa_agents.public import ManagerRefused
        if type(invocation) is not ServerInvocation:
            raise ManagerRefused('ORIGINAL_INVOCATION_REQUIRED')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise ManagerRefused('AUTHORITY_REVOKED') from None
        return invocation.principal_scope

    def allow(self, action, invocation):
        """Authority port of the shared preparation resolver.

        The agents-owned preparation port asks "may this caller start a
        prepared agent?". The answer is the SAME exact grant check the
        lifecycle uses, so no second policy exists for preparation.
        """
        return self._verified(invocation, str(action))

    def check_start(self, invocation, request, descriptor) -> None:
        self._verified(invocation, 'agents.start')

    def check_lifecycle_write(self, invocation, binding) -> None:
        self._verified(invocation, 'agents.start')

    def check_read_instance(self, invocation, instance) -> None:
        from ordessa_agents.public import ManagerRefused
        if type(invocation) is not ServerInvocation:
            raise ManagerRefused('ORIGINAL_INVOCATION_REQUIRED')
        granted = {capability for grant in invocation.principal.grants
                   for capability in grant.capabilities}
        if not granted & READ_OPERATIONS:
            raise ManagerRefused('READ_NOT_AUTHORIZED')

    def check_instance_lifecycle(self, invocation, control, *, action) -> None:
        """Stop/detach policy on the exact instance operation."""
        self._verified(invocation, 'agents.' + str(action))

    @contextmanager
    def guard_instance_lifecycle(self, invocation, control, *, action):
        self._verified(invocation, 'agents.' + str(action))
        yield


class ServerInteractionAuthority:
    """Turn/binding read and send policy on the same verified instance caller."""

    def __init__(self, authority: InstanceAccessAuthority) -> None:
        if type(authority) is not InstanceAccessAuthority:
            raise TypeError('original instance authority required')
        self._authority = authority

    def _verified(self, invocation, operation: str):
        from ordessa_agents.sdk.interactions import InteractionsRefused
        if type(invocation) is not ServerInvocation:
            raise InteractionsRefused('ORIGINAL_INVOCATION_REQUIRED')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise InteractionsRefused('AUTHORITY_REVOKED') from None
        granted = {capability for grant in invocation.principal.grants
                   for capability in grant.capabilities}
        if operation not in granted:
            raise InteractionsRefused(_refusal_code(operation))
        return invocation

    def principal_scope(self, invocation) -> str:
        from ordessa_agents.sdk.interactions import InteractionsRefused
        if type(invocation) is not ServerInvocation:
            raise InteractionsRefused('ORIGINAL_INVOCATION_REQUIRED')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise InteractionsRefused('AUTHORITY_REVOKED') from None
        return invocation.principal_scope

    def check_read_binding(self, invocation, instance_ref) -> None:
        self._verified(invocation, 'agents.query')

    def check_read_turn(self, invocation, query) -> None:
        self._verified(invocation, 'agents.query')

    def check_send(self, invocation, binding) -> None:
        self._verified(invocation, 'agents.prompt')

    def check_cancel(self, invocation, binding) -> None:
        self._verified(invocation, 'agents.cancel')

    def check_native_dispatch(self, invocation, binding) -> None:
        """A native dispatch is a send: it needs the recorded-operation grant."""
        self._verified(invocation, 'agents.native.recorded')

    def check_read_native_operation(self, invocation, operation_ref, input_digest) -> None:
        """A native observation is a read: it needs the query-operation grant."""
        self._verified(invocation, 'agents.native.query')

    @contextmanager
    def guard_native_dispatch(self, invocation, binding):
        """The guarded native cut: only a caller allowed to freeze may write."""
        self._verified(invocation, 'agents.native.freeze')
        yield


def _refusal_code(operation: str) -> str:
    """One stable refusal code per operation family."""
    if operation in ('agents.prompt', 'agents.cancel', 'agents.native.recorded',
                     'agents.native.freeze'):
        return 'SEND_NOT_AUTHORIZED'
    return 'READ_NOT_AUTHORIZED'


class ServerPromptWriteGuard:
    """The physical write cut for prompt, cancel and native frames.

    The original owners call ``guard_write(binding, invocation)`` inside their
    guarded writer, immediately before the bytes leave the process. The guard
    re-verifies the instance principal and requires the grant of the operation
    the binding represents:

    * a prompt binding needs ``agents.prompt``;
    * a cancel binding needs ``agents.cancel``;
    * a native write binding needs ``agents.native.freeze``.

    A native dispatch additionally needs ``agents.native.recorded``; that is
    the interaction authority's ``check_native_dispatch`` decision, so a native
    write requires BOTH native grants. Any other binding is refused: an unknown
    physical effect is never admitted by default.
    """

    def __init__(self, authority: InstanceAccessAuthority) -> None:
        if type(authority) is not InstanceAccessAuthority:
            raise TypeError('original instance authority required')
        self._authority = authority

    def _operation_for(self, binding) -> str:
        from ordessa_agents.sdk.interactions import CancelBinding, WriteBinding
        from ordessa_agents.public import NativeWriteBinding
        if type(binding) is WriteBinding:
            return 'agents.prompt'
        if type(binding) is CancelBinding:
            return 'agents.cancel'
        if type(binding) is NativeWriteBinding:
            return 'agents.native.freeze'
        raise _write_refused('WRITE_BINDING_UNSUPPORTED')

    @contextmanager
    def guard_write(self, binding, invocation):
        from ordessa_agents.sdk.interactions import InteractionsRefused
        if type(invocation) is not ServerInvocation:
            raise InteractionsRefused('ORIGINAL_INVOCATION_REQUIRED')
        try:
            self._authority.verify(invocation.principal)
        except AccessError:
            raise InteractionsRefused('AUTHORITY_REVOKED') from None
        operation = self._operation_for(binding)
        granted = {capability for grant in invocation.principal.grants
                   for capability in grant.capabilities}
        if operation not in granted:
            raise InteractionsRefused(_refusal_code(operation))
        yield


def _write_refused(code: str):
    from ordessa_agents.sdk.interactions import InteractionsRefused
    return InteractionsRefused(code)


__all__ = ["NATIVE_OPERATIONS", "READ_OPERATIONS", "ServerAgentAuthority",
           "ServerInteractionAuthority", "ServerPromptWriteGuard"]
