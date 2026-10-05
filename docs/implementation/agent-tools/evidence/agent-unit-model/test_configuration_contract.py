"""AU001 controlled structural contracts; no native provider/process/effects."""
from dataclasses import replace
import pytest
from pacthold.agents.public import (
 ApplicationPolicy, ConfigurationChangeRequest, ConfigurationDescription,
 ConfigurationSnapshot, ConfigurationItemResult, ConfigurationChangeResult,
 RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
)

UNIT={'environmentNamespace':'env','unitId':'u','sourceRevision':'1'}
SCOPE={'environmentNamespace':'env','scopeId':'scope'}
EVIDENCE={'environmentNamespace':'env','evidenceId':'readback'}
DECL={'declarationId':'model','configurationKind':'model','schemaVersion':'1','action':'value','requirement':'required','payload':{'modelId':'controlled'}}


def request(): return ConfigurationChangeRequest('request','native-1',(DECL,))
def snapshot():
 return ConfigurationSnapshot(UNIT,SCOPE,'native-2','2026-10-05T01:00:00Z',{'model':{'modelId':'controlled'}},('tools',),EVIDENCE,'ownerSerialized')
def confirmation(): return {'operationRef':'op','unitRef':UNIT,'scopeRef':SCOPE,'requestDigest':'fixed-digest','evidenceRef':EVIDENCE}


def test_explicit_roundtrip_and_default_no_restart_or_defer():
 value=request()
 assert value.to_dict()['applicationPolicy']=={'allowDeferred':False,'allowRestart':False}
 assert ConfigurationChangeRequest.from_dict(value.to_dict())==value
 with pytest.raises(TypeError): value.declarations[0]['payload']['modelId']='other'

@pytest.mark.parametrize('change',[
 {'expectedConfigurationRevision':None},{'expectedConfigurationRevision':''},
 {'requestId':' '},{'applicationPolicy':{'allowDeferred':1,'allowRestart':False}},
 {'applicationPolicy':{'allowDeferred':False,'allowRestart':False,'autoRetry':True}},
 {'nodeRef':UNIT},{'declarations':[]},
])
def test_invalid_or_authority_bearing_request_refused(change):
 value=request().to_dict(); value.update(change)
 with pytest.raises(ValueError): ConfigurationChangeRequest.from_dict(value)

@pytest.mark.parametrize('change',[
 {'action':'unset'},{'action':'reset'},{'configurationKind':''},{'requirement':'maybe'},
 {'payload':{'apiKey':'plain-secret'}},{'payload':{'password':'plain-secret'}},
 {'resourceRefs':[{'environmentNamespace':'other','id':'x'},{'environmentNamespace':'env','id':'y'}]},
])
def test_existing_declaration_contract_is_retained(change):
 value=dict(DECL); value.update(change)
 with pytest.raises(ValueError): ConfigurationChangeRequest('request','native-1',(value,))


def test_reset_and_secret_ref_stay_profile_vocabulary():
 reset={k:v for k,v in DECL.items() if k!='payload'}; reset['action']='reset'
 assert ConfigurationChangeRequest('request','native-1',(reset,)).declarations[0]['action']=='reset'
 ref={'ref':'opaque','revision':'1','owner_namespace':'env','access_purpose':'native-config'}
 value=dict(DECL,payload={'apiKey':{'secretRef':ref}})
 assert ConfigurationChangeRequest('request','native-1',(value,)).to_dict()['declarations'][0]['payload']['apiKey']=={'secretRef':ref}

@pytest.mark.parametrize('fields',[
 {'configuration':{'desired':{'modelId':'profile'}}},
 {'configuration':{'pending':{'modelId':'new'}}},
 {'configuration':{'apiKey':'plain-secret'}},
 {'unknown_items':('model',)}, {'source_revision':''},
 {'observed_at':'2026-10-05T01:00:00'},
 {'comparison_guarantee':'globalAtomic'},
 {'scope_ref':{'environmentNamespace':'other','scopeId':'scope'}},
 {'confirmation_evidence':{'environmentNamespace':'env'}},
])
def test_snapshot_cannot_invent_actual_or_cas_guarantee(fields):
 with pytest.raises(ValueError): replace(snapshot(),**fields)


def test_ack_is_not_applied_and_confirmation_is_bound():
 with pytest.raises(ValueError): ConfigurationItemResult('model','applied')
 with pytest.raises(ValueError): ConfigurationItemResult('model','applied',{'ack':True})
 with pytest.raises(ValueError): ConfigurationChangeResult('other-op',(ConfigurationItemResult('model','applied',confirmation()),))
 with pytest.raises(ValueError): ConfigurationChangeResult('op',(ConfigurationItemResult('model','applied',confirmation()),),replace(snapshot(),scope_ref={'environmentNamespace':'env','scopeId':'other'}))

@pytest.mark.parametrize('outcome',['deferred','restartRequired','rejected','conflict','unknown'])
def test_non_applied_does_not_require_fabricated_snapshot(outcome):
 result=ConfigurationChangeResult('op',(ConfigurationItemResult('model',outcome),))
 assert result.overall_outcome==outcome and result.confirmed_snapshot is None


def test_partial_preserves_each_item_and_snapshot_source():
 result=ConfigurationChangeResult('op',(ConfigurationItemResult('model','applied',confirmation()),ConfigurationItemResult('tools','unknown')),snapshot())
 assert result.to_dict()['overallOutcome']=='partial'
 assert result.to_dict()['itemResults'][1]['outcome']=='unknown'
 assert result.confirmed_snapshot.source_revision=='native-2'
 with pytest.raises(TypeError): result.confirmed_snapshot.configuration['model']['modelId']='fake'


def test_explicit_version_upgrade_rejects_v1_for_new_admission():
 assert RUNTIME_PROVIDER_VERSION=='agent-runtime/2'
 definition={'environmentNamespace':'env','definitionId':'controlled','revision':'1'}
 with pytest.raises(ValueError): RuntimeProviderDescriptor('controlled','agent-runtime/1',definition,'sha256:'+'a'*64)


def test_wire_version_upgrade_is_explicit_and_profile_v1_unchanged():
 from pacthold.agents.public import wire_contract, wire_schema_digest, AGENT_MANAGEMENT_CONTRACT_VERSION
 old=wire_contract()
 assert old['contractVersion']=='agent-assembly/1'
 assert 'agents.nodes.configuration.apply' not in old['methods']
 new=wire_contract(AGENT_MANAGEMENT_CONTRACT_VERSION)
 assert new['contractVersion']=='agent-assembly/2'
 assert new['methods']['agents.nodes.configuration.apply']['required']==['nodeRef','change']
 assert new['methods']['agents.nodes.configuration.apply']['effectful'] is True
 assert new['configurationChange']['providerContractVersion']=='agent-runtime/2'
 assert wire_schema_digest()!=wire_schema_digest(AGENT_MANAGEMENT_CONTRACT_VERSION)
 new['methods'].clear()
 assert 'agents.nodes.configuration.apply' in wire_contract(AGENT_MANAGEMENT_CONTRACT_VERSION)['methods']
 with pytest.raises(ValueError): wire_contract('agent-assembly/3')


def test_method_presence_does_not_enable_capability():
 definition={'environmentNamespace':'env','definitionId':'controlled','revision':'1'}
 descriptor=RuntimeProviderDescriptor('controlled',RUNTIME_PROVIDER_VERSION,definition,'sha256:'+'a'*64)
 assert descriptor.to_dict()['supportedMethods']==[]
 admitted=replace(descriptor,supported_methods=('describe_configuration','inspect_configuration'))
 assert admitted.snapshot()==admitted
 assert admitted.to_dict()['supportedMethods']==['describe_configuration','inspect_configuration']
 for methods in [('auto_retry',),('start','start'),['start']]:
  with pytest.raises(ValueError): replace(descriptor,supported_methods=methods)


def test_unknown_revision_remains_unknown_and_cannot_claim_comparison():
 value=replace(snapshot(),source_revision=None,comparison_guarantee='unavailable')
 assert value.to_dict()['sourceRevision'] is None
 with pytest.raises(ValueError): replace(snapshot(),source_revision=None)


def test_unsupported_description_does_not_invent_scope_or_actions():
 value=ConfigurationDescription('tools','1',{},(),None,(),'none','unknown')
 assert value.to_dict()['scope'] is None
 assert value.to_dict()['supportedActions']==[]
 with pytest.raises(ValueError): replace(value,support_status='supported')


def test_unit_inspection_is_owner_projection_without_native_state_machine():
 from pacthold.agents.public import UnitInspection, DirectoryBindingRef
 value=UnitInspection(UNIT,{'environmentNamespace':'env','providerId':'controlled'},SCOPE,
  DirectoryBindingRef('env','binding',1,'sha256:'+'a'*64),0,'borrowed','observation-1','2026-10-05T01:00:00Z',EVIDENCE)
 assert value.ownership=='borrowed' and value.management_epoch==0
 for changes in [{'management_epoch':True},{'ownership':'assumedOwned'},{'directory_binding_ref':None},
                 {'provider_ref':{'environmentNamespace':'other','providerId':'controlled'}}]:
  with pytest.raises(ValueError): replace(value,**changes)


@pytest.mark.parametrize('target',['unitRef','scopeRef'])
@pytest.mark.parametrize('wrong',[True,1.0])
def test_applied_confirmation_snapshot_reference_preserves_json_types(target,wrong):
 fields={'unitRef':'unit_ref','scopeRef':'scope_ref'}
 correct=dict(UNIT if target=='unitRef' else SCOPE,identityNumber=1)
 observed=replace(snapshot(),**{fields[target]:correct})
 proof=confirmation(); proof[target]=dict(correct,identityNumber=wrong)
 with pytest.raises(ValueError):
  ConfigurationChangeResult('op',(ConfigurationItemResult('model','applied',proof),),observed)
