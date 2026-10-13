"""Real SQLite/2.3 snapshot mechanical checks; management is a synthetic fixture.

Actual Blob bytes/selector/graph/proof reads are exercised. No authenticated
production business binding, model call or semantic coverage qualification.
"""
from dataclasses import replace
import hashlib
import pytest
from test_method_per_claim import ROOT, published, revision, binding
from test_method_control_admission import TestManagement, context
from test_proposal_usecases import SCOPE, ACTOR, CREATED_AT, SyntheticAccess
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest, CheckSourceAdmission
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.domain.artifacts.models import Artifact
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.provenance import SourceRef, SourceLocator, ExcerptCapture, EvidenceLink
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.common.models.values import Digest

@pytest.fixture
def mechanical(tmp_path, request):
    library=EngineeringLibrary.create((tmp_path/'mechanical.sqlite').resolve(),library_id='mechanical',schema_version=10)
    try:
        snapshot=published(library, ROOT/'candidates/2.3.0')
        factory=SQLiteUoWFactory(library);store=SQLiteSnapshotStore(library)
        methods=MethodUseCases(factory,SyntheticAccess(),store,TestManagement())
        method=MethodRef(snapshot.ref.method_id,snapshot.ref.release_version,snapshot.ref.schema_version,
                         Digest('sha256',snapshot.ref.snapshot_digest))
        methods.adopt(method,context('mechanical-adopt'),expected_version=0)
        controls=SQLiteMethodControl(factory,store);blobs=SQLiteBlobStore(library)
        raw=b'captured source text'
        blob=blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'text/plain')
        capture=SourceRef('source-1','code',SourceLocator('code',repository_id='repo',path='README.md'),
                         ExcerptCapture(blob,blob.digest,ContentSelector('whole_capture')),CREATED_AT,ACTOR,
                         'text/plain',len(raw))
        original=revision()
        material=replace(original,sources=(capture,),evidence_links=tuple(
            EvidenceLink(c.claim_id,capture,ContentSelector('whole_capture'),'supports','fixture association')
            for c in original.claims))
        if getattr(request, 'param', None) == 'missing-links':
            material=replace(material,evidence_links=())
        with factory.begin(SCOPE) as uow:
            uow.engineering.create(Artifact(SCOPE,material.artifact_id,'plan',CREATED_AT))
            verify_material(material,uow.engineering.validated_budget())
            uow.engineering.append_revision(material,expected_version=0);uow.commit()
        bindings=binding((material,));bridge=MethodBridge()
        req=next(r for r in bridge.review_requirements(snapshot,bindings,revisions=(material,))
                 if r.criterion_set_ref.criterion_set_id=='source-review')
        plan=bridge.review_plan(snapshot,bindings,req,'mechanical-review',revisions=(material,))
        standard=next(s for s in snapshot.program.standard_definitions if s.standard_id=='source-review')
        keys=tuple(k for k in plan.check_keys if k.criterion_id in ('source_integrity','claim_coverage'))
        yield MechanicalReviewCheckSource(factory,controls,blobs),context('mechanical-check'),plan,FrozenCheckRequest(plan.plan_digest,0,1),standard,keys,methods
    finally:library.close()


def test_real_capture_verify_and_guard_do_not_promote_semantic_coverage(mechanical):
    source,ctx,plan,request,standard,keys,_=mechanical
    ref=source.capture_proof(ctx,plan,request,standard=standard,check_keys=keys)
    response=source.verify_checks(ctx,plan,request,ref,standard=standard,check_keys=keys)
    assert {a.check_key.criterion_id:a.status for a in response.answers}=={
        'source_integrity':'satisfied','claim_coverage':'unknown'}
    assert response.provenance_digest==ref.digest
    with source.guard_checks(ctx,(CheckSourceAdmission(plan,request,ref,keys,response),)):
        assert source.factory.library._method_guard_fences.values
    assert not source.factory.library._method_guard_fences.values


@pytest.mark.parametrize('mechanical',['missing-links'],indirect=True)
def test_missing_claim_chain_is_insufficient_even_with_intact_source_bytes(mechanical):
    source,ctx,plan,request,standard,keys,_=mechanical
    ref=source.capture_proof(ctx,plan,request,standard=standard,check_keys=keys)
    response=source.verify_checks(ctx,plan,request,ref,standard=standard,check_keys=keys)
    assert {a.check_key.criterion_id:a.status for a in response.answers}=={
        'source_integrity':'satisfied','claim_coverage':'insufficient'}


@pytest.mark.parametrize('mutation',['version','fence','subset','bytes'])
def test_exact_proof_rejects_changed_request_keys_or_source_bytes(mechanical,mutation):
    source,ctx,plan,request,standard,keys,_=mechanical
    ref=source.capture_proof(ctx,plan,request,standard=standard,check_keys=keys)
    if mutation=='version':request=replace(request,request_version=1)
    elif mutation=='fence':request=replace(request,fence=2)
    elif mutation=='subset':keys=keys[:1]
    else:
        bad=b'changed proof';ref=source.blobs.put_verified(bad,Digest('sha256',hashlib.sha256(bad).hexdigest()),'application/json')
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_PROOF_CHANGED'):
        source.verify_checks(ctx,plan,request,ref,standard=standard,check_keys=keys)


def test_missing_mechanical_capability_version_fails_closed(mechanical):
    source,ctx,plan,request,standard,keys,_=mechanical
    criterion=next(c for c in standard.criteria if c.criterion_id==keys[0].criterion_id)
    invalid=replace(criterion,checks=(replace(criterion.checks[0],interface_version='9.9.9'),))
    changed=replace(standard,criteria=tuple(invalid if c==criterion else c for c in standard.criteria))
    with pytest.raises(ApplicationError,match='REVIEW_CHECK_EXECUTION_UNAVAILABLE'):
        source._proof(ctx,plan,request,changed,keys)


def test_method_disable_rejects_previously_captured_source_proof(mechanical):
    source,ctx,plan,request,standard,keys,methods=mechanical
    ref=source.capture_proof(ctx,plan,request,standard=standard,check_keys=keys)
    response=source.verify_checks(ctx,plan,request,ref,standard=standard,check_keys=keys)
    methods.control(plan.requirement.method_ref,context('mechanical-disable'),expected_version=0,
                    enabled=False,reason='fixture revocation')
    with pytest.raises(ApplicationError,match='METHOD_DISABLED'):
        with source.guard_checks(ctx,(CheckSourceAdmission(plan,request,ref,keys,response),)):
            pytest.fail('disabled method must refuse current source trust')
