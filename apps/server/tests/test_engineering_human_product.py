"""Fresh actual2.4 MethodPayload/fullPlan and registered chat source.

The capability catalog and chat replies are explicit synthetic test inputs.
Real instance permissions, original method selection, material validation,
mechanical proof, HTTP/CAS and current guards are exercised; no actual user
answer, model evaluation or Implementation Grant is asserted.
"""
from pathlib import Path
from dataclasses import asdict, replace
import hashlib
import json
import importlib.util

import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.reviews.human import encode_human_review_response
from ordessa_engineering.application.contracts.manual_reviews import ManualReviewReply
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.provenance import SourceRef,SourceLocator,ExcerptCapture,Claim,EvidenceLink
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.approvals.consent import ConversationSource,ConsentPolicyRef
from ordessa_engineering.domain.reviews.targets import Target
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities,CapabilityDescriptor,MethodSource
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant,InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_server.composition.engineering_method_management import OriginalMethodManagement
from ordessa_server.composition.engineering_human_review import human_review_ports_factory
from ordessa_server.composition.engineering_human_source import (
    SelectedHumanReviewPolicy, RegisteredChatHumanReviewAuthority, QUESTION, SOURCE_LIMITATION,expand_explicit_answer,
)
from ordessa_server.composition.engineering_human_preparation import (
    create_fresh_human_material,ConfiguredHumanReviewBindings,prepare_human_plan,prepare_human_presentation,
)

ROOT=Path(__file__).resolve().parents[3]
CANDIDATE=ROOT/'methods/incremental-engineering/candidates/2.4.0'
SCOPE=Scope('human-product-fixture-realm','human-product-fixture-project')
LOCATOR='conversation://synthetic-product-test/complete-checklist'
OPS=('engineering.capabilities','engineering.methods.adopt','engineering.artifacts.create','engineering.reviews.request',
     'engineering.reviews.record','engineering.reviews.get_request','engineering.conversation.attest')
GATE_OPS=(*OPS,'engineering.reviews.query')  # Original internal read permission, not a wire advertisement.
_spec=importlib.util.spec_from_file_location('human_http_fixture',Path(__file__).with_name('test_engineering_slice.py'))
_http=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_http)


def _publish(library):
    catalog=json.loads((CANDIDATE/'contracts/capability-catalog.json').read_bytes())
    assert catalog['fixture_only'] is True
    caps=CompilationCapabilities(tuple(CapabilityDescriptor(r['capability_id'],r['kind'],r['interface_version'],r['contract_digest'],r['contract'])
        for r in catalog['capabilities']),'explicit-product-test-catalog','host')
    loaded=load_method(MethodSource(CANDIDATE),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,caps,'ordessa.methods/v2');assert compiled.ok,compiled.error
    class FixtureCatalog:
        def read_current(self):return caps
    store=SQLiteSnapshotStore(library)
    frozen=freeze_method(compiled.value,store,store,capability_catalog=FixtureCatalog());assert frozen.ok,frozen.error
    snapshot=store.get(frozen.value.ref)
    assert snapshot.ref.snapshot_digest=='fa51512abd24167856217ee58b4ba26903247a4f6e319ed9d80d20dc4c8c800c'
    return snapshot,store


@pytest.fixture(scope="module")
def human_product(tmp_path_factory):
    tmp_path=tmp_path_factory.mktemp("fresh-human-product")
    path=tmp_path/'original-human.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='human-product-fixture',schema_version=10)
    factory=SQLiteUoWFactory(library);snapshot,store=_publish(library)
    authority=InstanceAccessAuthority(lambda:'synthetic-fixture-token',principal_id='synthetic-registered-agent',legacy_principal=None,
        grants=(AccessGrant(SCOPE,OPS),))
    access=EngineeringCommandAccess(authority);caller=authority.authenticate('Bearer synthetic-fixture-token')
    def admitted(op,id):return access.admit(caller,SCOPE,op,request_id=id,trace_id=id)
    method=MethodRef(snapshot.ref.method_id,snapshot.ref.release_version,snapshot.ref.schema_version,Digest('sha256',snapshot.ref.snapshot_digest))
    methods=SQLiteMethodControl(factory,store)
    with admitted('engineering.methods.adopt','adopt24') as context:
        MethodUseCases(factory,access,store,OriginalMethodManagement(access,SCOPE)).adopt(method,context,expected_version=0)
    blobs=SQLiteBlobStore(library)
    with admitted('engineering.artifacts.create','fresh24') as context:
        source_bytes=b'Synthetic qualification user request: keep human review distinct from implementation permission.'
        digest=Digest('sha256',hashlib.sha256(source_bytes).hexdigest())
        blob=blobs.put_verified(source_bytes,digest,'text/plain')
        source=SourceRef('fixture-qa','chat_message',SourceLocator('chat_message',provider='synthetic-test',conversation_id='thread',message_id='message'),
            ExcerptCapture(blob,digest,ContentSelector('whole_capture')),context.received_at,context.authenticated_actor,'text/plain',len(source_bytes))
        statement='Keep human review distinct from implementation permission.'
        value={'document_type':'did','schema_version':1,'title':'Synthetic fresh2.4 qualification DID',
            'intent':'Test actual method-bound human review without authorizing implementation.',
            'claims':[{'claim_id':'C1','kind':'user_request','statement':statement,'source_ids':['fixture-qa'],'counter_source_ids':[]}],
            'goals':['A complete human checklist'],'non_goals':['No implementation Grant'],
            'change_plan':[{'path':'controlled/README.md','change':'Document separate review and implementation actions','reason_claim_ids':['C1']}],
            'risks':[],'rollback':'No implementation occurs','acceptance':[{'acceptance_id':'A1','description':'Review is distinct from Grant','test_ids':['human-record']}],'open_questions':[]}
        claim=Claim('C1',ContentSelector('json_pointer',pointer='/claims/0/statement'),Digest('sha256',hashlib.sha256(canonical_bytes(statement)).hexdigest()))
        created=create_fresh_human_material(factory,access,methods,context,method_ref=method,document_type='did',value=value,
            sources=(source,),claims=(claim,),evidence_links=(EvidenceLink('C1',source,ContentSelector('whole_capture'),'supports','Synthetic fixture only'),))
        assert created.status=='completed',created.result
        target=Target('primary',decode_subject_ref(created.result['revision_ref']))
    raw_policy=(CANDIDATE/'policies/product-chat-human-review.v1.yaml').read_bytes()
    policy_ref=ConsentPolicyRef('ordessa.product.v1.chat-attested-human-review',1,Digest('sha256',hashlib.sha256(raw_policy).hexdigest()))
    selection=SelectedHumanReviewPolicy(raw_policy,policy_ref)
    def bindings_factory(f,m):
        return ConfiguredHumanReviewBindings(f,m,scope=target_scope,method_ref=method,
            targets=(target,),input_slots=('proposal_ref','source_captures','claim_bindings'),phase_key='source_review')
    target_scope=None
    # Domain scope is original, reconstructed by active admission rather than wire actor.
    with admitted('engineering.reviews.request','scope') as context:target_scope=context.scope
    def source_factory(f,m,b,a,s):
        return RegisteredChatHumanReviewAuthority(f,a,scope=s,principal_id=a.authority.principal_id,policy_selection=selection,
            selected_policy_ref=policy_ref,conversation_locator=LOCATOR,human_subject_id='synthetic-chat-user')
    proof_refs={}
    ports_factory=human_review_ports_factory(bindings=bindings_factory,manual_authority_factory=source_factory,
        proof_lookup=lambda id:(proof_refs[id],FrozenCheckRequest(plan.plan_digest,0,1)) if id in proof_refs else None)
    ports=ports_factory(factory,access,SCOPE)
    reviews=ReviewUseCases(factory,access,ports.review_admission,blobs=ports.blobs)
    with admitted('engineering.reviews.request','request24') as context:
        result=prepare_human_plan(factory,ports.review_admission.methods,ports.review_admission.base.bindings,reviews,context,
            review_id='fresh24-human-review',method_ref=method,phase_key='source_review')
        assert result.status=='completed',result.result
        presentation=prepare_human_presentation(factory,ports.review_admission,context,review_id='fresh24-human-review')
        with factory.begin(context.scope,'read') as uow:
            plan=uow.reviews.get_plan('fresh24-human-review');request=uow.reviews.get_request(plan.review_id)
        from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
        proof_refs[plan.review_id]=decode_blob_ref(presentation['mechanical_proof_ref'])
        with ports.review_admission.methods.guard_method(context,method) as current:
            standard=ports.review_admission.base._expected(context,plan,current)
        keys=tuple(k for k in plan.check_keys if k.criterion_id in {'source_integrity','claim_coverage'})
        answers=ports.review_admission.mechanical.verify_checks(context,plan,FrozenCheckRequest(plan.plan_digest,0,1),proof_refs[plan.review_id],
            standard=standard,check_keys=keys).answers
    library.close()
    runtime=build_product_runtime(tmp_path/'server',library_path=path,library_id='human-product-fixture',scope=SCOPE,
        machine_capabilities=OPS,application_ports_factory=ports_factory)
    runtime.start()
    # Explicit test root gives original internal gate read permission; production
    # wire selection remains finite and does not advertise this internal port.
    runtime.wire.identity_authority.replace_grants((AccessGrant(SCOPE,GATE_OPS),))
    try:yield dict(runtime=runtime,path=path,plan=plan,request=request,presentation=presentation,proof=proof_refs[plan.review_id],
        standard=standard,mechanical=answers,selection=selection,policy_ref=policy_ref,raw_policy=raw_policy,
        ports_factory=ports_factory,root=tmp_path)
    finally:runtime.stop()


def _parameters(case,answer='完整审核清单全部满足',**changes):
    plan=case['plan'];runtime=case['runtime']
    parsed=expand_explicit_answer(plan,case['standard'],answer,case['mechanical'])
    source=ConversationSource(LOCATOR,('synthetic-answer-message',),'Synthetic fixture, no actual user reply. '+SOURCE_LIMITATION,
        runtime.wire.identity_authority.principal_id,'2026-10-11T12:00:00.000000Z')
    reply=ManualReviewReply(QUESTION,canonical_bytes(case['presentation']['checklist']).decode(),answer,source,
        tuple(CriterionAnswer(k,parsed[k],(),'chat-attested explicit answer: '+answer) for k in plan.check_keys))
    reply=replace(reply,**changes)
    raw=encode_human_review_response(plan,0,1,reply,case['proof'],answer_mode='whole_plan')
    return {'review_id':plan.review_id,'request_version':0,'fence':1,'raw_response_utf8':raw.decode()}


def test_actual_fresh_method_payload_full_pending_checklist(human_product):
    c=human_product;value=_http.call(c['runtime'],'engineering.reviews.get_request',{'review_id':c['plan'].review_id},scope=SCOPE)['result']['data']
    assert value['request']['state']=='requested' and value['request']['version']==0 and value['request']['fence']==1
    assert value['human_review']['available'] is True
    assert len(value['human_review']['checklist']['checks'])==len(c['plan'].check_keys)==3
    material=value['human_review']['checklist']['materials'][0]
    assert material['payload']['content_kind']=='method_content'
    assert material['payload']['inline_value']['schema_ref']['method_ref']['release_version']=='2.4.0'
    assert 'Synthetic qualification user request' in value['human_review']['checklist']['captured_sources'][0]['selected_content']['text']
    assert value['human_review']['checklist']['review_is_implementation_grant'] is False


@pytest.mark.parametrize('change',['locator','attestor','context','expansion','policy','capability','blank','implementation_only','wrong_fence'])
def test_untrusted_source_or_changed_policy_keeps_original_pending(human_product,change):
    c=human_product;params=_parameters(c)
    value=json.loads(params['raw_response_utf8'])
    if change=='locator':value['reply']['source']['locator']='conversation://foreign'
    elif change=='attestor':value['reply']['source']['attestor_id']='foreign-agent'
    elif change=='context':value['reply']['necessary_context']='Only one check displayed'
    elif change=='expansion':value['reply']['check_answers'][0]['status']='violated'
    elif change=='blank':value['reply']['user_answer']=''
    elif change=='implementation_only':value['reply']['user_answer']='继续实施'
    elif change=='wrong_fence':value['fence']=2;params['fence']=2
    elif change=='policy':c['selection'].disable()
    elif change=='capability':c['runtime'].wire.identity_authority.replace_grants((AccessGrant(SCOPE,tuple(x for x in GATE_OPS if x!='engineering.conversation.attest')),))
    params['raw_response_utf8']=canonical_bytes(value).decode()
    response=_http.call(c['runtime'],'engineering.reviews.record',params,scope=SCOPE,request_id='negative-'+change)
    assert 'error' in response and 'result' not in response,response
    state=_http.call(c['runtime'],'engineering.reviews.get_request',{'review_id':c['plan'].review_id},scope=SCOPE)['result']['data']['request']
    assert state['state']=='requested' and state['version']==0 and state['fence']==1
    if change=='policy':c['selection'].select(c['raw_policy'],c['policy_ref'])
    if change=='capability':c['runtime'].wire.identity_authority.replace_grants((AccessGrant(SCOPE,GATE_OPS),))


def test_registered_fixture_answer_records_original_review_not_grant(human_product):
    c=human_product;response=_http.call(c['runtime'],'engineering.reviews.record',_parameters(c),scope=SCOPE)
    assert response['result']['status']=='completed',response
    historical=_http.call(c['runtime'],'engineering.reviews.get_request',{'review_id':c['plan'].review_id},scope=SCOPE)['result']['data']
    assert historical['request']['state']=='recorded' and historical['human_review']['available'] is True
    assert historical['human_review']['checklist']['request_version']==0
    library=EngineeringLibrary.open(c['path'],library_id='human-product-fixture')
    try:
        factory=SQLiteUoWFactory(library)
        with factory.begin(c['plan'].scope,'read') as uow:
            assert uow.reviews.get_request(c['plan'].review_id).state=='recorded'
            assert uow.engineering.access.execute('SELECT count(*) FROM eng_approval_grants').fetchone()[0]==0
    finally:library.close()




def test_recorded_gate_rechecks_policy_and_attestor_current_trust(human_product):
    from ordessa_engineering.application.contracts.errors import ApplicationError
    c=human_product;runtime=c['runtime'];library=EngineeringLibrary.open(c['path'],library_id='human-product-fixture')
    factory=SQLiteUoWFactory(library);access=EngineeringCommandAccess(runtime.wire.identity_authority)
    ports=c['ports_factory'](factory,access,SCOPE);reviews=ReviewUseCases(factory,access,ports.review_admission,blobs=ports.blobs)
    def gate():
        caller=runtime.wire.identity_authority.authenticate('Bearer '+runtime.token)
        with access.admit(caller,SCOPE,'engineering.reviews.query',request_id='gate',trace_id='gate') as context:
            return reviews.gate(c['plan'].requirement,context)
    try:
        assert gate().satisfied
        c['selection'].disable()
        with pytest.raises(ApplicationError,match='HUMAN_REVIEW_POLICY_CHANGED'):gate()
        c['selection'].select(c['raw_policy'],c['policy_ref'])
        runtime.wire.identity_authority.replace_grants((AccessGrant(SCOPE,tuple(x for x in GATE_OPS if x!='engineering.conversation.attest')),))
        with pytest.raises(ApplicationError,match='ACCESS_DENIED'):gate()
        with factory.begin(c['plan'].scope,'read') as uow:
            assert uow.reviews.get_request(c['plan'].review_id).state=='recorded'
    finally:library.close()


def test_selected_policy_refuses_reentrant_change_during_guard():
    from ordessa_engineering.application.contracts.errors import ApplicationError
    raw=(CANDIDATE/'policies/product-chat-human-review.v1.yaml').read_bytes()
    ref=ConsentPolicyRef('ordessa.product.v1.chat-attested-human-review',1,Digest('sha256',hashlib.sha256(raw).hexdigest()))
    selection=SelectedHumanReviewPolicy(raw,ref)
    with selection.guard(ref):
        with pytest.raises(ApplicationError,match='HUMAN_REVIEW_POLICY_BUSY'):selection.disable()
        with pytest.raises(ApplicationError,match='HUMAN_REVIEW_POLICY_BUSY'):selection.select(raw,ref)
