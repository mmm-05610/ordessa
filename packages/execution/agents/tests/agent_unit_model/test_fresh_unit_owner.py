"""Fresh original-owner selection and Local ACP durability; zero model calls."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent_tools_fixtures.manager_joint import build_joint_owner
from ordessa_units.public import (
    AgentOwnerUnavailable, AgentProviderView, FreshUnitFactory, bind_unit_manager,
    validate_agent_owner_inputs, decode_node_ref,
)
from ordessa_units.records import OperationJournal, UnitRecords, UnitRecordsRefused
from ordessa_units.records.operation_journal import JournalError
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.encoding.immutable_json import safe_json


@pytest.mark.parametrize('field,value', [
    ('fresh_unit_factory', object()), ('fresh_unit_factory', None),
    ('provider_factory', lambda *_: object()), ('node_evidence_port', object()),
    ('preparation_observation_port', object()), ('lifecycle_observation_port', object()),
    ('acp_turn_opt_in', 1), ('acp_turn_opt_in', 'true'),
    ('preparation_context_port', None), ('authority', None), ('current_state', None),
])
def test_selection_refuses_mixed_missing_or_implicit_inputs_before_factory(tmp_path, field, value):
    with build_joint_owner(tmp_path) as j:
        with pytest.raises(AgentOwnerUnavailable):
            validate_agent_owner_inputs(replace(j.inputs, **{field: value}))
        assert j.factory_calls == [] and j.events == []


@pytest.mark.parametrize('field', ['scope_authority', 'native_session_evidence', 'management_epoch',
    'configuration_evidence', 'native_unit_evidence', 'input_association_evidence', 'termination_evidence'])
def test_selected_record_ports_cannot_be_substituted(tmp_path, field):
    with build_joint_owner(tmp_path) as j:
        # A structurally valid port is still not the selected original object.
        substitute = SimpleNamespace(**{name: lambda *_: None for name in (
            'issue_scope', 'verify_scope', 'map_legacy_scope', 'verify_binding', 'current_epoch',
            'verify_configuration', 'capture_configuration', 'read_configuration_result',
            'verify_unit_binding', 'verify_association', 'verify_termination')})
        with pytest.raises(AgentOwnerUnavailable, match='original selected records'):
            bind_unit_manager(replace(j.inputs, **{field: substitute}),
                environment_id=AdmissionNamespace('env'), provider_view=j.view)
        assert j.factory_calls == [] and j.events == []


def test_binding_keeps_one_original_issuer_and_manager_without_factory_effect(tmp_path):
    with build_joint_owner(tmp_path, acp_turn_opt_in=True) as j:
        assert j.factory_calls == [] and j.manager.list() == () and j.events == []
        assert j.manager.records is j.records and j.manager.verifier is j.view.verifier
        assert j.records.acp_turn_available and j.records.journal.acp_turn_opt_in
        with pytest.raises(AgentOwnerUnavailable, match='already has'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('env'), provider_view=j.view)
        with pytest.raises(AgentOwnerUnavailable, match='original selected issuer'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('foreign'), provider_view=j.view)
        with pytest.raises(AgentOwnerUnavailable, match='original selected issuer'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('env'),
                provider_view=AgentProviderView(j.records, object()))
        with pytest.raises(AgentOwnerUnavailable, match='original selected records'):
            bind_unit_manager(replace(j.inputs, acp_turn_opt_in=False),
                environment_id=AdmissionNamespace('env'), provider_view=j.view)
        j.issuer.close()
        with pytest.raises(AgentOwnerUnavailable, match='original selected issuer'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('env'), provider_view=j.view)
        assert j.factory_calls == []


def test_no_legacy_factory_reinterpretation_or_implicit_opt_in(tmp_path):
    with build_joint_owner(tmp_path) as j:
        legacy = replace(j.inputs, fresh_unit_factory=None, provider_factory=lambda *_: object(),
            node_evidence_port=SimpleNamespace(inspect=lambda *_: None),
            preparation_observation_port=SimpleNamespace(observe=lambda *_: None))
        validate_agent_owner_inputs(legacy)
        with pytest.raises(AgentOwnerUnavailable, match='selection is unavailable'):
            bind_unit_manager(legacy, environment_id=AdmissionNamespace('env'), provider_view=j.view)
        with pytest.raises(AgentOwnerUnavailable, match='explicit fresh Unit selection'):
            validate_agent_owner_inputs(replace(legacy, acp_turn_opt_in=True))
        with pytest.raises(AgentOwnerUnavailable):
            FreshUnitFactory(None)
        with pytest.raises(JournalError, match='pristine'):
            OperationJournal(j.records.journal.path, acp_turn_opt_in=True)
        cold = UnitRecords(OperationJournal(j.records.journal.path),
            scope_authority=j.inputs.scope_authority, native_evidence=j.inputs.native_session_evidence,
            verifier=j.view.verifier, epoch_port=j.inputs.management_epoch,
            termination_evidence=j.inputs.termination_evidence)
        with pytest.raises(AgentOwnerUnavailable, match='original selected records'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('env'),
                provider_view=AgentProviderView(cold, j.view.verifier))
        assert j.factory_calls == [] and j.events == []


def _prepare(j):
    request = RequestKey('env', 'principal', 'fresh-prepare')
    operation = j.services.assembly.prepare(request, j.profile, {}, {})
    assert operation.status == 'published'
    node = decode_node_ref(operation.intent.node_ref)
    ref = j.services.nodes.read(node)['binding']['harnessUnitRef']
    return operation, node, ref, j.manager.find(ref)


def _cold_query(j, operation, ref, prompt_digest, *, suffix='1'):
    digest = UnitRecords.acp_turn_query_digest(ref, 'fresh-turn', prompt_digest)
    request = RequestKey('env', 'principal', 'fresh-read-' + suffix)
    context = dict(operation.intent.context_ref)
    context['invocationBindings'] = {'read': {'action': 'query', 'targetRef': dict(operation.intent.node_ref),
                                             'delegationRef': None, 'cleanup': False}}
    intent = OperationIntent('fresh-query-' + suffix, 'unit-acp-query',
        operation.intent.profile_snapshot_ref, context,
        (StepIntent('read', operation.intent.steps[0].pinned_provider_ref, digest, 'read-' + suffix),),
        dict(operation.intent.node_ref))
    j.store.reserve_operation(request, digest, intent)
    invocation = j.issuer.issue_query(request, digest, 'read')
    def forbidden(*_):
        raise AssertionError('cold query must not observe native handles')
    cold = UnitRecords(OperationJournal(j.records.journal.path), scope_authority=j.inputs.scope_authority,
        native_evidence=SimpleNamespace(verify_binding=forbidden), verifier=j.view.verifier,
        epoch_port=j.inputs.management_epoch)
    return cold.query_acp_turn(ref, 'fresh-turn', invocation, input_digest=digest,
                              expected_prompt_input_digest=prompt_digest)


def test_fresh_manager_node_recorded_prompt_authorized_cold_read_and_original_cleanup(tmp_path):
    with build_joint_owner(tmp_path, acp_turn_opt_in=True) as j:
        operation, node, ref, unit = _prepare(j)
        assert len(j.factory_calls) == 1 and j.factory_calls[0][2] is j.view
        assert j.events.count('spawn') == 1
        lease = unit.lease_port.grant(ref)
        receipt = unit.prompt(ref, lease, operation_ref='fresh-turn', timeout=2, prompt=[])
        assert receipt['state'] == 'completed'
        assert receipt['summary']['successfulRpcResponse'] is True
        assert receipt['summary']['modelQualityVerified'] is False
        assert _cold_query(j, operation, ref, receipt['inputDigest']) == receipt
        with pytest.raises(UnitRecordsRefused, match='no replay'):
            unit.prompt(ref, lease, operation_ref='fresh-turn', prompt=[])
        j.inputs.authority.allowed = False
        with pytest.raises(InvocationAuthorityRefused):
            _cold_query(j, operation, ref, receipt['inputDigest'], suffix='revoked')
        j.inputs.authority.allowed = True
        j.current.acquired = dict(operation.intent.node_ref)
        j.current.evidence = dict(ref)
        j.services.lifecycle.stop(RequestKey('env', 'principal', 'fresh-stop'), node, {})
        j.services.lifecycle.release(RequestKey('env', 'principal', 'fresh-release'), node, {})
        assert j.records.owner_read_termination(ref['unitId'], 'release')['state'] == 'confirmed'
        assert j.local.instance.snapshot.active_uses == 0 and j.manager.list() == ()
        assert j.events.count('spawn') == 1 and len(j.factory_calls) == 1


def test_unselected_durable_schema_cannot_record_a_prompt(tmp_path):
    with build_joint_owner(tmp_path) as j:
        _, _, ref, unit = _prepare(j)
        with pytest.raises(UnitRecordsRefused, match='opt-in'):
            unit.prompt(ref, unit.lease_port.grant(ref), operation_ref='fresh-turn', prompt=[])
        with j.records.journal._connect() as db:
            assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='harness_acp_turn_attempts'").fetchone()[0] == 0
        assert len(j.factory_calls) == 1 and j.events.count('spawn') == 1


def test_factory_cannot_substitute_harness_definition_or_retry_unknown(tmp_path, monkeypatch):
    from agent_tools_fixtures import manager_joint
    original = manager_joint.RuntimeProviderDescriptor
    def wrong_definition(*args, **kwargs):
        descriptor = original(*args, **kwargs)
        return replace(descriptor, definition_ref={**dict(descriptor.definition_ref), 'revision': 'foreign'})
    monkeypatch.setattr(manager_joint, 'RuntimeProviderDescriptor', wrong_definition)
    with build_joint_owner(tmp_path, acp_turn_opt_in=True) as j:
        request = RequestKey('env', 'principal', 'wrong-fixed-unit')
        result = j.services.assembly.prepare(request, j.profile, {}, {})
        assert result.status == 'unknown'
        assert j.services.assembly.prepare(request, j.profile, {}, {}).status == 'unknown'
        assert len(j.factory_calls) == 1 and j.local.opens == 0 and j.events == []
        with j.records.journal._connect() as db:
            assert db.execute('SELECT count(*) FROM harness_unit_reservations').fetchone()[0] == 0


def test_foreign_fixed_profile_is_refused_before_factory(tmp_path):
    from ordessa_agents.profiles import encode_revision_ref
    with build_joint_owner(tmp_path) as j:
        foreign = replace(j.profile, environment_namespace='foreign')
        plan = {'profileSnapshot': {'ref': encode_revision_ref(foreign), 'manifest': {
            'schemaVersion': '1', 'harnessDefinitionRef': {'environmentNamespace': 'foreign',
                'definitionId': 'controlled', 'revision': '1'}, 'declarations': []}}}
        invocation = SimpleNamespace(facts={'action': 'prepare', 'query': False,
            'request': {'requestId': 'wrong-profile'}, 'operationRef': 'wrong-profile', 'stepId': 'prepare'})
        with pytest.raises(AgentOwnerUnavailable, match='selected Environment'):
            j.manager.create(plan, invocation)
        assert j.factory_calls == [] and j.events == []


@pytest.mark.parametrize('opt_in', [False, True])
@pytest.mark.parametrize('replacement', ['file', 'symlink'])
def test_original_journal_identity_is_checked_even_without_durable_opt_in(tmp_path, opt_in, replacement):
    with build_joint_owner(tmp_path, acp_turn_opt_in=opt_in) as j:
        path = j.records.journal.path
        original = path.with_name('retained-original.sqlite')
        path.rename(original)
        if replacement == 'symlink':
            path.symlink_to(original)
        else:
            path.touch(exist_ok=False)
        assert j.records.journal.preopened_file_identity_valid is False
        with pytest.raises(AgentOwnerUnavailable, match='original selected records'):
            bind_unit_manager(j.inputs, environment_id=AdmissionNamespace('env'), provider_view=j.view)
        assert j.factory_calls == [] and j.events == []
