"""Source-only method adapter tests, no real model or production publication.

Report schema bytes are actual Methods2.5; an explicit minimal test-host method
is compiled/published in isolated SQLite. It is not publication of candidate2.5.
Unit identity issuer and method/source role selection below are explicit fixtures.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import MethodSource, CompilationCapabilities
from ordessa_engineering.methods.loading.parsing import parse_document
from ordessa_server.composition.engineering_method_unit_sources import decode_method_report, OriginalMethodUnitReviewPolicy

METHOD=Path(__file__).resolve().parents[3]/'methods/incremental-engineering/candidates/2.5.0'


@pytest.fixture
def specimen(tmp_path):
    root=tmp_path/'method';root.mkdir()
    strategy=parse_document((METHOD/'policies/unit-submission-review.v1.yaml').read_bytes(),'application/yaml','policy.yaml')
    workflow={'schema_version':1,'entry':'review','steps':[
        {'id':'review','kind':'operation','operation':'engineering.reviews.request','inputs':{'plan':'plan'},
         'outcomes':{'completed':{'next':'done'},'rejected':{'stop':'finished'}},
         'config':{'unit_submission_review_strategy':strategy}},
        {'id':'done','kind':'stop','outcome':'finished'}],
        'stop_outcomes':['finished'],'wait_kinds':[],'context_slots':['plan']}
    rawschema=(METHOD/'documents/submission/schema.json').read_bytes()
    resources=[]
    for rid,kind,path,media,raw in [('workflow.main','workflow','workflow.json','application/json',canonical_bytes(workflow)),
             ('document.submission.schema','document_schema','schema.json','application/schema+json',rawschema)]:
        (root/path).write_bytes(raw)
        resources.append({'id':rid,'kind':kind,'path':path,'media_type':media,'sha256':hashlib.sha256(raw).hexdigest()})
    descriptors=tuple(c for c in command_capabilities().capabilities if c.capability_id=='engineering.reviews.request')
    capabilities=CompilationCapabilities(descriptors,trust_class='host')
    manifest={'schema_version':1,'method_id':'test.product.report-schema','release_version':'1.0.0',
        'compiler_contract':'ordessa.methods/v1','entry':{'resource':'workflow.main'},'resources':resources,
        'documents':[{'document_type':'submission','schema':{'resource':'document.submission.schema'},'validation_target':'method_content'}],
        'requires':[{k:getattr(c,k) for k in ('capability_id','kind','interface_version','contract_digest')} for c in descriptors]}
    (root/'method.yaml').write_bytes(canonical_bytes(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,capabilities,'test.product.report-compiler/1');assert compiled.ok,compiled.error
    class TestHostCatalog:
        def read_current(self):return capabilities
    library=EngineeringLibrary.create((tmp_path/'test.sqlite').resolve(),library_id='controlled-report-fixture',schema_version=10)
    store=SQLiteSnapshotStore(library)
    frozen=freeze_method(compiled.value,store,store,capability_catalog=TestHostCatalog());assert frozen.ok,frozen.error
    snapshot=store.get(frozen.value.ref)
    ref=snapshot.ref
    method=MethodRef(ref.method_id,ref.release_version,ref.schema_version,Digest('sha256',ref.snapshot_digest))
    resource=next(r for r in snapshot.resources if r.resource_id=='document.submission.schema')
    schema=ExactMethodResourceRef(method,resource.logical_path,Digest('sha256',resource.digest),resource.resource_id)
    report={'document_type':'submission','schema_version':2,'summary':'Author report only','change_notes':['Delivered'],
        'evidence_index':[{'evidence_id':'test-report','kind':'test_log','summary':'Author asserts test succeeded'}],
        'remaining_issues':[],'reported_outcome':'complete',
        'fixed_delivery_refs':[{'kind':'commit','repository_id':'repo','commit_id':'a'*40}],
        'requirement_results':[{'requirement_id':'req-1','reported_state':'complete','delivery_indexes':[0],
                                'evidence_ids':['test-report'],'explanation':'Author assertion'}],
        'reported_facts':[{'fact_id':'test-1','kind':'test','statement':'Tests pass','evidence_ids':['test-report'],
                           'verification_status':'asserted'}]}
    try:yield SimpleNamespace(snapshot=snapshot,schema=schema,report=report,library=library)
    finally:library.close()


def test_actual_schema2_preserves_complete_as_assertion(specimen):
    s=specimen;content=decode_method_report(s.snapshot,s.schema,json.dumps(s.report))
    assert content.value['reported_outcome']=='complete'
    assert content.value['reported_facts'][0]['verification_status']=='asserted'


@pytest.mark.parametrize('change',['verified','mutable','empty','wrong-version'])
def test_method_schema_refuses_report_shape(specimen,change):
    s=specimen
    if change=='verified':s.report['reported_facts'][0]['verification_status']='verified'
    elif change=='mutable':s.report['fixed_delivery_refs'][0]['commit_id']='main'
    elif change=='empty':s.report['fixed_delivery_refs']=[]
    else:s.report['schema_version']=1
    with pytest.raises(ApplicationError):decode_method_report(s.snapshot,s.schema,json.dumps(s.report))


def test_duplicate_json_key_never_becomes_report(specimen):
    s=specimen
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_OUTPUT_INVALID'):
        decode_method_report(s.snapshot,s.schema,'{"summary":"a","summary":"b"}')


def test_other_method_snapshot_ref_is_rejected(specimen):
    s=specimen;other=replace(s.schema,method_ref=replace(s.schema.method_ref,release_version='other'))
    with pytest.raises(ApplicationError,match='METHOD_RESOURCE_MISMATCH'):
        decode_method_report(s.snapshot,other,json.dumps(s.report))


@pytest.fixture
def identity_specimen(specimen):
    unit={'environmentNamespace':'unit-env','unitId':'author','ownerProviderRef':{'fixture':'explicit'},'sourceRevision':'sha256:'+'1'*64}
    reviewer={**unit,'unitId':'reviewer'}
    calls=[]
    class AuthorizedRecordsFixture:
        def resolve_unit_reference(self,reference,context,*,input_digest):
            assert context=='fixture-query' and input_digest=='fixture-digest'
            calls.append(reference)
            return SimpleNamespace(public_ref=reference)
    policy=OriginalMethodUnitReviewPolicy(AuthorizedRecordsFixture(),unit_query_factory=lambda *args:('fixture-query','fixture-digest'))
    run=SimpleNamespace(author_unit_utf8=canonical_bytes(unit),reviewer_unit_utf8=canonical_bytes(reviewer))
    return specimen,policy,run,calls


def test_method_declaration_drives_original_identity_resolution(identity_specimen):
    s,policy,run,calls=identity_specimen
    with policy(None,s.snapshot,SimpleNamespace(requirement=SimpleNamespace(phase_key='review')),run):
        assert len(calls)==2


def test_this_method_rejects_same_author_reviewer(identity_specimen):
    s,policy,run,_=identity_specimen;run.reviewer_unit_utf8=run.author_unit_utf8
    with pytest.raises(ApplicationError,match='METHOD_REVIEWER_CONSTRAINT_FAILED'):
        with policy(None,s.snapshot,SimpleNamespace(requirement=SimpleNamespace(phase_key='review')),run):pass


def test_undeclared_phase_is_unavailable_not_global_independence(identity_specimen):
    s,policy,run,_=identity_specimen
    with pytest.raises(ApplicationError,match='METHOD_REVIEWER_POLICY_UNAVAILABLE'):
        with policy(None,s.snapshot,SimpleNamespace(requirement=SimpleNamespace(phase_key='done')),run):pass


@pytest.fixture
def report_source_specimen(specimen):
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.domain.common.models.identity import Scope
    from ordessa_engineering.domain.artifacts.models import MethodContent
    from ordessa_server.composition.engineering_method_unit_sources import OriginalMethodReportSource
    s=specimen;blobs=SQLiteBlobStore(s.library);factory=SimpleNamespace(authority_id=blobs.authority_id)
    scope=Scope('fixture-realm','fixture-project');context=SimpleNamespace(scope=scope)
    held={'method':False,'access':False}
    class ExplicitMethodSelectionFixture:
        def __init__(self):self.factory=factory
        @contextmanager
        def guard_selected(self,context):
            held['method']=True
            try:yield s.snapshot
            finally:held['method']=False
    class ExplicitAccessFixture:
        @contextmanager
        def guard_current_capability(self,*args):
            held['access']=True
            try:yield
            finally:held['access']=False
    content=MethodContent.from_value(s.schema,s.report)
    unit={'environmentNamespace':'fixture-env','unitId':'author','ownerProviderRef':{'fixture':'explicit'},'sourceRevision':'sha256:'+'a'*64}
    receipt={'state':'completed','unitRef':unit,'operationRef':'author-op','inputDigest':'sha256:'+'b'*64,
             'summary':{'text':json.dumps(s.report),'stopReason':'end_turn','successfulRpcResponse':True}}
    def observation():
        raw=canonical_bytes(receipt)
        ref=blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
        return SimpleNamespace(authority_id=blobs.authority_id,state='completed',blob_ref=ref,unit_ref=unit,
            operation_ref='author-op',expected_prompt_digest='sha256:'+'b'*64,query_digest='fixture-query')
    captured=observation()
    execution=SimpleNamespace(environment_namespace=unit['environmentNamespace'],unit_id=unit['unitId'],
        owner_provider_ref_bytes=canonical_bytes(unit['ownerProviderRef']),source_revision=unit['sourceRevision'],
        operation_ref='author-op',prompt_input_digest=Digest('sha256','b'*64),captured_observation_ref=captured.blob_ref)
    submission=SimpleNamespace(scope=scope,method_content=content,execution_ref=execution,output_refs=('explicit-output-ref-fixture',))
    source=OriginalMethodReportSource(factory,ExplicitMethodSelectionFixture(),blobs,ExplicitAccessFixture(),scope=scope,phase_key='review')
    return SimpleNamespace(source=source,context=context,package=SimpleNamespace(payload=SimpleNamespace(method_ref=s.schema.method_ref)),
        submission=submission,captured=captured,held=held,receipt=receipt,recapture=observation)


def test_original_report_port_view_holds_method_and_source_guards(report_source_specimen):
    s=report_source_specimen
    with s.source.guard_report(s.context,s.package,s.submission,s.captured) as admitted:
        assert s.held=={'method':True,'access':True}
        assert admitted.output_refs==s.submission.output_refs
        assert admitted.report_content_digest.hex==hashlib.sha256(s.submission.method_content.value_bytes).hexdigest()
    assert not any(s.held.values())


def test_report_bytes_cannot_be_replaced_by_caller_body(report_source_specimen):
    s=report_source_specimen
    s.receipt['summary']['text']=s.receipt['summary']['text'].replace('Author report only','Other native body')
    s.captured=s.recapture();s.submission.execution_ref.captured_observation_ref=s.captured.blob_ref
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_RESPONSE_MISMATCH'):
        with s.source.guard_report(s.context,s.package,s.submission,s.captured):pass


def test_report_unknown_cannot_be_submitted_via_this_source(report_source_specimen):
    s=report_source_specimen;s.captured.state='unknown'
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_SOURCE_INVALID'):
        with s.source.guard_report(s.context,s.package,s.submission,s.captured):pass


def test_root_cannot_select_arbitrary_document_schema(report_source_specimen):
    s=report_source_specimen;s.source.phase_key='done'
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_METHOD_BINDING_UNAVAILABLE'):
        with s.source.guard_report(s.context,s.package,s.submission,s.captured):pass
