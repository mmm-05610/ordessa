"""Bound endpoint: six independent members, bounded event pages, no authority leakage."""
import pytest

from ordessa_execution_agents.sdk.endpoint import (
    BoundEndpoint, EndpointValueError, ProcessObservation, ProtocolEvent,
    ProtocolEventPage, SendObservation,
)
from ordessa_execution_agents.sdk.instances import EndpointRef

DIGEST = 'sha256:' + 'a' * 64


def _ref():
    return EndpointRef('issuer-1', 'endpoint-1', 'rev-1', DIGEST)


def test_members_are_independent_and_missing_ones_are_not_denials():
    launcher = object()
    observe = object()
    endpoint = BoundEndpoint(_ref(), {'platform': 'linux'}, launcher=launcher, observe=observe)
    assert endpoint.members() == ('launcher', 'observe')
    assert endpoint.communicate is None and endpoint.terminate is None
    # Holding launcher grants nothing else; each member stays separately absent.
    assert endpoint.launcher is launcher and endpoint.observe is observe


def test_descriptor_carries_safe_facts_only():
    endpoint = BoundEndpoint(_ref(), {'platform': 'linux', 'protocol': 'acp'})
    assert endpoint.descriptor['protocol'] == 'acp'
    with pytest.raises(TypeError):
        endpoint.descriptor['platform'] = 'darwin'
    for forbidden in ('environmentRef', 'useRef', 'resourceRef', 'grant', 'authority'):
        with pytest.raises(EndpointValueError):
            BoundEndpoint(_ref(), {forbidden: 'x'})
    with pytest.raises(EndpointValueError):
        BoundEndpoint(_ref(), {1: 'x'})
    with pytest.raises(EndpointValueError):
        BoundEndpoint({'not': 'an EndpointRef'})


def test_send_observation_distinguishes_the_three_delivery_states():
    for delivery in ('not_sent', 'possibly_sent', 'confirmed'):
        assert SendObservation('accepted', 0, delivery).delivery == delivery
    with pytest.raises(EndpointValueError):
        SendObservation('accepted', 0, 'sent')
    with pytest.raises(EndpointValueError):
        SendObservation('accepted', True, 'not_sent')
    with pytest.raises(EndpointValueError):
        SendObservation('maybe', 0, 'not_sent')


def test_process_observation_requires_a_state_and_never_a_raw_pid():
    observation = ProcessObservation('running', '2026-10-19T00:00:00.000000Z',
                                     native_identity_digest=DIGEST, evidence_refs=('e-1',))
    assert observation.state == 'running'
    with pytest.raises(EndpointValueError):
        ProcessObservation('alive', 'now')
    with pytest.raises(EndpointValueError):
        ProcessObservation('exited', 'now', exit_code=True)
    with pytest.raises(EndpointValueError):
        ProcessObservation('running', '')


def test_event_page_is_bounded_and_a_cursor_is_required_to_continue():
    event = ProtocolEvent('assistant', DIGEST, b'{"text":"hi"}')
    page = ProtocolEventPage((event,), cursor='c-2', has_more=True)
    assert page.events[0].kind == 'assistant'
    assert ProtocolEventPage((event,)).has_more is False
    with pytest.raises(EndpointValueError, match='cursor'):
        ProtocolEventPage((event,), has_more=True)
    with pytest.raises(EndpointValueError):
        ProtocolEventPage(tuple(event for _ in range(257)))
    with pytest.raises(EndpointValueError):
        ProtocolEventPage(('not-an-event',))
