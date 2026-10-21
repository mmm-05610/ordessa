"""Normal product bootstrap on original records; no spawn, credential or model."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
import time

import pytest
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_agents.profiles import ProfileService
from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDescriptor, HarnessDefinitionDeclaration, HarnessInstallationObservation)
from ordessa_units.assembly import UnitRunPermission
from ordessa_units.public import AgentOwnerUnavailable, unit_services
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.pi_selection import (
    PiExecutionSelection, PiExecutionPorts, select_pi_execution)
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server.composition.product_runtime import build_product_runtime


@pytest.fixture
def selection_inputs(tmp_path):
    product_root = tmp_path/'product'
    fingerprint = ProtectedFingerprintHmac(
        {'controlled':b'controlled-fingerprint-value-32!!'},active_key_id='controlled')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(product_root)
    try:
        context = setup.unit_runtime.context
        namespace = context.environment_namespace
        definition = {'environmentNamespace':namespace, 'definitionId':'pi', 'revision':'1'}
        profiles = ProfileService(UnitProfileAdmission(context))
        profile = profiles.create(profile_id='selected-profile',name='Fixed test Profile',
            content={'schemaVersion':'1','harnessDefinitionRef':definition,'declarations':[
                {'declarationId':'selected-model','configurationKind':'assets.model-provider',
                 'schemaVersion':'1','action':'value','requirement':'required',
                 'payload':{'provider':'opencode','model':'step-5-preview-free',
                    'protocol':'openai-chat','endpoint':'https://opencode.ai/zen/v1'}}]},
            request=profiles.request_key('create-selected-profile'))
        revision = profiles.get_revision(profile.current_revision)
    finally:
        setup.stop()
    root=tmp_path/'local'; root.mkdir()
    store=SQLiteEnvironmentStore(tmp_path/'environments.sqlite')
    environments=EnvironmentManager(store=store,
        providers={'local':LocalEnvironmentResourceProvider(default_root=str(root))})
    instance=environments.register('local',str(root))
    descriptor=HarnessDefinitionDescriptor('pi',definition,'sha256:'+'a'*64,
        'acp/v1','controlled','controlled',('prepare','start','stop','release'))
    declaration=HarnessDefinitionDeclaration(descriptor,
        lambda *args: HarnessInstallationObservation('present',True,'controlled','controlled-installation'))
    selection=PiExecutionSelection('agent',revision.ref,instance.identity,'local','none',True,
        'selected-model','opencode','step-5-preview-free','/bin/true','a'*64,'/bin/true',
        '/home/maoqh/projects/ordessa/.env')
    calls=[]
    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        calls.append((runtime,admission_context,environment_instance))
        authority=runtime.wire.identity_authority
        scope=Scope(selection.profile_revision.environment_namespace,'test-project')
        actions=frozenset({'prepare','start','interaction','stop','release'})
        authority.replace_grants((AccessGrant(scope,tuple('execution.units.'+a for a in sorted(actions))),))
        principal=authority.authenticate('Bearer '+runtime.token)
        assert principal.kind=='machine' and principal.principal_id==admission_context.principal_scope
        return UnitRunPermission(access_authority=authority,principal=principal,scope=scope,
            agent_id=selection.agent_id,profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity,root_directory=str(root),
            actions=actions,expires_at=time.time()+60)
    ports=PiExecutionPorts(environments,declaration,fingerprint,permission_factory,
        ('step-5-preview-free',),None)
    return selection,ports,calls,instance,product_root


def test_selection_captures_configuration_before_context_without_reading_or_granting(selection_inputs):
    selection,ports,calls,instance,_=selection_inputs
    selected=select_pi_execution(selection,ports)
    assert selected.describe() is None
    assert calls==[] and instance.snapshot.active_uses==0


@pytest.mark.parametrize('change', [
    {'approved_check_command': 'check'},
    {'approved_check_command': 'check', 'restricted_file_tools': True},
    {'approved_check_command': '', 'restricted_file_tools': True, 'callback_approval_factory': lambda **_: None},
])
def test_check_command_cannot_enable_bash_without_original_callback_scope(selection_inputs, change):
    selection, ports, calls, instance, _ = selection_inputs
    with pytest.raises(AgentOwnerUnavailable, match='check command'):
        select_pi_execution(selection, replace(ports, **change))
    assert calls == [] and instance.snapshot.active_uses == 0


@pytest.mark.parametrize('change', [
    {'read_only_file_tools': 1},
    {'read_only_file_tools': 'true'},
    {'read_only_file_tools': True},
    {'read_only_file_tools': True, 'restricted_file_tools': True},
    {'read_only_file_tools': True, 'restricted_file_tools': True,
     'approved_check_command': 'check', 'callback_approval_factory': lambda **_: None},
])
def test_read_only_selection_cannot_enable_commands_or_omit_scope(selection_inputs, change):
    selection, ports, calls, instance, _ = selection_inputs
    with pytest.raises(AgentOwnerUnavailable, match='Read-only Pi tools'):
        select_pi_execution(selection, replace(ports, **change))
    assert calls == [] and instance.snapshot.active_uses == 0


@pytest.mark.parametrize('callback', [None, SimpleNamespace(authorize=lambda **_: None),
    SimpleNamespace(authorize=lambda **_: None, approved_check_command='check', scope_guard=lambda **_: None)])
def test_read_only_product_requires_a_command_free_original_callback_scope(selection_inputs, callback):
    selection, ports, _, instance, root = selection_inputs
    with pytest.raises(AgentOwnerUnavailable, match='Read-only Pi tools'):
        build_product_runtime(root, pi_selection=selection,
            pi_ports=replace(ports, restricted_file_tools=True, read_only_file_tools=True,
                callback_approval_factory=lambda **_: callback))
    assert instance.snapshot.active_uses == 0


def test_read_only_tools_reach_preparation_without_detaching_the_deferred_guard(selection_inputs, monkeypatch):
    import ordessa_server.composition.pi_selection as selection_module
    selection, ports, _, instance, root = selection_inputs
    original = selection_module.PiAcpHarnessPreparation
    prepared = []
    def preparation(**values):
        prepared.append(values)
        return original(**values)
    monkeypatch.setattr(selection_module, 'PiAcpHarnessPreparation', preparation)
    callback = SimpleNamespace(authorize=lambda **_: None, approved_check_command=None,
                               scope_guard=lambda **_: None)
    runtime = build_product_runtime(root, pi_selection=selection,
        pi_ports=replace(ports, restricted_file_tools=True, read_only_file_tools=True,
            callback_approval_factory=lambda **_: callback, acp_turn_opt_in=True,
            defer_effect_write_guard_factory=True))
    try:
        assert prepared[0]['read_only_file_tools'] is True
        assert prepared[0]['approved_check_command'] is None
        owner = runtime.unit_execution_owner
        with pytest.raises(AgentOwnerUnavailable, match='factory finalization is required'):
            runtime.units.create(owner.spec, owner.authorization())
        assert runtime.units.list() == () and instance.snapshot.active_uses == 0
    finally:
        runtime.stop()


@pytest.mark.parametrize('callback', [None, SimpleNamespace(authorize=lambda **_: None),
    SimpleNamespace(authorize=lambda **_: None, approved_check_command='different', scope_guard=lambda **_: None)])
def test_product_refuses_check_command_without_matching_guarded_callback(selection_inputs, callback):
    selection, ports, _, instance, root = selection_inputs
    with pytest.raises(AgentOwnerUnavailable, match='matching original callback scope'):
        build_product_runtime(root, pi_selection=selection,
            pi_ports=replace(ports, restricted_file_tools=True, approved_check_command='check',
                callback_approval_factory=lambda **_: callback))
    assert instance.snapshot.active_uses == 0


def test_managed_input_ports_are_explicit_and_reach_the_same_original_product_owner(selection_inputs):
    from ordessa_units.api import ManagedAcpInputPorts
    selection, ports, calls, instance, root = selection_inputs
    capture = SimpleNamespace(read_content=lambda *_: None)
    workspace = SimpleNamespace(authorize_execute=lambda *_: None, revalidate_execute=lambda *_: None)
    managed = ManagedAcpInputPorts(capture, workspace)
    with pytest.raises(AgentOwnerUnavailable):
        select_pi_execution(selection, replace(ports, managed_input_ports=managed))
    assert calls == [] and instance.snapshot.active_uses == 0
    runtime = build_product_runtime(root, pi_selection=selection,
        pi_ports=replace(ports, managed_input_ports=managed, acp_turn_opt_in=True))
    try:
        owner = runtime.unit_execution_owner
        assert owner._managed_inputs.ports is managed
        assert owner.records is runtime.unit_runtime.context.owner_ports.provider_view.records
        assert instance.snapshot.active_uses == 0
    finally:
        runtime.stop()


def test_normal_product_bootstrap_binds_one_original_context_store_and_manager(selection_inputs):
    selection,ports,calls,instance,root=selection_inputs
    runtime=build_product_runtime(root,pi_selection=selection,pi_ports=ports)
    try:
        context=runtime.unit_runtime.context
        assert len(calls)==1 and calls[0][0] is runtime and calls[0][1] is context
        assert runtime.unit_execution_owner.admission is context
        assert context.owner_ports.issuer._store is context.store_port
        assert unit_services(context).unit_manager is context.owner_ports.unit_manager
        assert runtime.units is runtime.unit_execution_owner.manager
        assert runtime.unit_execution_owner.acp_turn_opt_in is False
        assert runtime.unit_execution_owner.records.acp_turn_available is False
        assert runtime.unit_execution_owner.records.journal.acp_turn_opt_in is False
        assert instance.snapshot.active_uses==0
        assert runtime.execution_selection['environmentId']==instance.identity
        assert runtime.execution_selection['isolation']=='none'
        runtime.start()
        hello=runtime.wire.hello({'clientVersions':['wire/1'],'clientPresentationSupports':[]})
        assert hello['executionSelection']==runtime.execution_selection
        assert hello['executionSelection']['model']=='step-5-preview-free'
        assert 'credential_source' not in hello['executionSelection']
        assert 'bridge_executable' not in hello['executionSelection']
    finally:
        runtime.stop()
    assert instance.snapshot.active_uses==0


@pytest.mark.parametrize('change',[
    {'environment_provider':'openshell'},{'environment_isolation':'sandbox'},
    {'model':'kimi-k3'},{'provider':'deepseek'}])
def test_fixed_selection_cannot_change_resource_or_profile_route(selection_inputs,change):
    selection,ports,calls,instance,root=selection_inputs
    with pytest.raises(AgentOwnerUnavailable):
        build_product_runtime(root,pi_selection=replace(selection,**change),pi_ports=ports)
    assert calls==[] and instance.snapshot.active_uses==0
    assert len(ports.environments.list())==1


def test_missing_permission_configuration_refuses_before_runtime_creation(selection_inputs):
    selection,ports,calls,instance,root=selection_inputs
    with pytest.raises(AgentOwnerUnavailable,match='permission configuration'):
        build_product_runtime(root,pi_selection=selection,
            pi_ports=replace(ports,permission_factory=None))
    assert calls==[] and instance.snapshot.active_uses==0
    assert not (root/'state/agent-owner/operations.sqlite').exists()


@pytest.mark.parametrize('change', [
    {'acp_turn_opt_in': 1},
    {'acp_turn_opt_in': 'true'},
    {'effect_write_guard_factory': False},
    {'effect_write_guard_factory': lambda: None},
    {'defer_effect_write_guard_factory': 1},
    {'defer_effect_write_guard_factory': True},
    {'defer_effect_write_guard_factory': True, 'acp_turn_opt_in': True,
     'effect_write_guard_factory': lambda: None},
])
def test_invalid_acp_opt_in_or_guard_refuses_before_permission_factory(selection_inputs, change):
    selection,ports,calls,instance,_=selection_inputs
    with pytest.raises(AgentOwnerUnavailable):
        select_pi_execution(selection, replace(ports, **change))
    assert calls==[] and instance.snapshot.active_uses==0


def test_deferred_guard_requires_explicit_opt_in_and_refuses_unit_create_until_finalized(selection_inputs):
    selection,ports,calls,instance,root=selection_inputs
    deferred_ports=replace(ports,acp_turn_opt_in=True,
        defer_effect_write_guard_factory=True)
    runtime=build_product_runtime(root,pi_selection=selection,pi_ports=deferred_ports)
    try:
        owner=runtime.unit_execution_owner
        records=owner.records
        assert owner.acp_turn_opt_in is True
        assert owner.effect_write_guard_factory is None
        assert records.acp_turn_available is True
        assert records.journal.acp_turn_opt_in is True
        with pytest.raises(AgentOwnerUnavailable,match='factory finalization is required'):
            runtime.units.create(owner.spec,owner.authorization())
        assert runtime.units.list()==()
        assert len(calls)==1 and calls[0][0] is runtime
        assert calls[0][1] is runtime.unit_runtime.context
        assert instance.snapshot.active_uses==0
    finally:
        runtime.stop()
    assert instance.snapshot.active_uses==0


def test_opted_in_original_records_keep_exact_guard_factory_identity(selection_inputs):
    selection,ports,calls,instance,root=selection_inputs
    guard_factory=lambda *_args: None
    opted_ports=replace(ports, acp_turn_opt_in=True,
                        effect_write_guard_factory=guard_factory)
    runtime=build_product_runtime(root,pi_selection=selection,pi_ports=opted_ports)
    try:
        owner=runtime.unit_execution_owner
        records=owner.records
        assert owner.acp_turn_opt_in is True
        assert owner.effect_write_guard_factory is guard_factory
        assert records.acp_turn_available is True
        assert records.journal.acp_turn_opt_in is True
        original_services=unit_services(runtime.unit_runtime.context)
        assert runtime.units is owner.manager
        assert records is original_services.unit_manager.records
        assert len(calls)==1 and calls[0][0] is runtime
        assert calls[0][1] is runtime.unit_runtime.context
        assert instance.snapshot.active_uses==0
    finally:
        runtime.stop()
    assert instance.snapshot.active_uses==0


def test_caller_permission_fact_cannot_replace_original_runtime_authority(selection_inputs):
    selection,ports,_,instance,root=selection_inputs
    with pytest.raises(AgentOwnerUnavailable,match='Actual runtime permission'):
        build_product_runtime(root,pi_selection=selection,
            pi_ports=replace(ports,permission_factory=lambda **kwargs: SimpleNamespace()))
    assert instance.snapshot.active_uses==0
    assert not (root/'state/agent-owner/operations.sqlite').exists()


def test_public_unit_create_rejects_nonselected_spec_before_preparation(selection_inputs):
    selection,ports,calls,instance,root=selection_inputs
    runtime=build_product_runtime(root,pi_selection=selection,pi_ports=ports)
    try:
        owner=runtime.unit_execution_owner
        outside=replace(owner.spec,agent_id='different-agent')
        with pytest.raises(AgentOwnerUnavailable,match='outside the selected run permission'):
            runtime.units.create(outside,owner.authorization())
        assert runtime.units.list()==()
        assert len(calls)==1
        assert calls[0][0] is runtime
        assert calls[0][1] is runtime.unit_runtime.context
        assert calls[0][2] is owner.environment
        assert calls[0][2].identity==instance.identity
        assert instance.snapshot.active_uses==0
    finally:
        runtime.stop()
    assert instance.snapshot.active_uses==0
