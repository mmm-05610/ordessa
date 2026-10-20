"""Endpoint and agent-instance references: closed JSON, no authority, strict decode."""
import pytest

from ordessa_execution_agents.sdk.instances import AgentInstanceRef, EndpointRef, ReferenceError_

DIGEST = 'sha256:' + 'a' * 64


def test_endpoint_reference_is_closed_and_round_trips():
    ref = EndpointRef('issuer-1', 'endpoint-1', 'rev-1', DIGEST)
    value = ref.projection()
    assert value == {'schemaVersion': 'agent-endpoint/1', 'issuer': 'issuer-1',
                     'endpointId': 'endpoint-1', 'revision': 'rev-1',
                     'descriptorDigest': DIGEST}
    assert EndpointRef.decode(value) == ref
    # Unknown or missing fields are refused, never ignored.
    for broken in ({**value, 'extra': 1}, {k: v for k, v in value.items() if k != 'issuer'},
                   {**value, 'schemaVersion': 'agent-endpoint/2'}):
        with pytest.raises(ReferenceError_):
            EndpointRef.decode(broken)


def test_endpoint_reference_rejects_unbounded_or_non_digest_fields():
    for args in (('', 'endpoint-1', 'rev-1', DIGEST),
                 ('issuer-1', 'x' * 513, 'rev-1', DIGEST),
                 ('issuer-1', 'endpoint-1', 'rev-1', 'sha256:' + 'A' * 64),
                 ('issuer-1', 'endpoint-1', 'rev-1', 'a' * 64),
                 ('issuer-1', 'bad\x00id', 'rev-1', DIGEST)):
        with pytest.raises(ReferenceError_):
            EndpointRef(*args)


def test_agent_instance_reference_is_exactly_four_keys():
    ref = AgentInstanceRef('namespace-1', 'instance-1', DIGEST)
    assert ref.projection() == {'schemaVersion': 'agent-instance/1',
                                'namespace': 'namespace-1', 'instanceId': 'instance-1',
                                'bindingDigest': DIGEST}
    assert AgentInstanceRef.decode(ref.projection()) == ref
    # No grants, environment facts, paths or environment-use ids are admissible.
    for extra in ('grants', 'environment', 'path', 'environmentUseRef', 'useRef'):
        with pytest.raises(ReferenceError_):
            AgentInstanceRef.decode({**ref.projection(), extra: {}})
    with pytest.raises(ReferenceError_):
        AgentInstanceRef.decode({k: v for k, v in ref.projection().items() if k != 'namespace'})
    with pytest.raises(ReferenceError_):
        AgentInstanceRef.decode({**ref.projection(), 'schemaVersion': 'agent-instance/2'})


def test_agent_instance_digest_must_be_a_real_digest_not_a_placeholder():
    for digest in ('', 'pending', 'sha256:', 'sha256:' + 'a' * 63, 'sha256:' + 'g' * 64):
        with pytest.raises(ReferenceError_):
            AgentInstanceRef('namespace-1', 'instance-1', digest)
