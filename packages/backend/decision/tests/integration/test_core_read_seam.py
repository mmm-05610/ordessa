"""Real temporary Environment registry with controlled owner; no native effects."""
from dataclasses import replace
import pytest
from pacthold.public import Environment, InstallationRecord
from pacthold.agents.public import *
from pacthold.agents.runtime import RUNTIME_METHODS
from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError

DEF={'environmentNamespace':'test','definitionId':'fake','revision':'1'}
class Policy:
    allowed=True
    def admit_object_access(self, *args): return self.allowed
    def admit_invoke(self, *args): return self.allowed

class Owner:
    descriptor=RuntimeProviderDescriptor('fake',RUNTIME_PROVIDER_VERSION,DEF,'sha256:'+'a'*64,
        ('describe_configuration_offers','assess_configuration_proposal'),PURE_READ_VERSION)
    def __init__(self): self.calls=[]; self.effects=[]; self.after=lambda:None; self.bad=False
    def describe_configuration_offers(self,definition,context):
        self.calls.append('offers'); self.context=context
        assert context.environment_namespace=='test'
        self.after()
        return OwnerConfigurationOfferBatch(context.provider_ref,definition,'1',self.descriptor.implementation_digest,
            (ConfigurationDescription('brand.new','1',{'type':'number','minimum':0.1},('value',),'session',('live',),'none','supported'),),True,PURE_READ_VERSION,
            evidence_refs=({'environmentNamespace':'test','evidenceId':'offer'},))
    def assess_configuration_proposal(self,input,context):
        self.calls.append('assessment'); self.context=context; self.after()
        evidence={'environmentNamespace':'test','evidenceId':'read'}
        rows=tuple({'obligationId':o['obligationId'],'status':'passed','checkerId':o['checkerId'],'checkerVersion':o['checkerVersion'],'sourceVersions':{'descriptor':'1'},'evidenceRefs':[evidence]} for o in input.required_obligations)
        return OwnerProposalAssessment('bad' if self.bad else input.input_digest,{'descriptor':'1'},'valid',(),rows,'owner pure-read only',(evidence,),PURE_READ_VERSION)
for method in RUNTIME_METHODS:
    if not hasattr(Owner,method):
        def effect(self,*args,_method=method): self.effects.append(_method); raise AssertionError('mutation/probe forbidden')
        setattr(Owner,method,effect)

@pytest.fixture
def setup(tmp_path):
    from ordessa_persistence_sqlite import SqliteStorePort, ProtectedFingerprintHmac
    store=SqliteStorePort(tmp_path/"core.sqlite")
    fingerprint=ProtectedFingerprintHmac({"test":b"controlled-test-only"*2},active_key_id="test")
    policy=Policy(); env=Environment('test',policy=policy,principal_scope='authenticated',store=store,fingerprint_port=fingerprint)
    env.install(InstallationRecord('fake.plugin','a'*64)); env.enable('fake.plugin')
    owner=Owner(); env.activate('fake.plugin',AgentContributionSet(agent_runtime_providers=(owner,)))
    api=agent_services(env)
    yield env,policy,owner,api
    env.close(); store.close()

def input_for(api):
    provider=api.providers.describe(DEF)['providerRef']
    return OwnerProposalInput(DEF,provider,'1',{'configurationKind':'brand.new','payload':0.7},(),
        ({'obligationId':'config','requirement':'must','checkerId':'owner','checkerVersion':'1'},))

def test_T55_T57_T61_T62_real_public_forward(setup,tmp_path,monkeypatch):
    env,policy,owner,api=setup
    import subprocess
    def forbidden(*args,**kw): raise AssertionError('process forbidden')
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    before=tuple(tmp_path.iterdir())
    offers=api.providers.describe_configuration_offers(DEF)
    result=api.providers.assess_configuration_proposal(input_for(api))
    assert offers.offers[0].configuration_kind=='brand.new' and result.status=='valid'
    assert owner.calls==['offers','assessment'] and owner.effects==[]
    assert tuple(tmp_path.iterdir())==before
    assert owner.context.principal_scope=='authenticated'
    with pytest.raises(TypeError): api.providers.describe_configuration_offers(DEF,principal='root')

def test_T57_permission_version_and_bad_receipt(setup):
    env,policy,owner,api=setup; value=input_for(api)
    with pytest.raises(ConfigurationRevisionConflict): api.providers.assess_configuration_proposal(replace(value,descriptor_revision='2'))
    owner.bad=True
    with pytest.raises(GuaranteeUnavailableError): api.providers.assess_configuration_proposal(value)
    policy.allowed=False
    with pytest.raises(AdmissionRefusedError): api.providers.describe_configuration_offers(DEF)
    assert owner.effects==[]

def test_T57_owner_retired_in_callback(setup):
    env,policy,owner,api=setup
    owner.after=lambda: env.retire(env.agent_runtime_contribution(DEF).owner_activation)
    with pytest.raises(Exception): api.providers.describe_configuration_offers(DEF)
    assert owner.effects==[]

def test_T65_old_provider_unsupported(setup):
    env,policy,owner,api=setup
    # New provider registration retains all old contracts but opts out of pure read.
    other=Environment('test',policy=policy); other.install(InstallationRecord('old.plugin','a'*64)); other.enable('old.plugin')
    old=Owner(); old.descriptor=replace(old.descriptor,supported_methods=(),pure_read_contract_version=None)
    other.activate('old.plugin',AgentContributionSet(agent_runtime_providers=(old,)))
    with pytest.raises(ConfigurationUnsupported): agent_services(other).providers.describe_configuration_offers(DEF)
    assert old.calls==[] and old.effects==[]
    other.close()

async def test_T55_T56_profile_and_filtered_scope(setup):
    from ordessa_decision.contracts import ReadContext
    from ordessa_decision.integrations.ordessa import OrdessaReadFacade, ObservationQuery
    env,policy,owner,api=setup
    context=ReadContext(object(),'test')
    adapter=OrdessaReadFacade(api,namespace='test',read_context=context)
    profile=api.profiles.create(profile_id='sample',display_name='Sample',
        manifest={'harnessDefinitionRef':DEF,'schemaVersion':'profile/1','declarations':[]},
        request=api.profiles.request_key('setup-profile'))
    actual=api.profiles.preview(profile.current_manifest_ref)
    assert actual['status']=='unresolved' and actual['ready'] is False
    profiles=await adapter.observe(ObservationQuery('profiles',{}),context)
    assert not profiles.complete and profiles.unobserved_items==('permission_filtered_items',)
    single=await adapter.observe(ObservationQuery('profile',{'profile_ref':profile.current_manifest_ref.to_dict()}),context)
    assert single.complete and single.observations[0].source_version=='1'
    providers=await adapter.observe(ObservationQuery('providers',{}),context)
    assert 'installation' in providers.unobserved_items and not providers.complete
    nodes=await adapter.observe(ObservationQuery('nodes',{}),context)
    assert not nodes.complete and not nodes.observations and 'availability' in nodes.unobserved_items
    with pytest.raises(ValueError): await adapter.observe(ObservationQuery('profiles',{}),ReadContext(object(),'test'))
    with pytest.raises(ValueError): ObservationQuery('assembly.prepare',{})
    assert owner.effects==[]

async def test_T61_T62_T67_core_adapter_graph_owner_validation(setup,tmp_path):
    from ordessa_decision.contracts import plain, DecisionServices
    from ordessa_decision.offline import offline_case
    from ordessa_decision.runtime import run_decision
    from ordessa_decision.flows.agent_assignment.build import build_assignment_flow
    from ordessa_decision.integrations.ordessa import OrdessaReadFacade, ObservationQuery, OwnerProposalValidator
    env,policy,owner,api=setup
    request,old_flow,services=offline_case(action='create')
    adapter=OrdessaReadFacade(api,namespace='test',read_context=services.read_context)
    flow=build_assignment_flow(services.policy,read_query=ObservationQuery('configuration_offers',{'definition_ref':DEF}))
    request=replace(request,flow_ref=flow.ref)
    def builder(draft,basis):
        return OwnerProposalInput(DEF,api.providers.describe(DEF)['providerRef'],'1',
            {'configurationKind':'brand.new','payload':draft.payload['configuration']['ratio']},(),
            tuple({'obligationId':o.obligation_id,'requirement':o.requirement,'checkerId':o.validator_kind,'checkerVersion':o.version_constraint} for o in draft.required_validation_obligations))
    validator=OwnerProposalValidator(api.providers,input_builder=builder,read_context=services.read_context)
    services=replace(services,read=adapter,validator=validator)
    native_before=api.providers.list()
    result=await run_decision(request,flow=flow,services=services)
    assert result.status=='completed' and result.outcome.disposition=='ready'
    assert result.outcome.receipts[0].validator_id=='ordessa.owner'
    assert result.outcome.proposals[0].payload['configuration']['ratio']==0.7
    assert owner.calls==['offers','assessment'] and owner.effects==[]
    assert api.providers.list()==native_before and api.nodes.list()==() and api.profiles.list()==()
    # Descriptor drift invalidates original input instead of starting to probe.
    owner.descriptor=replace(owner.descriptor,implementation_digest='sha256:'+'b'*64)
    with pytest.raises(Exception): await validator.validate(result.outcome.proposals[0],{},services.read_context)
    assert owner.effects==[]
