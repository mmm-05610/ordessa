"""Two original Server roots with one real Manager/Local ACP peer, zero model.

Authority is explicitly controlled test authority, never a human Grant.
"""
from ordessa_server.composition.agent_tools.owner_ports import OwnerAssemblyRefused
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
import sys,time
import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'packages/execution/agents/tests/support'))
sys.path.insert(0,str(ROOT/'packages/execution/units/tests'))
from agent_tools_fixtures.invocation_authority import Authority, CurrentState
from test_unit_instance import Provider, Preparation, Scope
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor,RUNTIME_PROVIDER_VERSION
from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration,HarnessDefinitionDescriptor,HarnessInstallationObservation,
    HarnessContributionSet,HarnessAdmission,harness_registration_snapshot)
from ordessa_units.admission.material_admission import material_registration_snapshot
from ordessa_units.public import AgentOwnerInputs,FreshUnitFactory,unit_services
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.management import UnitInstance
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.bindings.assembly import PreparationContext
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_agents.profiles import decode_revision_ref
from pacthold.public import Environment,InstallationRecord
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_server.composition.runtime import DataRootOwner
from ordessa_server.composition.agent_owner import assemble_agent_owner
from ordessa_server.composition.agent_tools import AgentToolsDeployment
from ordessa_server.composition.agent_tools.owner_ports import OwnerPorts


def fingerprint():return ProtectedFingerprintHmac({'fixture':b'fresh-server-root'},active_key_id='fixture')
class OriginalScope(Scope):
    def __init__(self,namespace):self.namespace=namespace
    def issue_scope(self,provider,node,roots):
        from ordessa_units.records.unit_records import CanonicalConfigurationScopeRef
        return CanonicalConfigurationScopeRef(self.namespace,'configuration','1')
    def verify_scope(self,scope,roots):return scope.environment_namespace==self.namespace
    def map_legacy_scope(self,target):
        from ordessa_units.records import UnitRecordsRefused
        raise UnitRecordsRefused("historical conversion unavailable")
class Policy:
    def admit_invoke(self,*args):return True
    def admit_object_access(self,*args):return True
class OriginalEnvironment(Environment):
    @property
    def store_port(self):return self._store


@contextmanager
def root_owner(tmp_path,kind,*,acp_turn_opt_in=True,effect_write_guard_factory=None):
    root=tmp_path/kind
    host=DataRootOwner(root);host.acquire()
    units=[];events=[];local_root=root/'peer'/'root';local_root.parent.mkdir()
    local=Provider(local_root,events);holder={}
    def inputs_for(env):
        namespace=env.environment_id
        definition={'environmentNamespace':namespace,'definitionId':'pi','revision':'1'}
        env.install(InstallationRecord('pi','a'*64));env.enable('pi')
        declaration=HarnessDefinitionDeclaration(HarnessDefinitionDescriptor('pi',definition,
            'sha256:'+'a'*64,'acp/v1','controlled-peer',capabilities=('existingChannel',)),
            lambda _:HarnessInstallationObservation('present'))
        env.activate('pi',HarnessContributionSet(harness_definitions=(declaration,)))
        pin=HarnessAdmission(env).describe(definition).provider_ref
        directory=DirectoryBindingRef(namespace,'controlled-directory',1,'sha256:'+'d'*64)
        authority=Authority();authority.issuer_ref['environmentNamespace']=namespace;authority.expiry=time.time()+600
        current=CurrentState(pin,directory,None)
        evidence=AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'],
            start_authority=lambda unit,ctx:evidence.records.verifier.verify_continuation(ctx,'start',
                unit.facts['providerRef'],unit.facts['nodeRef'],ctx.facts['inputDigest']))
        descriptor=RuntimeProviderDescriptor('pi',RUNTIME_PROVIDER_VERSION,definition,'sha256:'+'a'*64,
            ('plan_preparation','prepare','start','connect','describe_access','stop','release'))
        def materialize(agent,environment,facts,snapshot):
            from ordessa_agents.preparation import ConfigurationResources
            location=environment.files.ensure(str(Path(agent.harness.resources.location).relative_to(local_root)))
            (Path(location)/'settings.json').write_text('{}')
            return ConfigurationResources(agent.harness.resources.kind,location,True)
        def factory(environment_id,plan,view):
            assert environment_id==AdmissionNamespace(namespace)
            unit=UnitInstance(descriptor=descriptor,agent_id='controlled-server-unit',
                profile_revision=decode_revision_ref(dict(plan['profileSnapshot']['ref'])),
                environment_instance=local,environment_sharing=True,environment_reference={'environmentId':local.identity},
                preparation=Preparation(events),materializer=materialize,records=view.records,projection=evidence,
                verifier=view.verifier,lease_port=ConnectionLeasePort(),termination_evidence=evidence,timeout=2,effect_write_guard_factory=effect_write_guard_factory)
            units.append(unit);return unit
        class Context:
            def resolve(self,request,manifest,admitted,node,context,options):
                return PreparationContext(directory,{'installationRef':{'environmentNamespace':namespace,
                    'installationId':'pi','sourceRevision':'a'*64}}, {'nodeRef':dict(node),'privateRootFacts':{
                    key:str(local_root/key) for key in ('home','cwd','profile')}})
        inputs=AgentOwnerInputs(authority,current,OriginalScope(namespace),evidence,SimpleNamespace(current_epoch=lambda _:0),
            preparation_context_port=Context(),fresh_unit_factory=FreshUnitFactory(factory),
            acp_turn_opt_in=acp_turn_opt_in,termination_evidence=evidence)
        holder.update(inputs=inputs,current=current,declaration=declaration,definition=definition)
        return inputs
    env=owner=store=None
    try:
        path=root/'state'/'core.sqlite'
        if kind=='default':
            path.parent.mkdir();store=SqliteStorePort(path)
            env=OriginalEnvironment('env',store=store,policy=Policy(),fingerprint_port=fingerprint(),
                resource_extension_snapshot=material_registration_snapshot,harness_definition_snapshot=harness_registration_snapshot)
            env.store_path=path
            journal_path=root/'state'/'agent-owner'/'operations.sqlite'
            binding=host.bind_owned_root(root_path=root,store_path=path,child_path=journal_path)
            owner=assemble_agent_owner(env,inputs_for(env),binding,root_port=host)
            services=unit_services(env,owner_ports=owner.ports)
        else:
            def ports_factory(env):
                inputs=inputs_for(env)
                values={f.name:getattr(inputs,f.name) for f in fields(OwnerPorts)}
                return OwnerPorts(**values)
            deployment=AgentToolsDeployment(fingerprint_port=fingerprint(),agent_contract_version='agent-assembly/3',
                policy_factory=lambda _:Policy(),owner_ports_factory=ports_factory)
            env=deployment.owned_environment_factory(path,host)
            owner=env.owner_ports;services=unit_services(env)
        yield SimpleNamespace(env=env,owner=owner,services=services,units=units,events=events,holder=holder,local=local)
    finally:
        for unit in units:
            use=unit.channel_factory.environment
            if use is not None and use.identity in local.release_receipts:
                continue
            record=unit.channel_factory.owned_record
            if record is not None and unit.channel_factory.environment is not None:
                unit.channel_factory.close(record.entry);unit.channel_factory.release(record.entry)
                unit.channel_factory.release_environment()
        if owner is not None:owner.revoke()
        if env is not None:env.close()
        if store is not None:store.close()
        host.release()


@pytest.mark.parametrize('kind',['default','agent-tools'])
def test_original_root_manager_prepare_stop_release(kind,tmp_path):
    with root_owner(tmp_path,kind) as j:
        namespace=j.env.environment_id
        assert j.owner.records.verifier is j.owner.verifier
        assert j.owner.records.acp_turn_available and j.owner.journal.acp_turn_opt_in
        assert not j.owner.records.managed_turn_available
        assert j.services.unit_manager.records is j.owner.records
        assert j.services.unit_manager.verifier is j.owner.verifier
        assert j.units==[]
        entry=j.services.profiles.create(profile_id='root-fixed',name='Root fixed',content={
            'schemaVersion':'1','harnessDefinitionRef':j.holder['definition'],'declarations':[]},
            request=RequestKey(namespace,'local','profile'))
        operation=j.services.assembly.prepare(RequestKey(namespace,'local','prepare'),entry.current_revision,{}, {})
        assert operation.status=='published'
        node=decode_node_ref(operation.intent.node_ref);binding=j.services.nodes.read(node)['binding']
        unit=j.services.unit_manager.find(binding['harnessUnitRef'])
        assert j.events.count('spawn')==1 and unit.records is j.owner.records
        ref=binding['harnessUnitRef']
        receipt=unit.prompt(ref,unit.lease_port.grant(ref),
            operation_ref='root-controlled-turn',timeout=2,prompt=[])
        assert receipt['state']=='completed'
        assert receipt['summary']['modelQualityVerified'] is False
        from ordessa_units.records import UnitRecords,OperationJournal
        from ordessa_units.definitions.operations import OperationIntent, StepIntent
        query_digest=UnitRecords.acp_turn_query_digest(ref,'root-controlled-turn',receipt['inputDigest'])
        query=RequestKey(namespace,'local','cold-read')
        context=dict(operation.intent.context_ref)
        context['invocationBindings']={'read':{'action':'query','targetRef':dict(operation.intent.node_ref),
            'delegationRef':None,'cleanup':False}}
        intent=OperationIntent('root-cold-read','unit-acp-query',operation.intent.profile_snapshot_ref,context,
            (StepIntent('read',operation.intent.steps[0].pinned_provider_ref,query_digest,'root-read'),),
            dict(operation.intent.node_ref))
        j.owner.issuer._store.reserve_operation(query,query_digest,intent)
        invocation=j.owner.issuer.issue_query(query,query_digest,'read')
        def forbidden(*_):raise AssertionError('cold query cannot inspect native handles')
        cold=UnitRecords(OperationJournal(j.owner.journal.path),
            scope_authority=j.holder['inputs'].scope_authority,
            native_evidence=SimpleNamespace(verify_binding=forbidden),verifier=j.owner.verifier,
            epoch_port=j.holder['inputs'].management_epoch)
        assert cold.query_acp_turn(ref,'root-controlled-turn',invocation,input_digest=query_digest,
            expected_prompt_input_digest=receipt['inputDigest'])==receipt
        j.holder['current'].acquired=dict(operation.intent.node_ref);j.holder['current'].evidence=dict(binding['harnessUnitRef'])
        j.services.lifecycle.stop(RequestKey(namespace,'local','stop'),node,{})
        j.services.lifecycle.release(RequestKey(namespace,'local','release'),node,{})
        assert j.services.unit_manager.list()==()
        assert j.local.instance.snapshot.active_uses==0
        assert 'recover' not in j.services.lifecycle.capabilities()['supportedLifecycleActions']


def test_default_fresh_selection_requires_pi_declaration_and_never_codex(tmp_path):
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    with root_owner(tmp_path,'default') as j:
        missing=create_host_product_composition(fingerprint_port=j.env._fingerprint_port,
            agent_owner_inputs=j.holder['inputs'])
        with pytest.raises(OwnerAssemblyRefused,match='explicit Pi definition'):
            missing.default_plugins()
        product=create_host_product_composition(fingerprint_port=j.env._fingerprint_port,
            agent_owner_inputs=j.holder['inputs'],pi_definition_declaration=j.holder['declaration'])
        selected=[p.descriptor().id for p in product.default_plugins()]
        assert 'pi' in selected and 'codex' not in selected
        assert j.units==[] and j.events.count('spawn')==0
        with pytest.raises(OwnerAssemblyRefused):
            product._codex_provider_factory(AdmissionNamespace(j.env.environment_id),j.owner.ports.provider_view)


@pytest.mark.parametrize('kind',['default','agent-tools'])
def test_fresh_root_does_not_infer_recorded_or_managed_opt_in(kind,tmp_path):
    with root_owner(tmp_path,kind,acp_turn_opt_in=False) as j:
        assert not j.owner.records.acp_turn_available
        assert not j.owner.journal.acp_turn_opt_in
        assert not j.owner.records.managed_turn_available
        assert j.services.unit_manager.records is j.owner.records
        assert j.units==[] and j.events.count('spawn')==0
