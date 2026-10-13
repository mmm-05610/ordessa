"""Real schema10/SQLite snapshots and fences; authority ports explicitly test-only."""
from contextlib import contextmanager
from dataclasses import replace
import pytest
from test_method_review_bridge import publish
from test_proposal_usecases import SCOPE, SyntheticAccess, _ctx, _artifact_graph
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.method_schema import METHOD_TABLES
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer, VerifiedReviewResponse
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.reviews.models import ReviewRequestState, observations_digest, Observation
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.refs import BlobRef


class TestManagement:
    __test__=False
    @contextmanager
    def guard_management(self,*args):
        yield Digest('sha256','b'*64)


@pytest.fixture
def env(tmp_path):
    lib=EngineeringLibrary.create((tmp_path/'methods.sqlite').resolve(),library_id='method-control-test',schema_version=10)
    try:
        snapshot,_=publish(lib,tmp_path/'source')
        ref=snapshot.ref
        method=MethodRef(ref.method_id,ref.release_version,ref.schema_version,Digest('sha256',ref.snapshot_digest))
        factory=SQLiteUoWFactory(lib);store=SQLiteSnapshotStore(lib)
        service=MethodUseCases(factory,SyntheticAccess(),store,TestManagement())
        controls=SQLiteMethodControl(factory,store)
        yield lib,method,factory,service,controls
    finally:lib.close()


def context(id):return replace(_ctx(),request_id=id)


def test_published_does_not_select_or_enable_until_authorized_adoption(env):
    lib,method,factory,service,controls=env
    with pytest.raises(ApplicationError,match='METHOD_SELECTION_UNAVAILABLE'):
        with controls.guard_selected(context('read')): pass
    with pytest.raises(ApplicationError,match='METHOD_CONTROL_UNAVAILABLE'):
        with controls.guard_method(context('read'),method): pass
    result=service.adopt(method,context('adopt'),expected_version=0)
    assert result.result['version']==1
    with controls.guard_selected(context('read'),expected_version=1) as frozen:
        assert frozen.ref.snapshot_digest==method.snapshot_digest.hex
        with factory.begin(SCOPE) as uow:uow.commit()


def test_exact_retry_is_history_and_does_not_adopt_twice(env):
    lib,method,factory,service,controls=env
    a=service.adopt(method,context('adopt'),expected_version=0)
    assert service.adopt(method,context('adopt'),expected_version=0)==a
    with factory.begin(SCOPE,'read') as uow:assert uow.methods.selected().version==1
    with pytest.raises(ApplicationError,match='METHOD_SELECTION_CHANGED'):
        service.adopt(method,context('different'),expected_version=0)
    with factory.begin(SCOPE,'read') as uow:assert uow.commands.get(context('different').key) is None


def test_disable_control_cas_and_selection_cannot_reenable(env):
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    service.control(method,context('disable'),expected_version=0,enabled=False,reason='explicit safety stop')
    with pytest.raises(ApplicationError,match='METHOD_DISABLED'):
        with controls.guard_method(context('read'),method):pass
    with pytest.raises(ApplicationError,match='METHOD_DISABLED'):
        service.adopt(method,context('select-disabled'),expected_version=1)
    with pytest.raises(ApplicationError,match='METHOD_CONTROL_CHANGED'):
        service.control(method,context('stale'),expected_version=0,enabled=True,reason='stale')
    service.control(method,context('enable'),expected_version=1,enabled=True,reason='explicit permission')
    with controls.guard_method(context('read'),method,expected_version=2):pass


def test_active_guard_rechecks_inside_original_begin_even_reentrant_changes(env):
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    with controls.guard_method(context('read'),method):
        service.control(method,context('disable'),expected_version=0,enabled=False,reason='reentrant stop')
        with pytest.raises(ApplicationError,match='METHOD_CONTROL_CHANGED'):
            with factory.begin(SCOPE) as uow:uow.commit()
    with pytest.raises(ApplicationError,match='METHOD_DISABLED'):
        with controls.guard_method(context('after'),method):pass


def test_scope_and_missing_management_are_refused(env):
    lib,method,factory,service,controls=env
    with pytest.raises(ApplicationError,match='METHOD_MANAGEMENT_UNAVAILABLE'):
        MethodUseCases(factory,SyntheticAccess(),SQLiteSnapshotStore(lib),None).adopt(method,context('denied'),expected_version=0)
    service.adopt(method,context('adopt'),expected_version=0)
    with pytest.raises(ApplicationError,match='METHOD_SELECTION_UNAVAILABLE'):
        with controls.guard_selected(replace(context('foreign'),scope=Scope('other','project'))):pass


def test_explicit_migration_preserves_old_schema_and_backups(tmp_path):
    old=EngineeringLibrary.create((tmp_path/'old.sqlite').resolve(),library_id='old',schema_version=9)
    try:
        with pytest.raises(ApplicationError,match='METHOD_CONTROL_SCHEMA_REQUIRED'):
            with SQLiteUoWFactory(old).begin(SCOPE,'read') as uow:uow.methods.selected()
        receipt=migrations.migrate_schema9(old,backup_path=(tmp_path/'backup.sqlite').resolve())
        assert receipt.applied and receipt.target_version==10
        assert not migrations.migrate_schema9(old,backup_path=(tmp_path/'backup.sqlite').resolve()).applied
        backup=EngineeringLibrary.open((tmp_path/'backup.sqlite').resolve(),library_id='old')
        try:
            assert backup._schema_version==9
            assert not set(METHOD_TABLES)&{r[0] for r in backup._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:backup.close()
    finally:old.close()


def build_plan(env):
    from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    # Mechanism-only bindings fixture; product document/slot resolver is absent.
    _,revision,_=_artifact_graph(factory)
    target=Target('primary',revision)
    binding=EngineeringTargetBindings(SCOPE,TargetSet((target,)),((target,'test-document'),),('proposal_ref',),('reviewer',),'phase')
    class Bindings:
        def resolve_bindings(self,*args):return binding
    with controls.guard_method(context('read'),method) as snapshot:
        req=MethodBridge().review_requirements(snapshot,binding)[0]
        plan=MethodBridge().review_plan(snapshot,binding,req,'review')
    return plan,Bindings()


def test_plan_guard_reconstructs_complete_contract_and_rejects_tampering(env):
    lib,method,factory,service,controls=env
    plan,bindings=build_plan(env)
    admission=EngineeringReviewAdmission(factory,controls,bindings)
    with admission.guard_plan(context('request'),plan):
        with factory.begin(SCOPE) as uow:uow.commit()
    with pytest.raises(ApplicationError,match='METHOD_REVIEW_PLAN_CHANGED'):
        with admission.guard_plan(context('changed'),replace(plan,check_policies=tuple(replace(p,weight=2) for p in plan.check_policies))):pass
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_AUTHORITY_UNAVAILABLE'):
        admission.verify_response(context('response'),plan,None,None)


def test_semantic_satisfied_remains_manual_and_missing_checks_refuse(env):
    lib,method,factory,service,controls=env
    plan,bindings=build_plan(env)
    raw=BlobRef(Digest('sha256','d'*64),1,'application/octet-stream','raw-fixture')
    obs=tuple(Observation(k,'indeterminate',(),'unmodified source answer') for k in plan.check_keys)
    evidence=VerifiedReviewerEvidence(SCOPE,context('response').authenticated_actor,('reviewer',),'actual-owner-fixture','1',1,plan.request_digest,raw.digest,observations_digest(obs),Digest('sha256','e'*64))
    class Source:
        def verify_response(self,*args,**kwargs):return VerifiedReviewResponse(evidence,tuple(CriterionAnswer(k,'satisfied',(),'unmodified source answer') for k in plan.check_keys))
    source=Source();admission=EngineeringReviewAdmission(factory,controls,bindings,source)
    req=ReviewRequestState(SCOPE,plan.review_id,'requested',1,0)
    record=admission.verify_response(context('response'),plan,req,raw)
    assert record.complete and record.verdict!='pass'
    assert all(o.result=='indeterminate' for o in record.observations)
    source.verify_response=lambda *args,**kwargs:VerifiedReviewResponse(evidence,())
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
        admission.verify_response(context('response'),plan,req,raw)


def test_source_uses_public_projection_without_copying_policy(env):
    _,method,_,_,controls=env
    plan,bindings=build_plan(env)
    with controls.guard_method(context('read'),method) as snapshot:
        standard=snapshot.program.standard_definitions[0]
    answers=tuple(CriterionAnswer(k,'satisfied',(),'actual structured answer') for k in reversed(plan.check_keys))
    obs=review_observations(plan,standard,answers)
    assert tuple(o.check_key for o in obs)==tuple(sorted(plan.check_keys,key=lambda k:k.sort_key))
    assert all(o.result=='indeterminate' for o in obs)
    assert observations_digest(obs)==observations_digest(review_observations(plan,standard,tuple(reversed(answers))))
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INVALID'):
        review_observations(plan,standard,answers+answers[:1])
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
        review_observations(plan,standard,answers[:1])
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        review_observations(plan,replace(standard,standard_id='other-standard'),answers)


def test_other_connection_stop_between_guard_and_begin_is_detected(env):
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    other=EngineeringLibrary.open(lib.path,library_id=lib.library_id)
    try:
        second=MethodUseCases(SQLiteUoWFactory(other),SyntheticAccess(),SQLiteSnapshotStore(other),TestManagement())
        with controls.guard_method(context('read'),method):
            second.control(method,context('external-stop'),expected_version=0,enabled=False,reason='same authority second connection')
            with pytest.raises(ApplicationError,match='METHOD_CONTROL_CHANGED'):
                with factory.begin(SCOPE) as uow:uow.commit()
    finally:other.close()


def test_control_event_failure_rolls_back_state_and_command(env,monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite.method_repository import SQLiteMethodRepository
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    def fault(*args):raise RuntimeError('control-event-write-fault')
    with monkeypatch.context() as m:
        m.setattr(SQLiteMethodRepository,'_event',fault)
        with pytest.raises(RuntimeError,match='control-event-write-fault'):
            service.control(method,context('fail'),expected_version=0,enabled=False,reason='stop')
    with factory.begin(SCOPE,'read') as uow:
        assert uow.methods.control(method).enabled
        assert uow.methods.control(method).version==0
        assert uow.commands.get(context('fail').key) is None


def test_selected_guard_detects_reentrant_selection_change_and_keeps_old_method(env):
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    with controls.guard_selected(context('read'),expected_version=1):
        service.adopt(method,context('reselect'),expected_version=1)
        with pytest.raises(ApplicationError,match='METHOD_SELECTION_CHANGED'):
            with factory.begin(SCOPE) as uow:uow.commit()
    # Adoption and MethodControl are distinct; history remains eligible.
    with controls.guard_method(context('historical'),method,expected_version=0):
        with factory.begin(SCOPE) as uow:uow.commit()


def test_method_readset_fences_keep_original_readset_codec(env):
    from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
    lib,method,factory,service,controls=env
    service.adopt(method,context('adopt'),expected_version=0)
    reads=ReadSet(SCOPE,(ReadVersion('method_control',method.snapshot_digest.hex,0),ReadVersion('method_selection','current',1)))
    with factory.begin(SCOPE,'read') as uow:uow.engineering.check_read_set(reads)
    service.control(method,context('stop'),expected_version=0,enabled=False,reason='stop')
    with pytest.raises(ApplicationError,match='READ_SET_CHANGED'):
        with factory.begin(SCOPE) as uow:uow.engineering.check_read_set(reads)


def test_original_record_response_consumes_actual_blob_request_and_trust_port(env):
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.domain.reviews.models import CurrentReviewTrust
    lib,method,factory,service,controls=env
    plan,bindings=build_plan(env)
    class Source:
        def verify_response(self,ctx,actual_plan,request,raw,*,standard):
            assert actual_plan==plan and request.fence==1
            assert standard.resource_ref.sha256==plan.requirement.criterion_set_ref.digest.hex
            observations=tuple(Observation(k,'indeterminate',(),'real raw blob fixture') for k in plan.check_keys)
            evidence=VerifiedReviewerEvidence(SCOPE,ctx.authenticated_actor,('reviewer',),'source-fixture','1',1,plan.request_digest,raw.digest,observations_digest(observations),Digest('sha256','f'*64))
            return VerifiedReviewResponse(evidence,tuple(CriterionAnswer(k,'satisfied',(),'real raw blob fixture') for k in plan.check_keys))
        @contextmanager
        def guard_trust(self,ctx,records):
            yield tuple(CurrentReviewTrust(r.ref,'source-fixture',1) for r in records)
    admission=EngineeringReviewAdmission(factory,controls,bindings,Source())
    reviews=ReviewUseCases(factory,SyntheticAccess(),admission,blobs=SQLiteBlobStore(lib))
    requested=reviews.plan(plan,context('request'))
    request=requested.result['request']
    recorded=reviews.record_response(plan.review_id,b'{"fixture":"actual stored raw bytes"}',context('record'),expected_request_version=request['version'],fence=request['fence'])
    assert recorded.status=='completed'
    assert not reviews.gate(plan.requirement,context('gate')).satisfied
