"""AU002 actual SQLite ledger with controlled Unit owner; no native/model."""
from ordessa_agents.profiles import encode_revision_ref
from dataclasses import replace
from pathlib import Path
import sys
import pytest

# Shared controlled owner fixtures are imported from their canonical support modules.
from agent_tools_fixtures.node_publication import setup as node_fixture, conclude, source, Provider
from agent_tools_fixtures.invocation_authority import Authority, CurrentState
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitIdentityMismatch, UnitOperationUnknown, UnitAdmissionRefused
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationIssuer, InvocationAuthorityRefused
from ordessa_agents.harness.providers.registry.contributions import RUNTIME_METHODS
from ordessa_units.configuration.contracts import (
 ApplicationPolicy, ConfigurationChangeRequest, ConfigurationDescription, ConfigurationSnapshot,
 ConfigurationItemResult, ConfigurationChangeResult, UnitInspection, ConfigurationUnsupported,
)
from ordessa_units.configuration.service import AgentConfiguration


@pytest.fixture(autouse=True)
def explicit_capabilities(monkeypatch):
 monkeypatch.setattr(Provider,'descriptor',replace(Provider.descriptor,supported_methods=RUNTIME_METHODS))


@pytest.fixture
def setup(node_fixture):
 _,store,env,policy,_,nodes,_,node,_,_=node_fixture
 env._fingerprint_port=ProtectedFingerprintHmac({'fixture':b'au-unit-hmac'},active_key_id='fixture')
 # The Node lineage must reference a real frozen manifest: whole-manifest
 # updates bind their base to it and read its declarations for the diff.
 from ordessa_agents.profiles.management.service import ProfileService
 base_entry=ProfileService(env).create(profile_id='profile-base',name='Base Profile',
  content={'harnessDefinitionRef':{'environmentNamespace':'env','definitionId':'fixture','revision':'1'},
            'schemaVersion':'1','declarations':[{'declarationId':'model','configurationKind':'model',
              'schemaVersion':'1','action':'value','requirement':'required','payload':{'modelId':'old'}}]},
  request=RequestKey('env','principal','create-profile-base'))
 from dataclasses import replace as _replace
 intent=_replace(node_fixture[8],profile_snapshot_ref=encode_revision_ref(base_entry.current_revision))
 fixture=node_fixture[:8]+(intent,)+node_fixture[9:]
 revision,usages=conclude(fixture)
 published=nodes.publish(fixture[6],'digest',revision,usages)
 binding=published['binding']; provider=env.agent_runtime_contribution(binding['harnessDefinitionRef']).provider
 directory=DirectoryBindingRef('env','directory',1,'sha256:'+'d'*64)
 inspection=UnitInspection(binding['harnessUnitRef'],binding['harnessProviderRef'],binding['configurationTargetRef'],directory,0,'owned','unit-1','2026-10-05T01:00:00Z',source(binding['harnessProviderRef'],'unit-read'))
 current=CurrentState(binding['harnessProviderRef'],directory,inspection.configuration_target_ref)
 authority=Authority(); issuer=InvocationIssuer(store,authority,current,clock=lambda:50)
 state={'revision':'native-1','model':'old','calls':0,'outcome':'applied','verify':True,'queryCalls':0}
 def inspect_configuration(unit):
  return ConfigurationSnapshot(unit,inspection.configuration_target_ref,state['revision'],'2026-10-05T01:00:00Z',{'model':state['model']},(),source(binding['harnessProviderRef'],'config-read'),'ownerSerialized')
 def describe_configuration(unit):
  return (ConfigurationDescription('model','1',{},('value','reset'),'instance',('live','deferred','restart'),'readback','supported'),)
 def effect(unit,change,context):
  facts=context.facts
  if state['verify']:
   issuer.verifier().verify_and_consume(context,'applyConfiguration',binding['harnessProviderRef'],inspection.configuration_target_ref,facts['inputDigest'])
  state['calls']+=1
  if state['outcome']=='throw': raise RuntimeError('private-test-secret')
  if state['outcome']=='applied': state.update(revision='native-2',model='new')
  return result(facts['operationRef'],facts['inputDigest'])
 def result(operation,digest):
  evidence={'operationRef':operation,'unitRef':inspection.unit_ref,'scopeRef':inspection.configuration_target_ref,'requestDigest':digest,'evidenceRef':source(binding['harnessProviderRef'],'native-apply')}
  item=ConfigurationItemResult('model',state['outcome'],evidence if state['outcome']=='applied' else None)
  return ConfigurationChangeResult(operation,(item,),inspect_configuration(inspection.unit_ref) if state['outcome']=='applied' else None)
 def query_change(unit,operation,context):
  facts=issuer.verifier().verify_and_consume(context,'query',binding['harnessProviderRef'],inspection.configuration_target_ref,context.facts['inputDigest'])
  state['queryCalls']+=1
  return result(operation,facts['inputDigest'])
 provider.inspect_unit=lambda unit:inspection
 provider.inspect_configuration=inspect_configuration
 provider.describe_configuration=describe_configuration
 provider.apply_configuration=effect
 provider.query_change=query_change
 coordinator=AgentConfiguration(env,nodes,invocation_issuer=issuer)
 request=RequestKey('env','principal','configuration-request')
 declaration={'declarationId':'model','configurationKind':'model','schemaVersion':'1','action':'value','requirement':'required','payload':{'modelId':'new'}}
 change=ConfigurationChangeRequest(request.request_id,'native-1',(declaration,))
 return store,env,policy,coordinator,node,request,change,state,authority,current,issuer


def apply(parts,**fields):
 _,_,_,service,node,request,change,*_=parts
 return service.apply(fields.get('request',request),fields.get('node',node),fields.get('change',change))


def optional_declaration(change, *, resource=False):
 declaration={'declarationId':'optional','configurationKind':'absent','schemaVersion':'1',
              'action':'value','requirement':'optional','payload':{}}
 if resource:
  declaration['configurationKind']='model'
  declaration['resourceRefs']=[{'environmentNamespace':'env','resourceId':'material'}]
 return replace(change,declarations=change.declarations+(declaration,))


@pytest.fixture
def wire(setup):
 from ordessa_system_access_bindings import agent_core_methods
 from ordessa_units.public import unit_services,AGENT_MANAGEMENT_CONTRACT_VERSION
 services=unit_services(setup[1],invocation_issuer=setup[-1])
 assert services.configuration._issuer is setup[-1]
 return {method.method_id:method.handler for method in agent_core_methods(lambda:setup[1],contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}


def wire_params(setup,change=None):
 from ordessa_units.public import encode_node_ref
 return {'nodeRef':encode_node_ref(setup[4]),'change':(change or setup[6]).to_dict()}


