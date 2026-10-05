"""C: explicit trusted ports and native responses; no Pi/model execution."""
from contextlib import nullcontext
from types import SimpleNamespace
from copy import deepcopy
from datetime import datetime, timezone
import pytest

from pacthold.agents.configuration import ConfigurationChangeRequest, ConfigurationItemResult, ConfigurationChangeResult, UnitInspection
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import InvocationVerifier
from ordessa_harness_pi import PiRuntimeProvider, PiProviderRefused


class Context:
    facts={'inputDigest':'digest-1'}


class Owner:
    def __init__(self):
        self.provider = {'environmentNamespace':'pi-test', 'providerId':'pi', 'generation':1}
        self.ref = {'environmentNamespace':'pi-test', 'unitId':'unit-1', 'ownerProviderRef':self.provider,'sourceRevision':'controlled-unit-source-1'}
        self.target = {'environmentNamespace':'pi-test', 'scopeId':'scope-1','revision':'1','ownerProviderRef':self.provider,'sourceRevision':'controlled-scope-source-1'}
        self.state = {'sessionId':'session-1', 'model':{'provider':'native','id':'old'}, 'thinkingLevel':'off'}
        self.commands=[]; self.ack_only=False; self.lost=False; self.permitted=True; self.session_valid=True
        self.inspection = UnitInspection(self.ref,self.provider,self.target,
            DirectoryBindingRef('pi-test','directory',1,'sha256:'+'a'*64),1,'owned','unit-1',
            datetime.now(timezone.utc).isoformat(),{'environmentNamespace':'pi-test','evidenceId':'unit'})
    def read_unit(self, ref): return SimpleNamespace(public_ref=self.ref,configuration_target_ref=self.target)
    def inspect_unit(self, ref): return self.inspection
    def channel(self, ref): return self
    def serialize_configuration(self, ref): return nullcontext()
    def verify_session(self, ref, session): return self.session_valid and session=='session-1'
    def revalidate_write(self, context, facts, unit): return self.permitted
    def authorize(self, context, action, provider, target, digest):
        if not self.permitted: raise PiProviderRefused('revoked')
        return {'operationRef':'operation-1','inputDigest':'digest-1','providerRef':self.provider,
                'managementEpoch':1,'query':action=='query','action':action}
    def command(self, command, **fields):
        self.commands.append((command,fields))
        if command=='get_state': return {'data':deepcopy(self.state)}
        if self.lost: raise TimeoutError()
        if not self.ack_only:
            if command=='set_model': self.state['model']={'provider':fields['provider'],'id':fields['modelId']}
            else: self.state['thinkingLevel']=fields['level']
        return {'success':True}


class Confirmations:
    def __init__(self): self.receipts=[]; self.original=None; self.fail=False
    def record(self, facts, unit, declaration, before, after):
        if self.fail: raise RuntimeError('receipt unavailable')
        self.receipts.append((facts, declaration, before, after))
        return {'environmentNamespace':'pi-test','evidenceId':'original-attempt-1'}
    def read(self, facts, unit, operation): return self.original


@pytest.fixture
def setup():
    owner, confirmations=Owner(),Confirmations()
    provider=PiRuntimeProvider(definition_ref={'environmentNamespace':'pi-test','definitionId':'pi','revision':'1'},
                    implementation_digest='sha256:'+'b'*64, owner=owner,confirmations=confirmations, verifier=InvocationVerifier(owner.authorize))
    return provider,owner,confirmations


def declaration(kind='pi.model', payload=None, requirement='required', declaration_id='model'):
    return {'declarationId':declaration_id,'configurationKind':kind,'schemaVersion':'1','action':'value',
            'requirement':requirement,'payload':payload or {'provider':'native','model':'new'}}


def change(provider, owner, *declarations):
    snapshot=provider.inspect_configuration(owner.ref)
    return ConfigurationChangeRequest('request-1',snapshot.source_revision,tuple(declarations or [declaration()]))


def test_advertises_only_wired_capabilities(setup):
    provider,owner,_=setup
    assert provider.descriptor.provider_id=='pi'
    assert 'apply_configuration' in provider.descriptor.supported_methods
    for method in ('prepare','start','connect','stop','release','recover'):
        assert method not in provider.descriptor.supported_methods
        with pytest.raises(PiProviderRefused): getattr(provider,method)(None,None)
    assert owner.commands==[]


def test_actual_readback_and_durable_owner_confirmation(setup):
    provider,owner,receipts=setup
    before=provider.inspect_configuration(owner.ref)
    result=provider.apply_configuration(owner.ref,change(provider,owner),Context())
    assert result.overall_outcome=='applied'
    assert owner.commands[-2:]==[('set_model',{'provider':'native','modelId':'new'}),('get_state',{})]
    assert result.confirmed_snapshot.configuration['pi.model']['model']=='new'
    assert before.configuration['pi.model']['model']=='old'
    assert len(receipts.receipts)==1
    assert result.item_results[0].confirmation['requestDigest']=='digest-1'


@pytest.mark.parametrize('failure',['ack_only','lost','receipt'])
def test_ack_missing_receipt_or_disconnect_never_applied(setup,failure):
    provider,owner,receipts=setup
    request=change(provider,owner)
    if failure=='receipt': receipts.fail=True
    else: setattr(owner,failure,True)
    result=provider.apply_configuration(owner.ref,request,Context())
    assert result.overall_outcome=='unknown' and result.confirmed_snapshot is None
    assert sum(cmd=='set_model' for cmd,_ in owner.commands)==1


def test_native_external_edit_version_conflicts_without_write(setup):
    provider,owner,_=setup
    request=change(provider,owner)
    owner.state['model']['id']='external'
    result=provider.apply_configuration(owner.ref,request,Context())
    assert result.overall_outcome=='conflict'
    assert all(cmd=='get_state' for cmd,_ in owner.commands)


def test_authority_revoked_before_native_effect(setup):
    provider,owner,_=setup
    request=change(provider,owner); owner.permitted=False
    with pytest.raises(PiProviderRefused): provider.apply_configuration(owner.ref,request,Context())
    assert all(cmd=='get_state' for cmd,_ in owner.commands)


def test_query_reads_original_receipt_never_current_matching_state(setup):
    provider,owner,receipts=setup
    request=change(provider,owner)
    result=provider.apply_configuration(owner.ref,request,Context())
    with pytest.raises(PiProviderRefused): provider.query_change(owner.ref,'operation-1',Context())
    receipts.original=result; owner.state['model']['id']='later-external'
    commands=list(owner.commands)
    assert provider.query_change(owner.ref,'operation-1',Context())==result
    assert owner.commands==commands


def test_missing_native_fields_unknown_not_filled_from_profile(setup):
    provider,owner,_=setup
    del owner.state['model']; del owner.state['thinkingLevel']
    snapshot=provider.inspect_configuration(owner.ref)
    assert not snapshot.configuration
    assert set(snapshot.unknown_items)=={'pi.model','pi.thinking'}


def test_session_mismatch_refuses_native_fact(setup):
    provider,owner,_=setup; owner.session_valid=False
    with pytest.raises(PiProviderRefused): provider.inspect_configuration(owner.ref)


def test_optional_unsupported_is_explicit_partial(setup):
    provider,owner,_=setup
    request=change(provider,owner,declaration(),declaration('absent',{},'optional','optional'))
    result=provider.apply_configuration(owner.ref,request,Context())
    assert result.overall_outcome=='partial'
    assert [i.outcome for i in result.item_results]==['applied','rejected']


def test_secret_native_model_metadata_never_enters_snapshot(setup):
    provider,owner,_=setup
    owner.state['model'].update(apiKey='private-test-key',baseUrl='secret-url')
    snapshot=provider.inspect_configuration(owner.ref)
    assert 'private-test-key' not in repr(snapshot.to_dict())
    assert 'secret-url' not in repr(snapshot.to_dict())


def test_missing_required_declaration_prevents_all_native_writes(setup):
    provider,owner,_=setup
    request=change(provider,owner,declaration(),declaration('absent',{},'required','absent'))
    result=provider.apply_configuration(owner.ref,request,Context())
    assert result.overall_outcome=='rejected'
    assert all(cmd=='get_state' for cmd,_ in owner.commands)


def test_thinking_native_field_is_level(setup):
    provider,owner,_=setup
    request=change(provider,owner,declaration('pi.thinking',{'level':'low'},declaration_id='thinking'))
    result=provider.apply_configuration(owner.ref,request,Context())
    assert result.overall_outcome=='applied'
    assert ('set_thinking_level',{'level':'low'}) in owner.commands


def test_each_setter_rechecks_current_writer_before_dispatch(setup):
    provider,owner,_=setup
    request=change(provider,owner,declaration(),declaration('pi.thinking',{'level':'low'},declaration_id='thinking'))
    count=[]
    def revalidate(context,facts,unit):
        count.append(unit)
        return len(count)==1
    owner.revalidate_write=revalidate
    result=provider.apply_configuration(owner.ref,request,Context())
    assert [item.outcome for item in result.item_results]==['applied','unknown']
    assert len(count)==2
    assert all(command!='set_thinking_level' for command,_ in owner.commands)


def test_missing_owner_does_not_advertise_instance_configuration_support():
    provider=PiRuntimeProvider(definition_ref={'environmentNamespace':'pi-test','definitionId':'pi','revision':'1'},
                             implementation_digest='sha256:'+'b'*64)
    assert all(description.support_status=='unknown' and not description.supported_actions
               for description in provider.describe_configuration({'environmentNamespace':'pi-test','unitId':'missing'}))
    assert 'apply_configuration' not in provider.descriptor.supported_methods
    with pytest.raises(PiProviderRefused): provider.inspect_configuration({'environmentNamespace':'pi-test','unitId':'missing'})


def test_incomplete_trusted_ports_refused_at_construction():
    with pytest.raises(PiProviderRefused):
        PiRuntimeProvider(definition_ref={'environmentNamespace':'pi-test','definitionId':'pi','revision':'1'},
                          implementation_digest='sha256:'+'b'*64,owner=object())


@pytest.mark.parametrize('forgery',['raw','source','owner','environment','extra','missing'])
@pytest.mark.parametrize('entry',['inspect','snapshot','describe','apply','query'])
def test_configuration_entries_reject_counterfeit_original_unit_ref(setup,forgery,entry):
    provider,owner,confirmations=setup
    ref=deepcopy(owner.ref)
    if forgery=='raw': ref={key:ref[key] for key in ('environmentNamespace','unitId')}
    elif forgery=='source': ref['sourceRevision']='forged-source'
    elif forgery=='owner': ref['ownerProviderRef']['generation']=999
    elif forgery=='environment': ref['environmentNamespace']='foreign'
    elif forgery=='extra': ref['extra']='field'
    else: del ref['ownerProviderRef']
    with pytest.raises(PiProviderRefused):
        if entry=='inspect': provider.inspect_unit(ref)
        elif entry=='snapshot': provider.inspect_configuration(ref)
        elif entry=='describe': provider.describe_configuration(ref)
        elif entry=='apply':
            request=ConfigurationChangeRequest('request-1','unverified-source',(declaration(),))
            provider.apply_configuration(ref,request,Context())
        else: provider.query_change(ref,'operation-1',Context())
    assert not owner.commands and not confirmations.receipts


@pytest.mark.parametrize('forgery',['raw','source','owner','boolean-generation','environment','extra'])
def test_inspection_cannot_substitute_configuration_target_source(setup,forgery):
    from dataclasses import replace
    provider,owner,confirmations=setup
    original_target=deepcopy(owner.target)
    altered=deepcopy(owner.target)
    if forgery=='raw': altered={key:altered[key] for key in ('environmentNamespace','scopeId','revision')}
    elif forgery=='source': altered['sourceRevision']='forged-source'
    elif forgery=='owner': altered['ownerProviderRef']['generation']=999
    elif forgery=='boolean-generation': altered['ownerProviderRef']['generation']=True
    elif forgery=='environment': altered['environmentNamespace']='foreign'
    else: altered['extra']='field'
    # Inspection DTO cannot accept foreign environment at all; all other source
    # changes remain structurally valid but must fail same original owner check.
    if forgery=='environment':
        with pytest.raises(ValueError): replace(owner.inspection,configuration_target_ref=altered)
    else:
        owner.inspection=replace(owner.inspection,configuration_target_ref=altered)
        with pytest.raises(PiProviderRefused): provider.inspect_configuration(owner.ref)
    assert owner.target==original_target and not owner.commands and not confirmations.receipts


def test_boolean_owner_generation_cannot_equal_original_integer_unit_generation(setup):
    provider,owner,_=setup
    ref=deepcopy(owner.ref); ref['ownerProviderRef']['generation']=True
    with pytest.raises(PiProviderRefused): provider.inspect_configuration(ref)
    assert not owner.commands


def test_confirmed_scope_is_complete_original_target(setup):
    provider,owner,_=setup
    result=provider.apply_configuration(owner.ref,change(provider,owner),Context())
    assert result.confirmed_snapshot.scope_ref==owner.read_unit(owner.ref).configuration_target_ref
    assert result.item_results[0].confirmation['scopeRef']==owner.target
    assert set(result.item_results[0].confirmation['scopeRef'])=={'environmentNamespace','scopeId','revision','ownerProviderRef','sourceRevision'}
