"""C: existing journal/projection-shaped fixtures; no actual Pi/model launch."""
from types import SimpleNamespace
import pytest
from pacthold.agents.access.invocation import InvocationVerifier
from ordessa_harness_pi import PiRuntimeProvider, PiProviderRefused

DIGEST='sha256:'+'a'*64
DEFINITION={'environmentNamespace':'test','definitionId':'pi','revision':'1'}
PROVIDER={'environmentNamespace':'test','providerId':'pi','implementationDigest':DIGEST,'contractVersion':'agent-runtime/2'}
NODE={'environmentNamespace':'test','instanceId':'node','generation':1}
TARGET={'environmentNamespace':'test','scopeId':'scope','revision':'1','ownerProviderRef':PROVIDER,'sourceRevision':'controlled-scope-source-1'}
UNIT={'environmentNamespace':'test','unitId':'unit-1','ownerProviderRef':PROVIDER,'sourceRevision':'controlled-unit-source-1'}


class Projection:
    def __init__(self):
        self.unit=SimpleNamespace(unit_ref='unit-1',public_ref=UNIT,configuration_target_ref=TARGET,facts={'providerRef':PROVIDER,'nodeRef':NODE,
            'privateRootFacts':{'cwd':'/isolated'},'managementEpoch':1},
            scope_ref=SimpleNamespace(to_dict=lambda:{'environmentNamespace':'test','scopeId':'scope','revision':'1'}))
        self.binding=SimpleNamespace(state='notCreated',native_facts=None,source_revision=1)
        self.rechecks=0; self.revoke_at=None; self.bad_evidence=False
    def verify_preparation(self,plan,facts):
        assert plan['context']['nodeRef']==facts['targetRef']
        return self.unit.facts['privateRootFacts']
    def revalidate_start(self,unit,context):
        self.rechecks+=1
        if self.rechecks==self.revoke_at: raise RuntimeError('revoked')
        return context.facts
    def read_unit(self,ref): return self.unit
    def read_session(self,ref): return self.binding
    def publication_facts(self,ref): raise RuntimeError('proof absent')
    def publish_channel(self,unit,client,evidence):
        if self.bad_evidence or evidence.get('sessionId')!='session-1': raise RuntimeError('owner evidence unavailable')
        return 'native-proof'
    def query_creation(self,correlation,facts): return {'correlation':correlation,'state':self.binding.state}


class Records:
    def __init__(self,projection,verifier):
        self.projection=projection; self.verifier=verifier; self.begins=0; self.reserves=0
    def read_unit(self,*args,**kwargs): return self.projection.unit
    def read_session(self,*args,**kwargs): return self.projection.binding
    def reserve_unit(self,context,**kwargs):
        self.reserves+=1
        assert kwargs['private_root_facts']=={'cwd':'/isolated'}
        return self.projection.unit,True
    def begin_session(self,unit,context,*,input_digest):
        if self.projection.binding.state!='notCreated': raise RuntimeError('existing start')
        self.begins+=1; self.projection.binding.state='opening'
        return object()
    def record_session(self,ticket,*,expected_source_revision,state,evidence=None):
        assert expected_source_revision==2
        self.projection.binding.state=state
        if state=='confirmed':
            assert evidence=='native-proof'
            self.projection.binding.native_facts={'nativeRealm':'pi','sessionId':'session-1','evidenceRef':evidence}
            self.projection.binding.source_revision=3
        return self.projection.binding


class Client:
    def __init__(self): self.calls=[]; self.fail=False; self.bad_identity=False; self.closes=0
    def initialize(self):
        self.calls.append('get_state:initialize')
        if self.fail: raise TimeoutError()
        return {'sessionId':'session-1'}
    def command(self,command,**fields):
        self.calls.append(command)
        return {'data':{'sessionId':'other' if self.bad_identity else 'session-1'}}
    def close(self): self.closes+=1


def fixture(lease=None):
    projection=Projection(); verifier=InvocationVerifier(lambda context,*args:context.facts)
    records=Records(projection,verifier); client=Client(); opens=[]
    def open_channel(roots,facts):
        assert roots=={'cwd':'/isolated'} and projection.binding.state=='opening'
        opens.append(roots); return client
    provider=PiRuntimeProvider(definition_ref=DEFINITION,implementation_digest=DIGEST,
        unit_records=records,projection=projection,verifier=verifier,
        channel_factory=SimpleNamespace(open=open_channel),lease_port=lease)
    context=SimpleNamespace(facts={'providerRef':PROVIDER,'targetRef':NODE,'inputDigest':'digest',
                         'action':'start','query':False,'managementEpoch':1})
    return provider,projection,records,client,context,opens


def test_prepare_uses_verified_fixed_roots_not_caller_path():
    provider,projection,records,client,context,opens=fixture()
    plan={'context':{'nodeRef':NODE,'privateRootFacts':{'cwd':'/attacker'}}}
    assert provider.prepare(plan,context)['unitRef']==UNIT
    assert records.reserves==1 and not opens and not client.calls


def test_wrong_plan_node_refuses_reservation():
    provider,projection,records,client,context,opens=fixture()
    with pytest.raises(PiProviderRefused): provider.prepare({'context':{'nodeRef':{}}},context)
    assert records.reserves==0


def test_original_binding_opens_before_native_calls_and_confirms_session():
    provider,projection,records,client,context,opens=fixture()
    result=provider.start({'unitRef':UNIT},context)
    assert result['nativeBinding']['sessionId']=='session-1'
    assert records.begins==1 and len(opens)==1
    assert client.calls==['get_state:initialize','get_state']
    assert not any('prompt' in call for call in client.calls)


@pytest.mark.parametrize('failure',['lost','identity','evidence'])
def test_unknown_creation_never_relaunches_or_kills(failure):
    provider,projection,records,client,context,opens=fixture()
    if failure=='lost': client.fail=True
    elif failure=='identity': client.bad_identity=True
    else: projection.bad_evidence=True
    with pytest.raises(PiProviderRefused,match='unknown'): provider.start({'unitRef':UNIT},context)
    assert projection.binding.state=='unknown'
    assert provider._channels['unit-1'] is client and client.closes==0
    with pytest.raises(RuntimeError,match='existing start'): provider.start({'unitRef':UNIT},context)
    assert len(opens)==1


@pytest.mark.parametrize('revoke_at,expected_calls',[(1,[]),(2,[]),(3,['get_state:initialize']),(4,['get_state:initialize','get_state'])])
def test_each_native_creation_edge_revalidates_original_claim(revoke_at,expected_calls):
    provider,projection,records,client,context,opens=fixture(); projection.revoke_at=revoke_at
    with pytest.raises(PiProviderRefused,match='unknown'): provider.start({'unitRef':UNIT},context)
    assert projection.binding.state=='unknown' and client.calls==expected_calls
    assert client.closes==0


def test_unconfirmed_unit_does_not_grant_access():
    provider,projection,records,client,context,opens=fixture()
    with pytest.raises(PiProviderRefused): provider.describe_access(UNIT)


def test_lease_missing_never_exposes_client():
    provider,projection,records,client,context,opens=fixture(); provider.start({'unitRef':UNIT},context)
    with pytest.raises(PiProviderRefused): provider.connect(UNIT,{'authorized':True})
    assert 'connect' not in provider.descriptor.supported_methods


def test_connection_only_uses_explicit_authorized_lease_port():
    seen=[]; entry=object()
    def bind(unit,lease,client):
        seen.append((unit,lease,client)); return entry
    provider,projection,records,client,context,opens=fixture(SimpleNamespace(bind=bind))
    provider.start({'unitRef':UNIT},context)
    lease=object()
    assert provider.connect(UNIT,lease) is entry
    assert seen==[(UNIT,lease,client)]


def test_foreign_unit_ref_refuses_before_open():
    provider,projection,records,client,context,opens=fixture()
    with pytest.raises(PiProviderRefused): provider.start({'unitRef':{**UNIT,'environmentNamespace':'other'}},context)
    assert not opens and records.begins==0


def test_query_only_original_operation_never_starts():
    provider,projection,records,client,context,opens=fixture()
    context.facts={**context.facts,'query':True,'action':'query'}
    result=provider.query_step({'operationRef':'original'},context)
    assert result['state']=='notCreated' and not opens and not client.calls and records.begins==0


def test_query_rejects_effect_context():
    provider,projection,records,client,context,opens=fixture()
    with pytest.raises(PiProviderRefused): provider.query_step({},context)
    assert not opens


def test_different_core_verifier_disables_lifecycle():
    provider,projection,records,client,context,opens=fixture()
    other=InvocationVerifier(lambda context,*args:context.facts)
    provider=PiRuntimeProvider(definition_ref=DEFINITION,implementation_digest=DIGEST,
        unit_records=records,projection=projection,verifier=other,channel_factory=provider.channel_factory)
    assert 'prepare' not in provider.descriptor.supported_methods
    with pytest.raises(PiProviderRefused): provider.start({'unitRef':UNIT},context)


def test_preparation_materials_not_silently_swallowed():
    provider,projection,records,client,context,opens=fixture()
    with pytest.raises(PiProviderRefused):
        provider.plan_preparation({'manifest':{'declarations':[{'requirement':'required'}]}},
            {'privateRootFacts':{'cwd':'/isolated'}},{'operationRef':'original'})
    assert not opens


@pytest.mark.parametrize('forgery',['raw','source','owner','environment','extra','missing'])
@pytest.mark.parametrize('entry',['start','access','connect','inspect'])
def test_complete_original_unit_ref_required_before_native_effect(forgery,entry):
    from copy import deepcopy
    provider,projection,records,client,context,opens=fixture(SimpleNamespace(bind=lambda *args:object()))
    ref=deepcopy(UNIT)
    if forgery=='raw': ref={key:ref[key] for key in ('environmentNamespace','unitId')}
    elif forgery=='source': ref['sourceRevision']='forged-source'
    elif forgery=='owner': ref['ownerProviderRef']['generation']=999
    elif forgery=='environment': ref['environmentNamespace']='foreign'
    elif forgery=='extra': ref['extra']='field'
    else: del ref['ownerProviderRef']
    with pytest.raises(PiProviderRefused):
        if entry=='start': provider.start({'unitRef':ref},context)
        elif entry=='access': provider.describe_access(ref)
        elif entry=='connect': provider.connect(ref,object())
        else: provider.inspect_unit(ref)
    assert not opens and records.begins==0 and not client.calls


def test_prepare_returns_exact_original_reservation_source_ref():
    provider,projection,records,client,context,opens=fixture()
    result=provider.prepare({'context':{'nodeRef':NODE}},context)
    assert result['unitRef']==projection.unit.public_ref
    assert set(result['unitRef'])=={'environmentNamespace','unitId','ownerProviderRef','sourceRevision'}


@pytest.mark.parametrize('wrong',['unit','target','epoch'])
def test_publication_projection_cannot_change_original_unit_target_or_epoch(wrong):
    from pacthold.agents.nodes.directory import DirectoryBindingRef
    provider,projection,records,client,context,opens=fixture()
    value={'unitRef':UNIT,'configurationTargetRef':projection.unit.configuration_target_ref,
        'managementEpoch':1,'directoryBindingRef':DirectoryBindingRef('test','directory',1,'sha256:'+'a'*64),
        'sourceRevision':'observation-1','evidenceRef':{'environmentNamespace':'test','evidenceId':'owner'}}
    if wrong=='unit': value['unitRef']={**UNIT,'sourceRevision':'other'}
    elif wrong=='target': value['configurationTargetRef']={**value['configurationTargetRef'],'scopeId':'other'}
    else: value['managementEpoch']=2
    projection.publication_facts=lambda ref:value
    with pytest.raises(PiProviderRefused): provider.inspect_unit(UNIT)
    assert not opens and not client.calls


def test_boolean_owner_generation_cannot_bypass_full_unit_comparison():
    from copy import deepcopy
    provider,projection,records,client,context,opens=fixture()
    ref=deepcopy(UNIT); ref['ownerProviderRef']['generation']=True
    # Original fixture provider has no generation, so use an explicit int-vs-bool
    # controlled original owner reference while retaining all provenance fields.
    projection.unit.public_ref=deepcopy(UNIT)
    projection.unit.public_ref['ownerProviderRef']['generation']=1
    with pytest.raises(PiProviderRefused): provider.start({'unitRef':ref},context)
    assert not opens and records.begins==0


def test_publication_uses_complete_original_configuration_target():
    from pacthold.agents.nodes.directory import DirectoryBindingRef
    provider,projection,records,client,context,opens=fixture()
    projection.publication_facts=lambda ref:{'unitRef':UNIT,'configurationTargetRef':TARGET,
        'managementEpoch':1,'directoryBindingRef':DirectoryBindingRef('test','directory',1,'sha256:'+'a'*64),
        'sourceRevision':'observed-1','evidenceRef':{'environmentNamespace':'test','evidenceId':'owner'}}
    assert provider.inspect_unit(UNIT).configuration_target_ref==projection.unit.configuration_target_ref
    assert not opens
