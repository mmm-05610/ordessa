"""Original SQLite snapshot/request reads; all Unit/authority peers are fixtures."""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace
import pytest

from test_method_review_bridge import publish
from test_proposal_usecases import SCOPE, SyntheticAccess, _artifact_graph
from test_method_control_admission import TestManagement, context
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.review_sources import SQLiteUnitReviewBindings
from ordessa_engineering.application.api import EngineeringService, NativeReviewInvocation
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import load_method, compile_method
from ordessa_engineering.methods.definitions.models import MethodSource, CompilationCapabilities, CapabilityDescriptor
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.identity import RecordIdentity
from ordessa_engineering.domain.reviews.models import Observation, ReviewRecord, observations_digest


@pytest.fixture
def selected(tmp_path):
    lib=EngineeringLibrary.create((tmp_path/'reader.sqlite').resolve(),library_id='reader-test',schema_version=10)
    try:
        _,root=publish(lib,tmp_path/'method')
        manifest=json.loads((root/'method.yaml').read_text());manifest['release_version']='3.5.2'
        workflow={'schema_version':1,'entry':'review','context_slots':['proposal_ref'],
            'steps':[{'id':'review','kind':'operation','operation':'engineering.reviews.request',
                'config':{'purpose':'quality','standards':[{'resource':'standard.test'}],
                    'review_source':{'response_document_type':'test-document',
                        'response_schema':{'resource':'schema.test'},'response_codec':'exact_check_key_status/1'}},
                'outcomes':{'completed':{'next':'done'},'rejected':{'stop':'finished'}}},
                {'id':'done','kind':'stop','outcome':'finished'}], 'stop_outcomes':['finished'],'wait_kinds':[]}
        raw=canonical_bytes(workflow);(root/'workflow.yaml').write_bytes(raw)
        manifest['resources'][0]['sha256']=hashlib.sha256(raw).hexdigest()
        operation=next(d for d in EngineeringService.operation_capabilities().capabilities
                       if d.capability_id=='engineering.reviews.request')
        manifest['requires'].append({k:getattr(operation,k) for k in ('capability_id','kind','interface_version','contract_digest')})
        (root/'method.yaml').write_text(json.dumps(manifest))
        check=CapabilityDescriptor('test.bridge.check','check','1.0.0',method_digest('capability-contract',{}),{})
        caps=CompilationCapabilities((check,operation),'explicit-reader-test-catalog','host')
        loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
        compiled=compile_method(loaded.value,caps,'test.reader/1');assert compiled.ok,compiled.error
        store=SQLiteSnapshotStore(lib)
        frozen=freeze_method(compiled.value,store,store,capability_catalog=SimpleNamespace(read_current=lambda:caps))
        assert frozen.ok,frozen.error
        snapshot=store.get(frozen.value.ref);ref=snapshot.ref
        method=MethodRef(ref.method_id,ref.release_version,ref.schema_version,Digest('sha256',ref.snapshot_digest))
        factory=SQLiteUoWFactory(lib);control=SQLiteMethodControl(factory,store)
        MethodUseCases(factory,SyntheticAccess(),store,TestManagement()).adopt(method,context('adopt'),expected_version=0)
        _,revision,_=_artifact_graph(factory);target=Target('primary',revision)
        binding=EngineeringTargetBindings(SCOPE,TargetSet((target,)),((target,'test-document'),),
            ('proposal_ref',),('reviewer',),'review',workflow_node_id='review')
        bridge=MethodBridge();requirement=bridge.review_requirements(snapshot,binding)[0]
        plan=bridge.review_plan(snapshot,binding,requirement,'reader-review')
        with factory.begin(SCOPE) as uow:
            request=uow.reviews.create_plan(plan);uow.commit()
        standard=snapshot.program.standard_definitions[0]
        class Bindings:
            def __init__(self):self.factory=factory
            def resolve_plan_bindings(self,*args):return binding
            def material_inputs_for_plan(self,*args):return ()
        records=SimpleNamespace(acp_prompt_input_digest=lambda unit,params:'sha256:'+hashlib.sha256(canonical_bytes({'unitRef':unit,'params':params})).hexdigest())
        unit={'environmentNamespace':'test','unitId':'independent','ownerProviderRef':{'fixture':True},'sourceRevision':'1'}
        author={**unit,'unitId':'author'}
        calls=[]
        def invocation(ctx,p,r,*,prompt_binding):
            calls.append(prompt_binding)
            return NativeReviewInvocation(unit,'actual-operation',{'sessionId':'test-session',
                'prompt':[{'type':'text','text':prompt_binding}]},object())
        reader=SQLiteUnitReviewBindings(factory,control,records,review_bindings=Bindings(),
            invocation_resolver=invocation,author_unit_resolver=lambda *args:author)
        yield locals()
    finally:lib.close()


def test_reader_binds_actual_frozen_delivery_schema_full_plan_and_native_prompt(selected):
    e=selected;bound=e['reader'].resolve_unit_review(context('read'),e['plan'],e['request'],standard=e['standard'])
    assert bound.delivery_refs==(e['revision'],)
    assert bound.required_check_keys==e['plan'].check_keys
    assert bound.request_version==e['request'].version and bound.request_fence==e['request'].fence
    block=json.loads(e['calls'][0])['ordessa.method-unit-review']
    assert block['plan']==json.loads(canonical_bytes(asdict(e['plan'])))
    assert block['delivery'][0]['revision_id']==e['revision'].revision_id
    assert block['response_schema_ref']==asdict(bound.response_schema_ref)
    assert bound.decision_question_refs==()  # Fixture has no Decision check.


def test_reader_refuses_stale_or_withdrawn_request_before_native_query(selected):
    e=selected
    with pytest.raises(ApplicationError,match='REVIEW_REQUEST_CHANGED'):
        e['reader'].resolve_unit_review(context('stale'),e['plan'],replace(e['request'],version=7),standard=e['standard'])
    with e['factory'].begin(SCOPE) as uow:
        uow.reviews.withdraw_request(e['plan'].review_id,expected_version=e['request'].version,fence=e['request'].fence)
        uow.commit()
    with pytest.raises(ApplicationError,match='REVIEW_REQUEST_CHANGED'):
        e['reader'].resolve_unit_review(context('withdrawn'),e['plan'],e['request'],standard=e['standard'])
    assert e['calls']==[]


def test_reader_reuses_original_codec_and_preserves_unknown_not_pass(selected):
    e=selected;bound=e['reader'].resolve_unit_review(context('read'),e['plan'],e['request'],standard=e['standard'])
    value={'document_type':'test-document','schema_version':1,'plan_digest':asdict(e['plan'].plan_digest),
        'answers':[{'check_key':asdict(key),'status':'unknown','evidence_refs':[],
                    'rationale':'Explicit lack of evidence'} for key in e['plan'].check_keys]}
    answers=e['reader'].decode_response(bound,value,plan=e['plan'],standard=e['standard'])
    assert all(a.status=='unknown' for a in answers)
    value['answers'].pop()
    with pytest.raises(ApplicationError,match='UNIT_REVIEW_RESPONSE_INCOMPLETE'):
        e['reader'].decode_response(bound,value,plan=e['plan'],standard=e['standard'])


def _pending_record(e):
    raw = b'{"fixture":"raw response; not an authenticated reviewer"}'
    raw_digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
    raw_ref = SQLiteBlobStore(e['lib']).put_verified(
        raw, raw_digest, 'application/octet-stream')
    observations = tuple(Observation(key, 'indeterminate', (), 'synthetic reader fixture')
                        for key in e['plan'].check_keys)
    reviewer = ActorRef('fixture-reviewer', 'human', 'synthetic-unit-review')
    evidence = VerifiedReviewerEvidence(
        SCOPE, reviewer, tuple(e['plan'].reviewer_requirements),
        'synthetic-unit-owner', '1', 1, e['plan'].request_digest, raw_digest,
        observations_digest(observations), Digest('sha256', 'b' * 64))
    record = ReviewRecord(
        RecordIdentity(SCOPE, e['plan'].review_id, context('record').received_at,
                       context('record').authenticated_actor, schema_version=2),
        e['plan'], evidence, observations, raw_response_ref=raw_ref)
    return record


def test_resolve_record_request_supports_in_memory_pending_record_then_exact_recorded_row(selected):
    e = selected
    record = _pending_record(e)
    pending = e['reader'].resolve_record_request(context('pending-record'), e['plan'], record)
    assert pending.state == 'requested'
    assert pending.version == e['request'].version
    assert pending.fence == e['request'].fence

    with e['factory'].begin(SCOPE) as uow:
        uow.reviews.insert_review(
            record, expected_request_version=e['request'].version, fence=e['request'].fence)
        uow.commit()
    recovered = e['reader'].resolve_record_request(context('recover-record'), e['plan'], record)
    assert recovered.state == 'recorded'
    assert recovered.version == e['request'].version
    assert recovered.fence == e['request'].fence


def test_resolve_record_request_refuses_withdrawn_pending_request(selected):
    e = selected
    record = _pending_record(e)
    with e['factory'].begin(SCOPE) as uow:
        uow.reviews.withdraw_request(e['plan'].review_id,
            expected_version=e['request'].version, fence=e['request'].fence)
        uow.commit()
    with pytest.raises(ApplicationError, match='REVIEW_REQUEST_CHANGED'):
        e['reader'].resolve_record_request(context('withdrawn-record'), e['plan'], record)
