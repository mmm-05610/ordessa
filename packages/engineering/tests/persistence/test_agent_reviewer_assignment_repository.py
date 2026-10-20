"""Original schema15 lower repository/control tests, not authenticated business UoW."""
from pathlib import Path
from dataclasses import replace,asdict
import runpy
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import _RepositoryAccess
from ordessa_engineering.adapters.persistence.sqlite.reviewer_assignment_repository import SQLiteReviewerAssignmentRepository
from ordessa_engineering.domain.reviews.assignments import ReviewerAssignment
from ordessa_engineering.domain.reviews.assignment_codec import decode_reviewer_assignment,encode_historical_reviewer_assignment
from ordessa_engineering.domain.reviews.models import ReviewSetKey
from ordessa_engineering.domain.reviews.codec import encode_plan,encode_requirement,encode_key
from ordessa_engineering.application.contracts.errors import ApplicationError

DOMAIN=Path(__file__).parents[1]/'domain'


def agent(name,digest='a'):
    return canonical_bytes({'schemaVersion':'agent-instance/1','namespace':'namespace','instanceId':name,
        'bindingDigest':'sha256:'+digest*64})


def original(tmp_path):
    req,plan,_=runpy.run_path(str(DOMAIN/'test_review_rules.py'))['_case']()
    library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='agent-reviewer-storage',schema_version=15)
    prefix=(plan.scope.realm_id,plan.scope.project_id);key=ReviewSetKey.for_requirement(req)
    with library.transaction() as db:
        db.execute('INSERT INTO eng_review_requirements VALUES (?,?,?,?,?,?)',prefix+(req.requirement_id,req.requirement_version,req.digest.hex,encode_requirement(req)))
        db.execute('INSERT INTO eng_review_sets VALUES (?,?,?,?,?,?,0)',prefix+(key.digest.hex,req.requirement_id,req.requirement_version,encode_key(key)))
        db.execute('INSERT INTO eng_review_plans VALUES (?,?,?,?,?,?)',prefix+(plan.review_id,key.digest.hex,plan.plan_digest.hex,encode_plan(plan)))
        db.execute("INSERT INTO eng_review_requests VALUES (?,?,?,'requested',1,0)",prefix+(plan.review_id,))
    value=ReviewerAssignment(plan.scope,'assignment',plan.review_id,plan.plan_digest,0,1,req.method_ref,
        agent('reviewer'),agent('author'),plan.reviewer_requirements,'synthetic-issuer',0,'2026-10-18T00:00:00.000000Z')
    return library,plan,value


def repo(db,scope,mode='write'):
    return SQLiteReviewerAssignmentRepository(_RepositoryAccess(db,scope,mode,'agent-reviewer-storage'))


def test_original_plan_roles_identity_control_revocation_and_cold_reopen(tmp_path):
    library,plan,value=original(tmp_path);path=library.path
    with library.transaction() as db:
        owner=repo(db,plan.scope)
        for digest in ('a','b'):
            with pytest.raises(ApplicationError,match='UNTRUSTED_REVIEWER'):
                owner.insert(replace(value,reviewer_agent_ref_bytes=agent('author',digest)))
        with pytest.raises(ApplicationError,match='REVIEWER_ASSIGNMENT_CHANGED'):
            owner.insert(replace(value,roles=('admin',)))
        assert db.execute('SELECT count(*) FROM eng_unit_reviewer_assignments').fetchone()==(0,)
        ref=owner.insert(value)
        actual,control=owner.active_for_review(plan.review_id)
        assert actual==value and control.state=='active' and control.version==0
    library.close();library=EngineeringLibrary.open(path,library_id='agent-reviewer-storage')
    with library.transaction() as db:
        owner=repo(db,plan.scope)
        assert owner.get(ref)==value
        assert owner.revoke(ref,expected_version=0,revoked_at='2026-10-18T00:01:00.000000Z',
            reason='controlled revoke',event_id='event').state=='revoked'
        with pytest.raises(ApplicationError,match='REVIEWER_ASSIGNMENT_UNAVAILABLE'):owner.active_for_review(plan.review_id)
        with pytest.raises(ApplicationError,match='REVIEWER_ASSIGNMENT_CHANGED'):
            owner.revoke(ref,expected_version=0,revoked_at='2026-10-18T00:01:00.000000Z',reason='duplicate',event_id='duplicate')
        assert db.execute('SELECT count(*) FROM eng_unit_reviewer_assignment_events').fetchone()==(1,)
    library.close()


def test_historical_assignment_is_readable_but_never_an_active_agent_role(tmp_path):
    library,plan,current=original(tmp_path)
    old=decode_reviewer_assignment((DOMAIN/'fixtures/reviewer-assignment-v1-baseline.json').read_bytes())
    old=replace(old,scope=plan.scope,review_id=plan.review_id,plan_digest=plan.plan_digest,method_ref=plan.requirement.method_ref)
    raw=encode_historical_reviewer_assignment(old)
    with library.transaction() as db:
        owner=repo(db,plan.scope)
        with pytest.raises(ApplicationError,match='AGENT_REVIEWER_ASSIGNMENT_REQUIRED'):owner.insert(old)
        # Explicit historical fixture insertion, never a production conversion.
        method=canonical_bytes(asdict(old.method_ref)).decode()
        db.execute('INSERT INTO eng_unit_reviewer_assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (old.scope.realm_id,old.scope.project_id,old.assignment_id,old.review_id,old.plan_digest.hex,0,1,
            method,old.reviewer_unit_ref_bytes.decode(),old.author_unit_ref_bytes.decode(),canonical_bytes(list(old.roles)).decode(),
            old.issuer_principal_id,old.issuer_credential_epoch,old.assigned_at,old.digest.hex,raw))
        db.execute("INSERT INTO eng_unit_reviewer_assignment_controls VALUES (?,?,?,?,?,'active',0,NULL,NULL)",
            (old.scope.realm_id,old.scope.project_id,old.assignment_id,old.review_id,0))
        assert owner.get(old.ref)==old
        with pytest.raises(ApplicationError,match='AGENT_REVIEWER_ASSIGNMENT_REQUIRED'):
            owner.revoke(old.ref,expected_version=0,revoked_at='2026-10-18T00:01:00.000000Z',
                reason='historical rows are read only',event_id='forbidden-historical-write')
        assert db.execute('SELECT count(*) FROM eng_unit_reviewer_assignment_events').fetchone()==(0,)
        with pytest.raises(ApplicationError,match='AGENT_REVIEWER_ASSIGNMENT_REQUIRED'):
            owner.check_active_control(old.assignment_id,0)
        with pytest.raises(ApplicationError,match='AGENT_REVIEWER_ASSIGNMENT_REQUIRED'):owner.active_for_review(plan.review_id)
        assert db.execute('SELECT canonical_bytes FROM eng_unit_reviewer_assignments').fetchone()==(raw,)
    library.close()


def test_original_sqlite_transaction_rolls_back_when_assignment_fence_changes(tmp_path):
    """Local COMMIT-boundary negative, not full MethodControl/business UoW."""
    library,plan,value=original(tmp_path)
    try:
        with library.transaction() as db:
            owner=repo(db,plan.scope);ref=owner.insert(value)
        before=library._connection.total_changes
        with pytest.raises(ApplicationError,match='REVIEWER_ASSIGNMENT_CHANGED'):
            with library.transaction() as db:
                owner=repo(db,plan.scope)
                owner.revoke(ref,expected_version=0,revoked_at='2026-10-18T00:01:00.000000Z',
                    reason='controlled stale fence',event_id='rolled-back-event')
                # Same original resolver used by UoW ReadSet at its COMMIT cut.
                owner.check_active_control(value.assignment_id,0)
        with library.transaction() as db:
            owner=repo(db,plan.scope)
            assert owner.control(ref).state=='active' and owner.control(ref).version==0
            assert db.execute('SELECT count(*) FROM eng_unit_reviewer_assignment_events').fetchone()==(0,)
            owner.check_active_control(value.assignment_id,0)
        assert library._connection.total_changes>before  # SQLite counts rolled-back mutations too.
    finally:library.close()
