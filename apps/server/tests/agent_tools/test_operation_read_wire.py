"""D-route: operation-read wire binding on the frozen v3 contract.

The D network contract (method name / capability advertisement / schema
version) is frozen in operation-read-wire-binding-v1.md: `agents.operations.read`
is a /3 pure addition, constant-answered, and mapped to typed wire families.
These tests prove presence on the /3 surface and absence from /1, the sealed
six-field wire projection with zero owner/claim/recovery effects, typed
NOT_FOUND hides for cross-principal and dual-ACL reads, CONFLICT_REQUEST for
illegal ref shapes, and the remaining uncontracted operation/resolve/compile
families still occupying nothing.
"""
from ordessa_execution_agents.harness.definitions import HarnessActivationRef
from ordessa_units.errors import UnitAdmissionRefused
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.errors import UnitIdentityMismatch

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot
import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'packages/execution/agents/tests/agent_unit_model'))
from agent_tools_fixtures.management import setup, node_fixture, explicit_capabilities  # noqa: F401

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.public import (
    AgentOperations, OperationNotFound, unit_services, encode_node_ref, wire_contract,
    wire_schema_digest,
)
from pacthold.environment import Environment
from ordessa_system_access_bindings import agent_core_methods
from server_plugin_api import WireError
from ordessa_system_access_client import ClientError, Service, WireClient, core_schema


NODE_REF = {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1}
PROFILE_REF = {'environmentNamespace': 'env', 'profileId': 'profile-base',
               'manifestRevision': 1, 'contentDigest': 'sha256:' + 'b' * 64}
READ_METHOD = 'agents.operations.read'
UNCONTRACTED_METHODS = ('agents.operations.list',
                        'agents.nodes.resolveMaterial', 'agents.materials.resolve',
                        'agents.nodes.compile')
WHITELIST = frozenset({'operationRef', 'kind', 'revision', 'status', 'nodeRef', 'hasResult'})


class ExplodingResolver:
    """Fails the test if a rejected DTO ever reaches service composition."""

    def __call__(self):
        raise AssertionError('services must not be consulted for a rejected DTO')


def handlers(resolver, version='agent-assembly/3'):
    return {item.method_id: item.handler
            for item in agent_core_methods(resolver, contract_version=version)}


def dump(parts):
    return tuple(parts[0]._conn.iterdump())


def counters(parts):
    return (parts[7]['calls'], parts[7]['queryCalls'])


def uncontracted_names(methods):
    return sorted(name for name in methods
                  if (name.startswith('agents.operations') and name != READ_METHOD)
                  or any(token in name for token in ('resolve', 'compile')))


def foreign_operations(parts):
    rival = Environment('env', store=parts[0], policy=parts[2], principal_scope='rival', resource_extension_snapshot=_test_resource_snapshot)
    return AgentOperations(rival, unit_services(rival).nodes)


def test_operation_read_surface_is_contracted_advertised_and_v3_only(setup):
    contract = wire_contract('agent-assembly/3')
    # §6 gate 1: present in the /3 contract with the frozen binding shape…
    assert READ_METHOD in contract['methods']
    definition = contract['methods'][READ_METHOD]
    assert definition['action'] == 'operationRead'
    assert definition['required'] == ['operationRef'] and definition['optional'] == []
    assert definition['effectful'] is False
    metadata = contract['results']['operationMetadata']
    assert metadata['required'] == ['operationRef', 'kind', 'revision', 'status', 'nodeRef', 'hasResult']
    assert metadata['additionalProperties'] is False
    assert metadata['statuses'] == ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']
    assert uncontracted_names(contract['methods']) == []
    # …absent from /1, advertised on /3 as a constant, with no new supports key.
    assert READ_METHOD not in wire_contract('agent-assembly/1')['methods']
    descriptors = agent_core_methods(lambda: setup[1], contract_version='agent-assembly/3')
    assert READ_METHOD in {item.method_id for item in descriptors}
    capabilities = {item.method_id: item.handler for item in descriptors}['agents.capabilities']({})
    assert READ_METHOD in capabilities['supportedMethods']
    assert uncontracted_names(capabilities['supportedMethods']) == []
    assert set(capabilities['supports']) == {
        'profileCatalog', 'nodes', 'managedInput',
        'configurationManagement', 'nodePreparation', 'nodeLifecycle'}
    assert 'agents.capabilities' in capabilities['supportedMethods']
    assert set(capabilities['supportedMethods']) <= set(contract['methods'])
    assert capabilities['schemaDigest'] is not None
    # Constant advertisement even without any management capability key.
    assert capabilities['supports']['configurationManagement'] is False
    # …and the shipped client mirror carries the same method and digest.
    mirror = core_schema('agent-assembly/3')
    assert mirror['schemaDigest'] == wire_schema_digest('agent-assembly/3')
    assert mirror['schema']['methods'][READ_METHOD] == definition
    assert READ_METHOD not in core_schema('agent-assembly/1')['schema']['methods']


def test_operation_read_wire_answers_sealed_six_fields_with_zero_effect(setup):
    services = unit_services(setup[1], invocation_issuer=setup[10])
    registry = handlers(lambda: setup[1])
    applied = setup[3].apply(setup[5], setup[4], setup[6])
    assert applied.status == 'published'
    operation_ref = applied.intent.operation_ref
    node_ref = encode_node_ref(setup[4])
    before, counts = dump(setup), counters(setup)
    view = registry[READ_METHOD]({'operationRef': operation_ref})
    # §6 gate 2: exact six-field whitelist over the wire, no body/evidence/step.
    assert set(view) == WHITELIST
    assert view['operationRef'] == operation_ref and view['status'] == 'published'
    assert view['kind'] == applied.intent.kind
    assert view['nodeRef'] == node_ref and view['hasResult'] is True
    assert not any(key in view for key in
                   ('evidence', 'step', 'steps', 'intent', 'context', 'body', 'configurationResult'))
    # One query: zero owner invocation, zero claim, zero recovery writes.
    assert dump(setup) == before
    assert counters(setup) == counts
    # The /1 capabilities never carry the management methods member at all.
    v1 = {item.method_id: item.handler
          for item in agent_core_methods(lambda: setup[1], contract_version='agent-assembly/1')}
    v1_capabilities = v1['agents.capabilities']({})
    assert 'supportedMethods' not in v1_capabilities
    assert READ_METHOD not in v1_capabilities['schema']['methods']
    assert dump(setup) == before
    assert counters(setup) == counts


def test_operation_read_wire_hides_foreign_and_acl_denied_as_not_found(setup):
    registry = handlers(lambda: setup[1])
    applied = setup[3].apply(setup[5], setup[4], setup[6])
    operation_ref = applied.intent.operation_ref
    before, counts = dump(setup), counters(setup)
    # §6 gate 2: a foreign principal sees the identical typed absence.
    rival_env = Environment('env', store=setup[0], policy=setup[2], principal_scope='rival', resource_extension_snapshot=_test_resource_snapshot)
    foreign = handlers(lambda: rival_env)
    with pytest.raises(WireError) as absent:
        foreign[READ_METHOD]({'operationRef': 'missing-operation'})
    with pytest.raises(WireError) as rival:
        foreign[READ_METHOD]({'operationRef': operation_ref})
    assert absent.value.family == rival.value.family == 'NOT_FOUND'
    assert absent.value.details.get('retryable') is False
    # Same principal, missing operation: typed NOT_FOUND, never an empty success.
    with pytest.raises(WireError) as missing:
        registry[READ_METHOD]({'operationRef': 'missing-operation'})
    assert missing.value.family == 'NOT_FOUND'
    # Dual-read ACL: the operation reads but its target Node is hidden — the
    # association disappears exactly like an absent operation.
    original_admit = setup[2].admit_object_access
    try:
        setup[2].admit_object_access = (
            lambda principal, target, purpose:
            ':agents.node:' not in target and original_admit(principal, target, purpose))
        with pytest.raises(WireError) as hidden:
            registry[READ_METHOD]({'operationRef': operation_ref})
    finally:
        setup[2].admit_object_access = original_admit
    assert hidden.value.family == 'NOT_FOUND'
    assert dump(setup) == before
    assert counters(setup) == counts


def test_operation_read_wire_invalid_refs_and_dto_stay_typed(setup):
    registry = handlers(lambda: setup[1])
    before, counts = dump(setup), counters(setup)
    # §2: an illegal ref shape reaches the core and maps to CONFLICT_REQUEST.
    for bad in ('', ' leading', 'trailing ', 'line\nbreak', 'x' * 257, 123, None):
        with pytest.raises(WireError) as caught:
            registry[READ_METHOD]({'operationRef': bad})
        assert caught.value.family == 'CONFLICT_REQUEST'
        assert caught.value.details.get('retryable') is False
    # Shape refusals before service consultation: resolver must never run.
    exploding = {item.method_id: item.handler
                 for item in agent_core_methods(ExplodingResolver(), contract_version='agent-assembly/3')}
    for params in ({}, {'operationRef': 'operation-x', 'unexpected': 1}):
        with pytest.raises(WireError) as caught:
            exploding[READ_METHOD](params)
        assert caught.value.family == 'INVALID_REQUEST'
        assert caught.value.details.get('retryable') is False
    # A store without the same-domain guarantee stays typed unsupported.
    stranger = Environment('env-stranger', store=object(), policy=setup[2], principal_scope='principal', resource_extension_snapshot=_test_resource_snapshot)
    with pytest.raises(WireError) as stranded:
        handlers(lambda: stranger)[READ_METHOD]({'operationRef': 'operation-x'})
    assert stranded.value.family == 'CAPABILITY_UNSUPPORTED'
    assert dump(setup) == before
    assert counters(setup) == counts


@pytest.mark.parametrize('method', UNCONTRACTED_METHODS)
def test_unknown_operation_read_method_refused_before_service_or_http(method):
    registry = {item.method_id for item in agent_core_methods(ExplodingResolver(), contract_version='agent-assembly/3')}
    assert method not in registry
    assert method not in wire_contract('agent-assembly/1')['methods']
    assert method not in wire_contract('agent-assembly/3')['methods']
    # Client transport: refused before any HTTP attempt. Port 1 has no
    # listener, so a network attempt would surface SERVICE_UNAVAILABLE instead.
    client = WireClient(Service('local', 'http://127.0.0.1:1', 'fixture-token'), timeout=1)
    client.schema_version = 'agent-assembly/3'
    with pytest.raises(ClientError) as caught:
        client.core_call(method, {'operationRef': 'configuration-x'}, 'request-1')
    assert caught.value.code == 'PARAMETER_INVALID' and caught.value.exit_code == 2


def test_client_refuses_method_absent_from_advertised_capabilities():
    client = WireClient(Service('local', 'http://127.0.0.1:1', 'fixture-token'), timeout=1)
    client.schema_version = 'agent-assembly/3'
    client.supported_methods = frozenset({'agents.capabilities'})
    with pytest.raises(ClientError) as caught:
        client.core_call('agents.nodes.read', {'nodeRef': {}}, 'request-2')
    assert caught.value.code == 'CORE_CAPABILITY_UNAVAILABLE' and caught.value.exit_code == 4


INVALID_DTO = [
    ('agents.capabilities', {'unexpected': True}),
    ('agents.capabilities', 'not-an-object'),
    ('agents.capabilities', None),
    ('agents.nodes.read', {}),
    ('agents.nodes.read', {'nodeRef': 'not-a-ref'}),
    ('agents.nodes.read', {'nodeRef': NODE_REF, 'unexpected': 1}),
    ('agents.nodes.read', {'nodeRef': dict(NODE_REF, generation=True)}),
    ('agents.nodes.list', {'nodes': []}),
    ('agents.nodes.queryPreparation', {}),
    ('agents.nodes.queryPreparation', {'requestId': ''}),
    ('agents.nodes.queryPreparation', {'requestId': 1}),
    ('agents.nodes.queryPreparation', {'requestId': True}),
    ('agents.nodes.queryPreparation', {'requestId': ['x']}),
    ('agents.nodes.queryPreparation', {'requestId': 'bad\nrequest'}),
    ('agents.nodes.configuration.query', {'nodeRef': NODE_REF}),
    ('agents.providers.describe', {}),
    ('agents.providers.describe', {'definitionRef': 'not-an-object'}),
    ('agents.providers.describe', {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture'}}),
    ('agents.providers.describe', {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture', 'revision': '1', 'unexpected': True}}),
    ('agents.nodes.stop', {'nodeRef': NODE_REF, 'requestId': 'request-1'}),
    ('agents.nodes.prepare', {'requestId': 'request-1', 'profileRef': PROFILE_REF}),
    ('agents.nodes.applyProfile', {'nodeRef': NODE_REF, 'requestId': 'request-1',
                                    'profileRef': PROFILE_REF, 'baseProfileRef': PROFILE_REF,
                                    'expectedConfigurationRevision': 'native-1',
                                    'applicationPolicy': {'allowDeferred': False, 'allowRestart': 1}}),
]


@pytest.mark.parametrize('method,params', INVALID_DTO)
def test_invalid_dto_parameters_refused_before_service_consultation(setup, method, params):
    registry = handlers(ExplodingResolver())
    with pytest.raises(WireError) as caught:
        registry[method](params)
    assert caught.value.family == 'INVALID_REQUEST'
    assert caught.value.details.get('retryable') is False
    # The Environment was never composed into Agent services for this refusal.
    assert not hasattr(setup[1], '_agent_services')


REAL_INVALID_DTO = [
    # Trailing control characters are caught by the pre-service RequestKey check.
    ('agents.nodes.queryPreparation', {'requestId': 'bad\nrequest'}, 'INVALID_REQUEST'),
    # An uncomposed issuer refuses before any operationRef validation: typed
    # CAPABILITY_UNSUPPORTED, never an empty success and never a leak.
    ('agents.nodes.configuration.query', {'nodeRef': NODE_REF, 'operationRef': ''}, 'CAPABILITY_UNSUPPORTED'),
    ('agents.nodes.configuration.query', {'nodeRef': NODE_REF, 'operationRef': 123}, 'CAPABILITY_UNSUPPORTED'),
    # A foreign-node target is refused as a request identity conflict.
    ('agents.nodes.configuration.query', {'nodeRef': dict(NODE_REF, environmentNamespace='foreign'),
                                          'operationRef': 'operation-x'}, 'CONFLICT_REQUEST'),
]


@pytest.mark.parametrize('method,params,family', REAL_INVALID_DTO)
def test_invalid_dto_with_real_services_refuses_without_state_change(setup, method, params, family):
    registry = handlers(lambda: setup[1])
    before, counts = dump(setup), counters(setup)
    with pytest.raises(WireError) as caught:
        registry[method](params)
    assert caught.value.family == family
    assert caught.value.details.get('retryable') is False
    assert dump(setup) == before
    assert counters(setup) == counts


def test_unadvertised_capability_refused_not_empty_success(setup):
    registry = handlers(lambda: setup[1])
    capabilities = registry['agents.capabilities']({})
    assert capabilities['supports']['nodePreparation'] is False
    assert capabilities['supports']['configurationManagement'] is False
    unadvertised = {'agents.nodes.prepare', 'agents.nodes.queryPreparation',
                    'agents.nodes.applyProfile', 'agents.nodes.stop',
                    'agents.nodes.release', 'agents.nodes.recover'}
    assert unadvertised.isdisjoint(capabilities['supportedMethods'])
    before, counts = dump(setup), counters(setup)
    node_ref = encode_node_ref(setup[4])
    refusals = [
        ('agents.nodes.applyProfile', {'nodeRef': node_ref, 'requestId': 'request-1',
                                        'profileRef': PROFILE_REF, 'baseProfileRef': PROFILE_REF,
                                        'expectedConfigurationRevision': 'native-1',
                                        'applicationPolicy': {'allowDeferred': False, 'allowRestart': False}}),
        ('agents.nodes.prepare', {'requestId': 'request-1', 'profileRef': PROFILE_REF,
                                   'context': {}, 'options': {}}),
        ('agents.nodes.queryPreparation', {'requestId': 'no-original-preparation'}),
        ('agents.nodes.configuration.query', {'nodeRef': node_ref, 'operationRef': 'no-original-operation'}),
        ('agents.nodes.stop', {'nodeRef': node_ref, 'requestId': 'request-1', 'preconditions': {}}),
    ]
    for method, params in refusals:
        with pytest.raises(WireError) as caught:
            registry[method](params)
        assert caught.value.family == 'CAPABILITY_UNSUPPORTED', method
        assert caught.value.details.get('retryable') is False
    # Contrast: the advertised owner-backed observation still answers.
    described = registry['agents.nodes.configuration.describe']({'nodeRef': node_ref})
    assert [item['configurationKind'] for item in described['descriptions']] == ['model']
    # One refused battery changed no durable fact and invoked no owner.
    assert dump(setup) == before
    assert counters(setup) == counts


def test_wire_operation_query_view_typed_zero_effect_and_six_field_read(setup):
    # Compose management authorities once, the way a managing Server host does.
    services = unit_services(setup[1], invocation_issuer=setup[10])
    assert services.configuration.capabilities()['configurationManagement'] is True
    registry = handlers(lambda: setup[1])
    capabilities = registry['agents.capabilities']({})
    assert capabilities['supports']['configurationManagement'] is True
    assert capabilities['supports']['nodePreparation'] is False
    assert 'agents.nodes.configuration.query' in capabilities['supportedMethods']
    assert 'agents.nodes.queryPreparation' not in capabilities['supportedMethods']
    applied = setup[3].apply(setup[5], setup[4], setup[6])
    assert applied.status == 'published'
    operation_ref = applied.intent.operation_ref
    before, counts = dump(setup), counters(setup)
    node_ref = encode_node_ref(setup[4])
    view = registry['agents.nodes.configuration.query'](
        {'nodeRef': node_ref, 'operationRef': operation_ref})
    assert set(view) == {'operationRef', 'revision', 'status', 'configurationResult'}
    assert view['operationRef'] == operation_ref and view['status'] == 'published'
    assert view['configurationResult'] is not None
    # Typed refusal for an uncomposed preparation capability, not an empty miss.
    with pytest.raises(WireError) as unprepared:
        registry['agents.nodes.queryPreparation']({'requestId': 'no-original-preparation'})
    assert unprepared.value.family == 'CAPABILITY_UNSUPPORTED'
    # Typed refusal for an invalid operationRef once the issuer is composed.
    with pytest.raises(WireError) as invalid_ref:
        registry['agents.nodes.configuration.query']({'nodeRef': node_ref, 'operationRef': ''})
    assert invalid_ref.value.family == 'CONFLICT_REQUEST'
    # One query battery: zero owner invocation, zero claim, zero recovery writes.
    assert dump(setup) == before
    assert counters(setup) == counts
    # The ruled core read: exact six-field whitelist, no body/evidence/step.
    projection = services.operations.read(operation_ref)
    assert frozenset(projection) == WHITELIST
    assert projection['operationRef'] == operation_ref
    assert projection['kind'] == applied.intent.kind
    assert projection['revision'] == view['revision']
    assert projection['status'] == 'published'
    assert projection['nodeRef'] == node_ref
    assert projection['hasResult'] is True
    assert not any(key in projection for key in
                   ('evidence', 'step', 'steps', 'intent', 'context', 'body', 'configurationResult'))
    with pytest.raises(TypeError):
        projection['status'] = 'mutated-client-copy'
    assert dump(setup) == before
    assert counters(setup) == counts


def test_operation_read_service_rejections_keep_six_field_whitelist(setup):
    services = unit_services(setup[1], invocation_issuer=setup[10])
    operations = services.operations
    applied = setup[3].apply(setup[5], setup[4], setup[6])
    operation_ref = applied.intent.operation_ref
    record = setup[0].read_operation(setup[5])
    before, counts = dump(setup), counters(setup)

    projection = operations.read(operation_ref)
    assert frozenset(projection) == WHITELIST
    assert projection['operationRef'] == operation_ref
    assert projection['kind'] == record.intent.kind
    assert projection['revision'] == record.revision
    assert projection['status'] == record.status
    assert projection['nodeRef'] == encode_node_ref(setup[4])
    assert projection['hasResult'] == (record.result is not None)

    # Missing and foreign-principal reads answer the identical typed absence:
    # another caller's operation never leaks its existence.
    with pytest.raises(OperationNotFound) as missing:
        operations.read('missing-operation')
    with pytest.raises(OperationNotFound) as foreign:
        foreign_operations(setup).read(operation_ref)
    assert (type(missing.value), missing.value.code, str(missing.value)) == \
           (type(foreign.value), foreign.value.code, str(foreign.value))
    assert missing.value.code == 'OPERATION_NOT_FOUND'

    # Invalid DTO operationRef values are refused before any lookup.
    for bad in ('', ' leading', 'trailing ', 'line\nbreak', 'x' * 257,
                1, None, b'ref', ['ref'], {'ref': 'x'}):
        with pytest.raises(UnitIdentityMismatch):
            operations.read(bad)

    # Operation read ACL denial happens before any index lookup.
    original_admit = setup[2].admit_object_access
    try:
        setup[2].admit_object_access = (
            lambda principal, target, purpose:
            ':operation:' not in target and original_admit(principal, target, purpose))
        with pytest.raises(UnitAdmissionRefused):
            operations.read(operation_ref)
    finally:
        setup[2].admit_object_access = original_admit

    # Dual-read ACL: the operation is readable but its target Node is not; the
    # association is hidden exactly like an absent operation.
    try:
        setup[2].admit_object_access = (
            lambda principal, target, purpose:
            ':agents.node:' not in target and original_admit(principal, target, purpose))
        with pytest.raises(OperationNotFound):
            operations.read(operation_ref)
    finally:
        setup[2].admit_object_access = original_admit

    # Corrupted identity index: refused as unverifiable, not as a green read.
    cursor = setup[0]._conn.execute(
        "SELECT payload FROM env_domain_records"
        " WHERE environment='env' AND namespace='core.operation-identities' AND record_id=?",
        (operation_ref,))
    original_payload = cursor.fetchone()['payload']
    good_holder = json.loads(original_payload)['holder']

    def write_holder(holder):
        setup[0]._conn.execute(
            "UPDATE env_domain_records SET payload=?"
            " WHERE environment='env' AND namespace='core.operation-identities' AND record_id=?",
            (json.dumps({'holder': holder}), operation_ref))

    try:
        write_holder({'kind': 'operation', 'environmentNamespace': 'env',
                      'principalScope': 'principal', 'requestId': good_holder['requestId'],
                      'operationId': 'another-operation'})
        with pytest.raises(UnitGuaranteeUnavailable):
            operations.read(operation_ref)
        write_holder({key: good_holder[key] for key in good_holder if key != 'requestId'})
        with pytest.raises(UnitGuaranteeUnavailable):
            operations.read(operation_ref)
    finally:
        setup[0]._conn.execute(
            "UPDATE env_domain_records SET payload=?"
            " WHERE environment='env' AND namespace='core.operation-identities' AND record_id=?",
            (original_payload, operation_ref))

    # No same-store operation ledger: typed refusal, never an empty success.
    stranger = Environment('env-stranger', store=object(), policy=setup[2],
                           principal_scope='principal', resource_extension_snapshot=_test_resource_snapshot)
    with pytest.raises(UnitGuaranteeUnavailable):
        AgentOperations(stranger, services.nodes).read(operation_ref)

    # Provider retirement releases usage only; durable history stays readable.
    node_facts = services.nodes.read(setup[4])
    activation = setup[1].agent_runtime_contribution(
        node_facts['binding']['harnessDefinitionRef']).provider_ref
    owner = activation['ownerActivationRef']
    setup[1].retire_activation(HarnessActivationRef(
        owner['environmentNamespace'], owner['pluginId'], owner['generation']))
    assert operations.read(operation_ref)['status'] == record.status
    assert services.nodes.read(setup[4]) is not None

    # Every read above left the ledger and the owner untouched.
    assert dump(setup) == before
    assert counters(setup) == counts
    assert setup[0].read_operation(setup[5]) is not None


def test_operation_read_uncertain_operation_reports_no_result(setup):
    services = unit_services(setup[1], invocation_issuer=setup[10])
    operations = services.operations
    setup[7]['outcome'] = 'unknown'
    uncertain_request = RequestKey('env', 'principal', 'second-configuration-request')
    uncertain_change = replace(setup[6], request_id='second-configuration-request')
    uncertain = setup[3].apply(uncertain_request, setup[4], uncertain_change)
    assert uncertain.status == 'unknown'
    uncertain_ref = uncertain.intent.operation_ref
    before, counts = dump(setup), counters(setup)
    projection = operations.read(uncertain_ref)
    assert frozenset(projection) == WHITELIST
    assert projection['status'] == 'unknown'
    assert projection['hasResult'] is False
    assert projection['revision'] == setup[0].read_operation(uncertain_request).revision
    # Reading an uncertain original never claims a result and never recovers.
    assert dump(setup) == before
    assert counters(setup) == counts
