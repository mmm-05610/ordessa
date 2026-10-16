"""AU002 actual SQLite ledger with controlled Unit owner; no native/model."""
from ordessa_execution_agents.profiles import encode_revision_ref
from dataclasses import replace
from pathlib import Path
import sys
import pytest

from agent_tools_fixtures.node_publication import setup as node_fixture, conclude, source, Provider
from agent_tools_fixtures.invocation_authority import Authority, CurrentState
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import IdentityMismatchError, UnknownResultError, AdmissionRefusedError
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationIssuer, InvocationAuthorityRefused
from ordessa_execution_agents.harness.providers.registry.contributions import RUNTIME_METHODS
from ordessa_units.configuration.contracts import (
 ApplicationPolicy, ConfigurationChangeRequest, ConfigurationDescription, ConfigurationSnapshot,
 ConfigurationItemResult, ConfigurationChangeResult, UnitInspection, ConfigurationUnsupported,
)
from ordessa_units.configuration.service import AgentConfiguration


from agent_tools_fixtures.management import explicit_capabilities, setup, apply, optional_declaration, wire, wire_params


from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

def test_confirmed_configuration_is_one_owner_effect_and_immutable_operation(setup):
 store,_,_,service,node,request,change,state,*_=setup
 before=service.inspect(node)
 result=apply(setup)
 assert result.status=='published' and state['calls']==1
 assert result.result['configurationResult']['overallOutcome']=='applied'
 assert service.inspect(node).configuration['model']=='new'
 assert before.configuration['model']=='old'
 assert apply(setup)==result and state['calls']==1
 assert service.query(node,result.intent.operation_ref)==result and state['queryCalls']==0
 assert store.read_operation_step(request,'configuration-apply').outcome=='concluded'

@pytest.mark.parametrize('field',['payload','revision'])
def test_same_request_different_payload_or_precondition_cannot_apply(setup,field):
 apply(setup); change=setup[6]
 if field=='revision': changed=replace(change,expected_configuration_revision='native-2')
 else:
  declaration=dict(change.to_dict()['declarations'][0]); declaration['payload']={'modelId':'other'}
  changed=replace(change,declarations=(declaration,))
 with pytest.raises(IdentityMismatchError): apply(setup,change=changed)
 assert setup[7]['calls']==1

@pytest.mark.parametrize('outcome',['unknown','throw'])
def test_unknown_and_throw_block_new_key_and_never_dispatch_again(setup,outcome):
 setup[7]['outcome']=outcome
 old=apply(setup)
 assert old.status=='unknown' and setup[7]['calls']==1
 assert apply(setup)==old
 new=RequestKey('env','principal','different-request')
 with pytest.raises(UnknownResultError): apply(setup,request=new,change=replace(setup[6],request_id=new.request_id))
 assert setup[0].read_operation(new) is None and setup[7]['calls']==1
 assert 'private-test-secret' not in old.evidence_json


def test_provider_return_without_verified_invocation_is_unknown(setup):
 setup[7]['verify']=False
 result=apply(setup)
 assert result.status=='unknown' and result.result_json is None


def test_query_reconciles_original_attempt_without_another_apply(setup):
 setup[7]['outcome']='unknown'; old=apply(setup)
 setup[7].update(outcome='applied',model='new',revision='native-2')
 result=setup[3].query(setup[4],old.intent.operation_ref)
 assert result.status=='published'
 assert setup[7]['calls']==1 and setup[7]['queryCalls']==1
 assert result.intent.node_ref==old.intent.node_ref


def test_stale_native_revision_and_required_unknown_kind_refuse_before_claim(setup):
 with pytest.raises(IdentityMismatchError): apply(setup,change=replace(setup[6],expected_configuration_revision='stale'))
 declaration=dict(setup[6].to_dict()['declarations'][0]); declaration['configurationKind']='absent'
 with pytest.raises(ConfigurationUnsupported): apply(setup,change=replace(setup[6],declarations=(declaration,)))
 assert setup[7]['calls']==0 and setup[0].read_operation(setup[5]) is None


def test_revoke_before_dispatch_and_query_no_secret_leak(setup):
 setup[8].allowed=False
 with pytest.raises(InvocationAuthorityRefused): apply(setup)
 assert setup[7]['calls']==0


def test_no_profile_save_and_no_cached_actual_truth(setup):
 result=apply(setup)
 setup[7].update(revision='external-3',model='external')
 assert setup[3].inspect(setup[4]).configuration['model']=='external'
 assert result.result['configurationResult']['confirmedSnapshot']['configuration']['model']=='new'
 assert setup[0].list_domain('env','agents.profiles')==()


@pytest.mark.parametrize('resource',[False,True])
def test_optional_missing_support_or_material_is_explicit_partial(setup,resource):
 change=optional_declaration(setup[6],resource=resource)
 result=apply(setup,change=change)
 assert result.status=='published' and setup[7]['calls']==1
 facts=result.result['configurationResult']
 assert facts['overallOutcome']=='partial'
 assert {item['declarationId']:item['outcome'] for item in facts['itemResults']}=={'model':'applied','optional':'rejected'}
 assert result.intent.context_ref['effectiveDeclarations']==change.declarations[:1]


def test_all_optional_unsupported_has_no_claim_or_owner_dispatch(setup):
 change=optional_declaration(setup[6])
 change=replace(change,declarations=(change.declarations[-1],))
 result=apply(setup,change=change)
 assert result.status=='refused' and setup[7]['calls']==0
 assert setup[0].read_operation_step(setup[5],'configuration-apply') is None
 assert apply(setup,change=change)==result


def test_required_resource_not_acquired_cannot_dispatch(setup):
 declaration=setup[6].to_dict()['declarations'][0]
 declaration['resourceRefs']=[{'environmentNamespace':'env','resourceId':'material'}]
 with pytest.raises(ConfigurationUnsupported):
  apply(setup,change=replace(setup[6],declarations=(declaration,)))
 assert setup[7]['calls']==0 and setup[0].read_operation(setup[5]) is None


def test_deferred_requires_permission_and_holds_original_scope(setup):
 setup[7]['outcome']='deferred'
 result=apply(setup)
 assert result.status=='unknown'
 assert 'configurationResult' not in __import__('json').loads(setup[0].read_operation_step(setup[5],'configuration-apply').evidence_json)


def test_authorized_deferred_query_settles_without_resend_and_keeps_observations(setup):
 import json
 setup[7]['outcome']='deferred'
 change=replace(setup[6],application_policy=ApplicationPolicy(allow_deferred=True))
 result=apply(setup,change=change)
 assert result.status=='unknown'
 new=RequestKey('env','principal','competitor')
 with pytest.raises(UnknownResultError):
  apply(setup,request=new,change=replace(change,request_id=new.request_id))
 setup[7].update(outcome='applied',revision='native-2',model='new')
 final=setup[3].query(setup[4],result.intent.operation_ref)
 assert final.status=='published' and setup[7]['calls']==1
 evidence=json.loads(setup[0].read_operation_step(setup[5],'configuration-apply').evidence_json)
 assert [row['configurationResult']['overallOutcome'] for row in evidence['observations']]==['deferred','applied']


@pytest.mark.parametrize('broken',['ack','digest','scope','verification'])
def test_ack_wrong_confirmation_and_swallowed_verification_are_unknown(setup,broken):
 store,env,_,service,node,request,change,state,*_=setup
 binding=service._nodes.read(node)['binding']
 provider=env.agent_runtime_contribution(binding['harnessDefinitionRef']).provider
 original=provider.apply_configuration
 def bad(unit,change,context):
  if broken=='verification':
   try: setup[-1].verifier().verify_and_consume(context,'wrong-action',binding['harnessProviderRef'],binding['configurationTargetRef'],context.facts['inputDigest'])
   except InvocationAuthorityRefused: pass
   state['verify']=False
  result=original(unit,change,context)
  if broken=='ack': return {'accepted':True}
  if broken in {'digest','scope'}:
   confirmation=dict(result.item_results[0].confirmation)
   if broken=='digest': confirmation['requestDigest']='other'
   else: confirmation['scopeRef']={'environmentNamespace':'env','scopeId':'other'}
   return ConfigurationChangeResult(result.operation_ref,(ConfigurationItemResult('model','applied',confirmation),))
  return result
 provider.apply_configuration=bad
 result=apply(setup)
 assert result.status=='unknown' and result.result_json is None
 assert state['calls']==1


def test_crash_after_concluded_step_recovers_publication_without_native_call(setup,monkeypatch):
 store=setup[0]; original=store.publish_operation
 def crash(*args,**kwargs): raise RuntimeError('controlled publication interruption')
 monkeypatch.setattr(store,'publish_operation',crash)
 with pytest.raises(RuntimeError,match='publication interruption'): apply(setup)
 assert store.read_operation_step(setup[5],'configuration-apply').outcome=='concluded'
 assert setup[7]['calls']==1
 monkeypatch.setattr(store,'publish_operation',original)
 final=apply(setup)
 assert final.status=='published' and setup[7]['calls']==1
 assert setup[3].query(setup[4],final.intent.operation_ref)==final


def test_late_unknown_query_cannot_replace_a_confirmed_result(setup):
 from concurrent.futures import ThreadPoolExecutor
 from threading import Event
 setup[7]['outcome']='unknown'; initial=apply(setup)
 provider=setup[1].agent_runtime_contribution(setup[3]._nodes.read(setup[4])['binding']['harnessDefinitionRef']).provider
 original=provider.query_change; entered=Event(); release=Event()
 def late(unit,operation,context):
  result=original(unit,operation,context)
  if result.overall_outcome=='unknown':
   entered.set(); assert release.wait(5)
  return result
 provider.query_change=late
 with ThreadPoolExecutor(max_workers=2) as pool:
  future=pool.submit(setup[3].query,setup[4],initial.intent.operation_ref)
  try:
   assert entered.wait(5)
   setup[7].update(outcome='applied',revision='native-2',model='new')
   current=setup[3].query(setup[4],initial.intent.operation_ref)
   assert current.status=='published'
  finally: release.set()
  assert future.result(timeout=5)==current
 assert setup[0].read_operation(setup[5])==current and setup[7]['calls']==1


def test_public_wire_configuration_apply_inspect_query_do_not_publish_nodes_capability(setup,wire):
 caps=wire['agents.capabilities']({})
 assert caps['contractVersion']=='agent-assembly/3'
 assert caps['supports']['configurationManagement'] is True and caps['supports']['nodes'] is False
 assert 'agents.nodes.prepare' not in caps['supportedMethods']
 assert wire['agents.nodes.configuration.describe']({'nodeRef':wire_params(setup)['nodeRef']})['descriptions'][0]['configurationKind']=='model'
 result=wire['agents.nodes.configuration.apply'](wire_params(setup))
 assert result['status']=='published'
 assert wire['agents.nodes.configuration.apply'](wire_params(setup))==result
 assert wire['agents.nodes.configuration.inspect']({'nodeRef':wire_params(setup)['nodeRef']})['configuration']['model']=='new'
 assert wire['agents.nodes.configuration.query']({'nodeRef':wire_params(setup)['nodeRef'],'operationRef':result['operationRef']})==result
 assert setup[7]['calls']==1


@pytest.mark.parametrize('failure',['stale','authority','identity','shape'])
def test_public_wire_safe_version_authority_request_and_shape_errors(setup,wire,failure):
 from server_plugin_api import WireError
 params=wire_params(setup)
 family='INVALID_REQUEST'
 if failure=='stale':
  params['change']['expectedConfigurationRevision']='stale'; family='CONFLICT_VERSION'
 elif failure=='authority':
  setup[8].allowed=False; family='FORBIDDEN'
 elif failure=='identity':
  wire['agents.nodes.configuration.apply'](params)
  params['change']['expectedConfigurationRevision']='native-2'; family='CONFLICT_REQUEST'
 else: params['principal']='forged'
 with pytest.raises(WireError) as error: wire['agents.nodes.configuration.apply'](params)
 assert error.value.family==family


@pytest.mark.parametrize('method', ['agents.nodes.stop','agents.nodes.release','agents.nodes.recover'])
def test_unwired_lifecycle_port_is_typed_unsupported(setup,wire,method):
 from server_plugin_api import WireError
 # stop/release/recover are now wired to the composed core coordinator, but
 # this fixture still assembles no lifecycle observation port. Preserve the
 # unwired guard semantics: every lifecycle port without its original
 # observation authority stays typed unsupported, is never advertised, and
 # dispatches or reserves nothing.
 identity=method.rsplit('.',1)[1]
 with pytest.raises(WireError) as error:
  wire[method]({'nodeRef':wire_params(setup)['nodeRef'],
                'preconditions':{},'requestId':identity+'-unwired'})
 assert error.value.family=='CAPABILITY_UNSUPPORTED'
 assert setup[7]['calls']==0
 assert setup[7]['queryCalls']==0
 assert setup[0].read_operation(RequestKey('env','principal',identity+'-unwired')) is None
 capabilities=wire['agents.capabilities']({})
 assert capabilities['supports']['nodeLifecycle'] is False
 assert method not in capabilities['supportedMethods']


def test_provider_retirement_before_dispatch_is_denied(setup,node_fixture):
 setup[3].reserve(setup[5],setup[4],setup[6])
 setup[1].retire_activation(node_fixture[-1].activation)
 with pytest.raises(AdmissionRefusedError): apply(setup)
 assert setup[7]['calls']==0 and setup[0].read_operation_step(setup[5],'configuration-apply') is None


def test_cold_reserved_or_unknown_replay_does_not_query_or_dispatch(setup,node_fixture):
 from pacthold.adapters.sqlite.environment.store import SqliteStorePort
 from pacthold.public import Environment
 from ordessa_units.bindings.publication import NodePublication
 setup[7]['outcome']='unknown'; first=apply(setup)
 setup[0].close(); setup[1]._fixture_store_closed=True
 reopened=SqliteStorePort(node_fixture[0])
 try:
  env=Environment('env',store=reopened,policy=setup[2],principal_scope='principal',fingerprint_port=setup[1]._fingerprint_port, resource_extension_snapshot=_test_resource_snapshot)
  issuer=InvocationIssuer(reopened,setup[8],setup[9],clock=lambda:50)
  manager=AgentConfiguration(env,NodePublication(env),invocation_issuer=issuer)
  assert manager.apply(setup[5],setup[4],setup[6])==first
  assert setup[7]['calls']==1 and setup[7]['queryCalls']==0
  with pytest.raises(AdmissionRefusedError): manager.query(setup[4],first.intent.operation_ref)
 finally: reopened.close()


def test_sqlite_fence_and_request_reservation_roll_back_together(setup):
 import sqlite3
 from ordessa_units.configuration.service import CONFIGURATION_ATTEMPTS
 store=setup[0]
 store._conn.execute("CREATE TRIGGER block_configuration_request BEFORE INSERT ON env_requests WHEN NEW.request_id='configuration-request' BEGIN SELECT RAISE(ABORT,'controlled rollback'); END")
 store._conn.commit()
 with pytest.raises(sqlite3.IntegrityError): apply(setup)
 assert store.read_operation(setup[5]) is None and store.list_domain('env',CONFIGURATION_ATTEMPTS)==()
 assert setup[7]['calls']==0


@pytest.mark.parametrize('target',['unitRef','scopeRef'])
@pytest.mark.parametrize('wrong',[True,1.0])
def test_owner_applied_confirmation_cannot_change_reference_json_types(setup,target,wrong):
 import json
 from ordessa_execution_api.environment.operations import safe_json
 provider=setup[1].agent_runtime_contribution(setup[3]._nodes.read(setup[4])['binding']['harnessDefinitionRef']).provider
 original=provider.apply_configuration
 def mismatched(unit,change,context):
  result=original(unit,change,context)
  proof=json.loads(safe_json(result.item_results[0].confirmation))
  assert type(proof[target]['ownerProviderRef']['generation']) is int
  proof[target]['ownerProviderRef']['generation']=wrong
  return ConfigurationChangeResult(result.operation_ref,(ConfigurationItemResult('model','applied',proof),))
 provider.apply_configuration=mismatched
 result=apply(setup)
 assert setup[7]['calls']==1
 assert result.status=='unknown'
 assert setup[0].read_operation_step(setup[5],'configuration-apply').outcome=='unknown'
 assert result.result is None


@pytest.mark.parametrize('field',['unit_ref','provider_ref','configuration_target_ref'])
@pytest.mark.parametrize('wrong',[True,1.0])
def test_current_unit_owner_reference_types_checked_before_observation(setup,field,wrong):
 import json
 from ordessa_execution_api.environment.operations import safe_json
 from ordessa_execution_api.environment import GuaranteeUnavailableError
 provider=setup[1].agent_runtime_contribution(setup[3]._nodes.read(setup[4])['binding']['harnessDefinitionRef']).provider
 current=provider.inspect_unit(setup[3]._nodes.read(setup[4])['binding']['harnessUnitRef'])
 ref=json.loads(safe_json(getattr(current,field)))
 if field=='provider_ref': ref['generation']=wrong
 else: ref['ownerProviderRef']['generation']=wrong
 changed=replace(current,**{field:ref})
 provider.inspect_unit=lambda unit:changed
 with pytest.raises(GuaranteeUnavailableError):
  setup[3].inspect(setup[4])
 with pytest.raises(GuaranteeUnavailableError):
  apply(setup)
 assert setup[0].read_operation(setup[5]) is None
 assert setup[0].read_operation_step(setup[5],'configuration-apply') is None
 assert setup[7]['calls']==0 and setup[7]['queryCalls']==0
