"""C: published SQLite facts through public wire; no native owner invocation."""
import json
import pytest

from test_node_publication import setup, conclude
from pacthold.agents.public import encode_node_ref, wire_contract
from pacthold.public import Environment
from ordessa_environment_api.operations import safe_json
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError


def methods(parts):
    return {item.method_id: item.handler for item in agent_core_methods(
        lambda: parts[2], contract_version='agent-assembly/3')}


def publish(parts):
    revision, usages = conclude(parts)
    return parts[5].publish(parts[6], 'digest', revision, usages)


def test_public_read_methods_observe_exact_publication_without_issuer_or_native(setup):
    expected = json.loads(safe_json(publish(setup)))
    before = tuple(setup[1]._conn.iterdump())
    calls = methods(setup)
    capabilities = calls['agents.capabilities']({})
    assert capabilities['supports']['nodePreparation'] is False
    assert {'agents.nodes.list', 'agents.nodes.read'} <= set(capabilities['supportedMethods'])
    assert calls['agents.nodes.list']({}) == {'nodes': [expected]}
    assert calls['agents.nodes.read']({'nodeRef': encode_node_ref(setup[7])}) == {'node': expected}
    assert tuple(setup[1]._conn.iterdump()) == before
    assert 'ready' not in expected and 'state' not in expected
    # Response mutation cannot modify the authoritative durable record.
    expected['binding']['harnessUnitRef']['ref'] = 'mutated-client-copy'
    assert calls['agents.nodes.read']({'nodeRef': encode_node_ref(setup[7])})['node']['binding']['harnessUnitRef']['ref'] == 'actual-unit'


def test_missing_publication_remains_null_and_empty_not_a_fake_node(setup):
    calls = methods(setup)
    assert calls['agents.nodes.list']({}) == {'nodes': []}
    assert calls['agents.nodes.read']({'nodeRef': encode_node_ref(setup[7])}) == {'node': None}


@pytest.mark.parametrize('action', ['list', 'read'])
def test_read_permission_refused_without_observation_or_write(setup, action):
    publish(setup)
    before = tuple(setup[1]._conn.iterdump())
    setup[3].allowed = False
    with pytest.raises(WireError) as error:
        methods(setup)['agents.nodes.' + action]({} if action == 'list' else {'nodeRef': encode_node_ref(setup[7])})
    assert error.value.family == 'FORBIDDEN'
    assert tuple(setup[1]._conn.iterdump()) == before


@pytest.mark.parametrize('change, family', [
    ({'generation': True}, 'INVALID_REQUEST'),
    ({'generation': 1.0}, 'INVALID_REQUEST'),
    ({'environmentNamespace': 'foreign'}, 'CONFLICT_REQUEST'),
    ({'principalScope': 'invented'}, 'INVALID_REQUEST'),
])
def test_invalid_or_foreign_node_identity_refused(setup, change, family):
    publish(setup)
    ref = encode_node_ref(setup[7]); ref.update(change)
    with pytest.raises(WireError) as error:
        methods(setup)['agents.nodes.read']({'nodeRef': ref})
    assert error.value.family == family


def test_core_owns_read_result_wrappers_and_missing_semantics():
    results = wire_contract('agent-assembly/3')['results']
    assert results['nodesList'] == {'required': ['nodes'], 'additionalProperties': False}
    assert results['nodeRead'] == {'required': ['node'], 'additionalProperties': False, 'missing': None}


def test_read_published_history_with_retired_provider_does_not_reactivate(setup):
    expected = json.loads(safe_json(publish(setup)))
    setup[2].retire_activation(setup[9].activation)
    before = tuple(setup[1]._conn.iterdump())
    assert methods(setup)['agents.nodes.read']({'nodeRef': encode_node_ref(setup[7])}) == {'node': expected}
    assert tuple(setup[1]._conn.iterdump()) == before


@pytest.mark.parametrize('action', ['list', 'read'])
def test_absent_same_store_capability_is_refused_not_empty_success(setup, action):
    setup[2]._store = object()
    with pytest.raises(WireError) as error:
        methods(setup)['agents.nodes.' + action]({} if action == 'list' else {'nodeRef': encode_node_ref(setup[7])})
    assert error.value.family == 'CAPABILITY_UNSUPPORTED'


def test_list_checks_node_permission_after_wildcard_permission(setup):
    publish(setup)
    before = tuple(setup[1]._conn.iterdump())
    setup[3].admit_object_access = lambda principal, target, purpose: target.endswith(':*')
    with pytest.raises(WireError) as error:
        methods(setup)['agents.nodes.list']({})
    assert error.value.family == 'FORBIDDEN'
    assert tuple(setup[1]._conn.iterdump()) == before


def test_new_environment_reads_durable_publication_without_runtime_registry(setup):
    expected = json.loads(safe_json(publish(setup)))
    cold = Environment('env', store=setup[1], policy=setup[3], principal_scope='principal')
    handlers = {item.method_id: item.handler for item in agent_core_methods(
        lambda: cold, contract_version='agent-assembly/3')}
    before = tuple(setup[1]._conn.iterdump())
    assert handlers['agents.nodes.list']({}) == {'nodes': [expected]}
    assert handlers['agents.nodes.read']({'nodeRef': encode_node_ref(setup[7])}) == {'node': expected}
    assert handlers['agents.providers.list']({}) == {'providers': []}
    assert tuple(setup[1]._conn.iterdump()) == before
