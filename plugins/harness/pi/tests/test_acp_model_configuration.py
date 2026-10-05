"""Pure historical ACP plans do not establish native routing application."""
from dataclasses import replace
import pytest
from ordessa_harness_api.model_compilation import AdapterContext, TargetHandle, ChoiceRequest, RequestParams, CompileIntent, BindSecret, Refusal
from ordessa_harness_pi.acp_model_configuration import PiAdapter


def context(session='original-session', target=None):
    return AdapterContext(target or TargetHandle('pi','instance','fixture'),'0.5.1',{'native_session_id':session})


def choice(**flags):
    return ChoiceRequest('fixture','desired','https://fixture.test','openai-chat','ref://fixture','acme',
                         {'provider_in_instance':True,**flags})


def sample():
    return {'providers':{'acme':{'baseUrl':'https://original.test','api':'openai-completions',
        'models':[{'id':'desired','maxTokens':4096,'cost':{'input':1}},{'id':'sibling','maxTokens':2048}], 'custom':'preserved'}}}


def retry():
    return RequestParams.from_record({'retry':{'enabled':True,'maxRetries':3,'provider':{'maxRetries':2,'maxRetryDelayMs':1000}}})


def test_existing_provider_switches_model_and_add_provider_keeps_model_and_ref():
    adapter=PiAdapter(); plan=adapter.compile(context(),{},choice())
    assert plan.reconfiguration=='session-local'
    assert [(x.field_path,x.typed_value) for x in plan.intents]==[(('session','model'),'desired')]
    plan=adapter.compile(context(),{},choice(provider_in_instance=False))
    assert plan.reconfiguration=='restart-resume' and plan.resume_expectation=={'native_session_id':'original-session'}
    assert any(isinstance(x,CompileIntent) and x.field_path==('providers','acme') for x in plan.intents)
    assert any(isinstance(x,CompileIntent) and x.field_path==('session','model') and x.typed_value=='desired' for x in plan.intents)
    assert any(isinstance(x,BindSecret) and x.secret_ref=='ref://fixture' for x in plan.intents)


def test_retry_only_keeps_provider_untouched_and_desired_model_in_plan():
    before=sample(); plan=PiAdapter().compile(context(),before,replace(choice(),params=retry()))
    assert plan.reconfiguration=='restart-resume'
    assert not any(isinstance(x,CompileIntent) and x.field_path==('providers','acme') for x in plan.intents)
    assert any(isinstance(x,CompileIntent) and x.field_path==('session','model') and x.typed_value=='desired' for x in plan.intents)
    intent=next(x for x in plan.intents if isinstance(x,CompileIntent) and x.field_path==('retry',))
    assert intent.target_handle==TargetHandle('pi','instance','pi.settings.json')
    assert intent.typed_value==retry().retry
    assert before==sample()


def test_credential_only_binds_reference_without_replacing_models():
    plan=PiAdapter().compile(context(),sample(),choice(credential_changed=True))
    assert plan.reconfiguration=='restart-resume'
    assert not any(isinstance(x,CompileIntent) and x.field_path==('providers','acme') for x in plan.intents)
    assert any(isinstance(x,BindSecret) and x.secret_ref=='ref://fixture' for x in plan.intents)
    assert any(isinstance(x,CompileIntent) and x.field_path==('session','model') for x in plan.intents)


def test_budget_preserves_siblings_metadata_and_model():
    before=sample(); plan=PiAdapter().compile(context(),before,replace(choice(),params=RequestParams(max_tokens=1024)))
    golden=next(x for x in plan.intents if isinstance(x,CompileIntent) and x.field_path==('providers','acme')).typed_value
    assert golden['models']==[{'id':'desired','maxTokens':1024,'cost':{'input':1}},{'id':'sibling','maxTokens':2048}]
    assert golden['custom']=='preserved' and golden['baseUrl']=='https://fixture.test'
    assert before==sample()
    assert any(isinstance(x,CompileIntent) and x.field_path==('session','model') for x in plan.intents)


def test_budget_duplicate_target_refuses_ambiguous_subtree():
    before=sample();before['providers']['acme']['models'].append({'id':'desired','maxTokens':2})
    assert isinstance(PiAdapter().compile(context(),before,replace(choice(),params=RequestParams(max_tokens=1024))),Refusal)


@pytest.mark.parametrize('flag',[True,1,{},'true'])
def test_credential_change_needs_reference_and_boolean(flag):
    assert isinstance(PiAdapter().compile(context(),{},replace(choice(credential_changed=flag),credential_ref=None)),Refusal)


@pytest.mark.parametrize('flag',[1,{},'true',None])
def test_untyped_provider_observation_refuses(flag):
    assert isinstance(PiAdapter().compile(context(),{},choice(provider_in_instance=flag)),Refusal)


@pytest.mark.parametrize('target',[TargetHandle('codex','instance','fixture'),TargetHandle('pi','project','fixture'),TargetHandle('pi','instance',None)])
def test_foreign_or_untyped_target_refuses(target):
    adapter=PiAdapter();ctx=context(target=target)
    assert isinstance(adapter.compile(ctx,{},choice()),Refusal)
    assert adapter.verify(ctx,{'desired_model':'desired','readback':{'model':'desired'},'native_session_id':'original-session'}).verdict=='unknown'


@pytest.mark.parametrize('value',[None,'',True,1,'bad\x7fidentity','bad\ud800identity'])
def test_missing_or_untyped_session_never_matches(value):
    assert PiAdapter().verify(context(value),{'desired_model':'desired','readback':{'model':'desired'},'native_session_id':value}).verdict=='unknown'


@pytest.mark.parametrize('expected,actual',[(None,None),(True,1),('','')])
def test_missing_or_untyped_model_never_matches(expected,actual):
    assert PiAdapter().verify(context(),{'desired_model':expected,'readback':{'model':actual},'native_session_id':'original-session'}).verdict=='unknown'


@pytest.mark.parametrize('reference',[True,{},1,'bad\x00ref'])
def test_untyped_reference_refuses(reference):
    assert isinstance(PiAdapter().compile(context(),{},replace(choice(provider_in_instance=False),credential_ref=reference)),Refusal)


def test_same_session_readback_match_wrong_session_mismatch_and_ack_unknown():
    adapter=PiAdapter();observed={'desired_model':'desired','readback':{'model':'desired'},'native_session_id':'original-session'}
    assert adapter.verify(context(),observed).verdict=='match'
    observed['native_session_id']='replacement-session'
    assert adapter.verify(context(),observed).verdict=='mismatch'
    assert adapter.verify(context(),{'desired_model':'desired','rpc_ack':True}).verdict=='unknown'


@pytest.mark.parametrize('brand',[{}, {'credential_changed':False}])
def test_missing_provider_observation_cannot_be_assumed_absent(brand):
    assert isinstance(PiAdapter().compile(context(),{},replace(choice(),brand_fields=brand)),Refusal)


@pytest.mark.parametrize('params',[RequestParams(max_tokens=True),RequestParams(max_tokens=0),RequestParams(retry={}),{},RequestParams(retry={'enabled':1,'maxRetries':2,'provider':{'maxRetries':0,'maxRetryDelayMs':0}})])
def test_direct_malformed_params_refuse_without_crash(params):
    assert isinstance(PiAdapter().compile(context(),sample(),replace(choice(),params=params)),Refusal)


@pytest.mark.parametrize('endpoint',[None,True,'bad\x7fendpoint','bad\ud800endpoint'])
def test_provider_add_requires_valid_endpoint(endpoint):
    assert isinstance(PiAdapter().compile(context(),{},replace(choice(provider_in_instance=False),endpoint=endpoint)),Refusal)


def test_budget_keeps_observed_endpoint_when_choice_does_not_change_it():
    desired=replace(choice(),endpoint=None,params=RequestParams(max_tokens=1024))
    plan=PiAdapter().compile(context(),sample(),desired)
    golden=next(x for x in plan.intents if isinstance(x,CompileIntent) and x.field_path==('providers','acme')).typed_value
    assert golden['baseUrl']=='https://original.test'


def test_unobserved_budget_endpoint_refuses():
    before=sample();del before['providers']['acme']['baseUrl']
    desired=replace(choice(),endpoint=None,params=RequestParams(max_tokens=1024))
    assert isinstance(PiAdapter().compile(context(),before,desired),Refusal)


def test_same_provider_endpoint_change_preserves_models_and_updates_routing():
    before=sample();plan=PiAdapter().compile(context(),before,choice(endpoint_changed=True))
    assert plan.reconfiguration=='restart-resume'
    golden=next(x for x in plan.intents if isinstance(x,CompileIntent) and x.field_path==('providers','acme')).typed_value
    assert golden['baseUrl']=='https://fixture.test' and golden['models']==before['providers']['acme']['models']
    assert before==sample()


def test_endpoint_change_without_native_provider_sample_refuses():
    assert isinstance(PiAdapter().compile(context(),{},choice(endpoint_changed=True)),Refusal)


@pytest.mark.parametrize('field,value',[('apiKey','sk-plaintext-fixture'),('headers',{'Authorization':'Bearer plaintext-fixture'})])
def test_native_credential_content_does_not_enter_budget_intents(field,value):
    before=sample();before['providers']['acme'][field]=value
    result=PiAdapter().compile(context(),before,replace(choice(),params=RequestParams(max_tokens=1024)))
    assert isinstance(result,Refusal)
    assert 'plaintext-fixture' not in repr(result)


def test_native_env_reference_is_preserved_without_secret_content():
    before=sample();before['providers']['acme']['apiKey']='$DEEPSEEK_API_KEY'
    result=PiAdapter().compile(context(),before,replace(choice(),params=RequestParams(max_tokens=1024)))
    golden=next(x for x in result.intents if isinstance(x,CompileIntent) and x.field_path==('providers','acme')).typed_value
    assert golden['apiKey']=='$DEEPSEEK_API_KEY'
