"""The Server's Agent lifecycle/interaction authority is the instance identity.

These are policy tests for the composition adapters: one verified caller, exact
grants, immediate revocation. No owner is launched and no model is called.
"""
from __future__ import annotations

import pytest

from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.agent_authority import (
    ServerAgentAuthority,
    ServerInteractionAuthority,
    ServerPromptWriteGuard,
)
from ordessa_server.composition.invocation import ServerInvocation, server_invocation


class _Stub:
    """Any object: the adapters never inspect the owner's arguments."""


def _authority(operations, *, token='instance-token'):
    return InstanceAccessAuthority(
        lambda: token,
        principal_id='instance',
        grants=(AccessGrant(Scope('ordessa', 'local'), tuple(operations)),),
        legacy_principal=None,
    )


def _invocation(authority) -> ServerInvocation:
    return server_invocation(authority.authenticate('Bearer instance-token'))


def test_scope_and_start_require_the_exact_grant():
    authority = _authority(('agents.start', 'agents.get'))
    invocation = _invocation(authority)
    lifecycle = ServerAgentAuthority(authority)
    assert lifecycle.principal_scope(invocation) == 'principal:instance'
    lifecycle.check_start(invocation, _Stub(), _Stub())
    lifecycle.check_lifecycle_write(invocation, _Stub())
    with lifecycle.guard_instance_lifecycle(invocation, _Stub(), action='start'):
        pass  # granted action is allowed through the guard
    with pytest.raises(Exception):
        with lifecycle.guard_instance_lifecycle(invocation, _Stub(), action='stop'):
            pass  # 'agents.stop' is not granted


def test_ungranted_operation_is_refused_with_a_stable_code():
    authority = _authority(('agents.get',))
    lifecycle = ServerAgentAuthority(authority)
    with pytest.raises(Exception) as raised:
        lifecycle.check_start(_invocation(authority), _Stub(), _Stub())
    assert 'START_NOT_AUTHORIZED' in str(raised.value)

    interactions = ServerInteractionAuthority(authority)
    with pytest.raises(Exception) as raised:
        interactions.check_send(_invocation(authority), _Stub())
    assert 'SEND_NOT_AUTHORIZED' in str(raised.value)


def test_send_requires_agents_prompt_and_read_requires_a_read_operation():
    prompt = _authority(('agents.prompt',))
    interactions = ServerInteractionAuthority(prompt)
    interactions.check_send(_invocation(prompt), _Stub())
    with pytest.raises(Exception):
        interactions.check_read_turn(_invocation(prompt), _Stub())

    reader = _authority(('agents.query',))
    ServerInteractionAuthority(reader).check_read_turn(_invocation(reader), _Stub())


def test_revocation_applies_immediately_to_every_check():
    authority = _authority(('agents.start', 'agents.prompt'))
    lifecycle = ServerAgentAuthority(authority)
    interactions = ServerInteractionAuthority(authority)
    invocation = _invocation(authority)
    lifecycle.check_start(invocation, _Stub(), _Stub())
    interactions.check_send(invocation, _Stub())
    authority.revoke()
    for call in (lambda: lifecycle.check_start(invocation, _Stub(), _Stub()),
                 lambda: lifecycle.principal_scope(invocation),
                 lambda: interactions.check_send(invocation, _Stub()),
                 lambda: interactions.principal_scope(invocation)):
        with pytest.raises(Exception):
            call()


def test_a_foreign_invocation_object_is_refused():
    authority = _authority(('agents.start', 'agents.prompt'))
    lifecycle = ServerAgentAuthority(authority)
    with pytest.raises(Exception):
        lifecycle.check_start(object(), _Stub(), _Stub())


def test_instance_lifecycle_policy_names_the_exact_instance_operation():
    authority = _authority(('agents.stop', 'agents.detach'))
    lifecycle = ServerAgentAuthority(authority)
    invocation = _invocation(authority)
    lifecycle.check_instance_lifecycle(invocation, _Stub(), action='stop')
    lifecycle.check_instance_lifecycle(invocation, _Stub(), action='detach')
    with pytest.raises(Exception):
        lifecycle.check_instance_lifecycle(invocation, _Stub(), action='start')


def test_preparation_uses_the_same_grant_as_the_lifecycle():
    authority = _authority(('agents.start',))
    lifecycle = ServerAgentAuthority(authority)
    invocation = _invocation(authority)
    lifecycle.allow('agents.start', invocation)
    without = _authority(('agents.get',))
    with pytest.raises(Exception):
        ServerAgentAuthority(without).allow('agents.start', _invocation(without))


def _native_binding(kind='request'):
    """A real closed dispatch binding; the authority inspects its kind."""
    from ordessa_agents.sdk.instances import AgentInstanceRef, EndpointRef
    from ordessa_agents.sdk.native_runtime import (NativeDispatchBinding,
                                                   native_dispatch_request_id)
    instance_ref = AgentInstanceRef('server', 'instance-1', 'sha256:' + 'a' * 64)
    endpoint = EndpointRef('issuer', 'endpoint', '1', 'sha256:' + 'd' * 64)
    frame = 'sha256:' + 'c' * 64
    return NativeDispatchBinding(
        instance_ref, endpoint, kind, 'sha256:' + 'e' * 64, 'codex-app-server/1',
        'session-1', 'sha256:' + 'b' * 64, frame,
        native_dispatch_request_id(endpoint, frame), 'native/' + 'f' * 32)


def test_native_policy_names_the_exact_native_operation():
    request = _native_binding('request')
    authority = _authority(('agents.native.request', 'agents.native.query'))
    interactions = ServerInteractionAuthority(authority)
    invocation = _invocation(authority)
    interactions.check_native_dispatch(invocation, request)
    interactions.check_read_native_operation(invocation, _Stub(), 'sha256:' + '0' * 64)
    # A notify frame is a different write and needs its own grant.
    with pytest.raises(Exception):
        interactions.check_native_dispatch(invocation, _native_binding('notify'))
    with pytest.raises(Exception):
        interactions.check_read_native_events(invocation, _Stub())
    notify = _authority(('agents.native.notify',))
    ServerInteractionAuthority(notify).check_native_dispatch(
        _invocation(notify), _native_binding('notify'))
    # The guarded cut repeats the same exact grant check.
    with interactions.guard_native_dispatch(invocation, request):
        pass
    with pytest.raises(Exception):
        with interactions.guard_native_dispatch(invocation, _native_binding('notify')):
            pass


def test_native_reads_and_reply_have_their_own_grants():
    authority = _authority(('agents.native.describe', 'agents.native.events'))
    interactions = ServerInteractionAuthority(authority)
    invocation = _invocation(authority)
    interactions.check_native_describe(invocation, _Stub())
    interactions.check_read_native_events(invocation, _Stub())
    with pytest.raises(Exception):
        interactions.check_native_respond(invocation, _Stub())
    reply = _authority(('agents.native.respond',))
    ServerInteractionAuthority(reply).check_native_respond(_invocation(reply), _Stub())


def test_the_write_guard_admits_only_the_granted_physical_write():
    from ordessa_agents.sdk.instances import AgentInstanceRef
    from ordessa_agents.sdk.interactions import TurnRef, WriteBinding

    instance_ref = AgentInstanceRef('server', 'instance-1', 'sha256:' + 'a' * 64)
    prompt = WriteBinding(TurnRef(instance_ref, 'turn-1'), 'session-1',
                           'agent-operation/1', 'request-1', None,
                           'sha256:' + 'b' * 64, 'sha256:' + 'c' * 64)
    authority = _authority(('agents.prompt',))
    guard = ServerPromptWriteGuard(authority)
    invocation = _invocation(authority)
    with guard.guard_write(prompt, invocation):
        pass  # the granted prompt write is admitted through the cut
    # A native request frame needs the native request grant, not the prompt one.
    with pytest.raises(Exception):
        with guard.guard_write(_native_binding('request'), invocation):
            pass
    native = _authority(('agents.native.request',))
    with ServerPromptWriteGuard(native).guard_write(_native_binding('request'),
                                                    _invocation(native)):
        pass


def test_the_write_guard_refuses_an_ungranted_or_unknown_binding():
    from ordessa_agents.sdk.instances import AgentInstanceRef
    from ordessa_agents.sdk.interactions import CancelBinding

    instance_ref = AgentInstanceRef('server', 'instance-1', 'sha256:' + 'a' * 64)
    cancel = CancelBinding(instance_ref, 'session-1', 'agent-operation/1',
                           'request-1', 'sha256:' + 'c' * 64)
    authority = _authority(('agents.prompt',))
    guard = ServerPromptWriteGuard(authority)
    invocation = _invocation(authority)
    # A cancel binding needs its own grant, not the prompt grant.
    with pytest.raises(Exception):
        with guard.guard_write(cancel, invocation):
            pass
    # An unknown binding is never admitted by default.
    with pytest.raises(Exception):
        with guard.guard_write(_Stub(), invocation):
            pass
    # A foreign invocation object is refused before the binding is inspected.
    with pytest.raises(Exception):
        with guard.guard_write(_Stub(), object()):
            pass


def test_the_write_guard_revocation_applies_at_the_cut():
    from ordessa_agents.sdk.instances import AgentInstanceRef
    from ordessa_agents.sdk.interactions import TurnRef, WriteBinding

    instance_ref = AgentInstanceRef('server', 'instance-1', 'sha256:' + 'a' * 64)
    prompt = WriteBinding(TurnRef(instance_ref, 'turn-1'), 'session-1',
                           'agent-operation/1', 'request-1', None,
                           'sha256:' + 'b' * 64, 'sha256:' + 'c' * 64)
    authority = _authority(('agents.prompt',))
    guard = ServerPromptWriteGuard(authority)
    invocation = _invocation(authority)
    authority.revoke()
    with pytest.raises(Exception):
        with guard.guard_write(prompt, invocation):
            pass
