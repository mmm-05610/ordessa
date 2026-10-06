"""AU002 wire lifecycle binding: stop/release/recover through agent_core_wire (C only).

Real temporary SQLite store, real Core/Node publication/Issuer with the
controlled provider and owner ports of the reviewed core coordinator fixture;
the product Server wire is composed over the same Environment with a controlled
lifecycle observation stub. No native process, no model. The wire projects the
original lifecycleOperation view, gates the three actions on the assembled
nodeLifecycle capability, and never grants retry permission from any effectful
failure.
"""
import pytest

from test_lifecycle import lifecycle as core_lifecycle
from ordessa_environment_api import RequestKey
from pacthold.agents.public import agent_services, encode_node_ref, AGENT_MANAGEMENT_CONTRACT_VERSION
from server_plugin_api import WireError


def wire_params(node_ref, request_id):
 return {'nodeRef': encode_node_ref(node_ref), 'preconditions': {}, 'requestId': request_id}


@pytest.fixture
def wire(core_lifecycle):
 from ordessa_server.agent_core_wire import agent_core_methods
 lifecycle, lifecycle_owner, provider, node_ref, node, env, store, stop_request, provider_ref, current = core_lifecycle
 # Same reviewed Environment, issuer and controlled receipt observer; the
 # public agent services compose the lifecycle authority once.
 services = agent_services(env, invocation_issuer=lifecycle._issuer, lifecycle_observation_port=lifecycle_owner)
 assert services.lifecycle.capabilities() == {'nodeLifecycle': True}
 handlers = {item.method_id: item.handler for item in agent_core_methods(
  lambda: env, contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
 return handlers, provider, node_ref, store, env


@pytest.fixture
def unwired_wire(core_lifecycle):
 from ordessa_server.agent_core_wire import agent_core_methods
 lifecycle, lifecycle_owner, provider, node_ref, node, env, store, stop_request, provider_ref, current = core_lifecycle
 services = agent_services(env, invocation_issuer=lifecycle._issuer)
 assert services.lifecycle.capabilities() == {'nodeLifecycle': False}
 handlers = {item.method_id: item.handler for item in agent_core_methods(
  lambda: env, contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
 return handlers, provider, node_ref, store


def test_assembled_wire_advertises_and_projects_lifecycle_operations(wire):
 handlers, provider, node_ref, store, env = wire
 capabilities = handlers['agents.capabilities']({})
 assert capabilities['supports']['nodeLifecycle'] is True
 assert {'agents.nodes.stop', 'agents.nodes.release', 'agents.nodes.recover'} <= set(capabilities['supportedMethods'])
 views = {}
 for action in ('stop', 'release', 'recover'):
  views[action] = handlers['agents.nodes.' + action](wire_params(node_ref, 'wire-' + action))
  operation = store.read_operation(RequestKey('env', 'principal', 'wire-' + action))
  assert views[action]['operationRef'] == operation.intent.operation_ref
  assert type(views[action]['revision']) is int
  assert views[action]['revision'] == operation.revision and views[action]['revision'] >= 1
  assert views[action]['status'] == 'running' and views[action]['action'] == action
  assert views[action]['node'] is None
  assert store.read_operation_step(RequestKey('env', 'principal', 'wire-' + action), action).outcome == 'concluded'
 assert [call for call in provider.lifecycle_calls if type(call) is str] == ['stop', 'release', 'recover']
 # The same original request replays the sole operation; the wire never
 # re-dispatches the claimed step.
 assert handlers['agents.nodes.stop'](wire_params(node_ref, 'wire-stop')) == views['stop']
 assert provider.lifecycle_calls.count('stop') == 1


@pytest.mark.parametrize('bad', ['string', 5, ('tuple',)])
def test_wire_preconditions_shape_refuses_before_reservation(wire, bad):
 handlers, provider, node_ref, store, env = wire
 with pytest.raises(WireError) as error:
  handlers['agents.nodes.stop'](dict(wire_params(node_ref, 'shaped-' + type(bad).__name__.lower()),
                                     preconditions=bad))
 assert error.value.family == 'INVALID_REQUEST'
 assert error.value.details['retryable'] is False
 assert store.read_operation(RequestKey('env', 'principal', 'shaped-' + type(bad).__name__.lower())) is None
 assert [call for call in provider.lifecycle_calls if type(call) is str] == []


@pytest.mark.parametrize('action', ['stop', 'release', 'recover'])
def test_unwired_lifecycle_wire_call_stays_unsupported_and_unreserved(unwired_wire, action):
 handlers, provider, node_ref, store = unwired_wire
 with pytest.raises(WireError) as error:
  handlers['agents.nodes.' + action](wire_params(node_ref, 'unwired-' + action))
 assert error.value.family == 'CAPABILITY_UNSUPPORTED'
 assert error.value.details['retryable'] is False
 assert handlers['agents.capabilities']({})['supports']['nodeLifecycle'] is False
 assert store.read_operation(RequestKey('env', 'principal', 'unwired-' + action)) is None
 assert provider.lifecycle_calls == []


def test_wire_effectful_unknown_exception_grants_no_retry(wire, monkeypatch):
 handlers, provider, node_ref, store, env = wire
 original = env._fingerprint_port.fingerprint

 def crash(*args, **kwargs):
  raise RuntimeError('controlled-original-failure')

 monkeypatch.setattr(env._fingerprint_port, 'fingerprint', crash)
 with pytest.raises(WireError) as error:
  handlers['agents.nodes.stop'](wire_params(node_ref, 'unknown-wire-stop'))
 assert error.value.family == 'OUTCOME_UNKNOWN'
 assert error.value.details['retryable'] is False
 assert store.read_operation(RequestKey('env', 'principal', 'unknown-wire-stop')) is None
 monkeypatch.setattr(env._fingerprint_port, 'fingerprint', original)
 view = handlers['agents.nodes.stop'](wire_params(node_ref, 'unknown-wire-stop'))
 assert view['action'] == 'stop' and view['status'] == 'running'
 assert store.read_operation_step(RequestKey('env', 'principal', 'unknown-wire-stop'), 'stop').outcome == 'concluded'
