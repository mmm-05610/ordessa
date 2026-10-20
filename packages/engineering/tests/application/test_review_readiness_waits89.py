"""Original SQLite wait CAS with explicitly synthetic readiness owners.

These tests cover the two pre-request/pre-record readiness meanings. Synthetic
method/source peers are not production review policy or reviewer authority.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import reference_for
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import (
    BoundRunWait, ReviewReadiness, run_wait_row_digest,
)
from ordessa_engineering.application.contracts.method_work import ReviewWaitRequirements
from ordessa_engineering.application.usecases.queries.run_waits import CurrentRunWaitUseCases
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.models import ReviewRequestExpectation
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest

from test_review_usecases import (
    SyntheticAccess, _context, _create_source, _plan, _scope,
)


class SyntheticMethods:
    """A test peer for the selected method guard; not a production owner."""
    def __init__(self, factory):
        self.factory = factory

    @contextmanager
    def guard_method(self, context, method_ref):
        assert context.scope.project_id == 'project-1'
        yield {'method_ref': method_ref}


class SyntheticReadinessBindings:
    """Explicit test-only Work/readiness source, using the real SQLite UoW."""
    def __init__(self, factory, methods, plan, readiness, family, blob_store=None):
        self.factory, self.methods = factory, methods
        self.plan, self.readiness, self.family = plan, readiness, family
        self.blob_store = blob_store
        self.plan_guard_calls = 0
        self.response_guard_calls = 0

    @contextmanager
    def guard_wait(self, context, run_id, row):
        with self.factory.begin(context.scope, 'read') as uow:
            ordinal = uow.workflow.next_step_ordinal(run_id)
            if self.family == 'review_response_ready':
                plan = uow.reviews.get_plan(self.plan.review_id)
                request = uow.reviews.get_request(self.plan.review_id)
            else:
                plan, request = self.plan, None
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            if self.family == 'review_plan_ready':
                with self.guard_plan_ready(context, snapshot, plan,
                        phase_key=plan.requirement.phase_key,
                        input_ref=self.readiness.input_ref,
                        subject_ref=self.readiness.subject_ref, view=row) as ready:
                    condition = BoundRunWait(context.scope, run_id, run_wait_row_digest(row),
                        ordinal, self.family, readiness=ready)
                    yield condition
            elif self.family == 'review_response_ready':
                with self.guard_response_ready(context, snapshot, plan, request,
                        self.readiness.raw_response_ref,
                        phase_key=plan.requirement.phase_key,
                        input_ref=self.readiness.input_ref,
                        subject_ref=self.readiness.subject_ref, view=row) as ready:
                    condition = BoundRunWait(context.scope, run_id, run_wait_row_digest(row),
                        ordinal, self.family, readiness=ready)
                    yield condition
            else:
                condition = BoundRunWait(context.scope, run_id, run_wait_row_digest(row),
                    ordinal, 'review_gate', intent=ReviewWaitRequirements(
                        context.scope, (self.plan.requirement,)))
                yield condition

    @contextmanager
    def guard_plan_ready(self, context, snapshot, plan, *, phase_key, input_ref,
                         subject_ref, view):
        self.plan_guard_calls += 1
        if (snapshot['method_ref'] != plan.requirement.method_ref
                or phase_key != plan.requirement.phase_key
                or plan != self.plan or input_ref != self.readiness.input_ref
                or subject_ref != self.readiness.subject_ref):
            raise ApplicationError('SYNTHETIC_PLAN_BINDING_MISMATCH')
        yield self.readiness

    @contextmanager
    def guard_response_ready(self, context, snapshot, plan, request, raw_response_ref, *,
                             phase_key, input_ref, subject_ref, view):
        self.response_guard_calls += 1
        if (snapshot['method_ref'] != plan.requirement.method_ref
                or phase_key != plan.requirement.phase_key or plan != self.plan
                or raw_response_ref != self.readiness.raw_response_ref
                or input_ref != self.readiness.input_ref or subject_ref != self.readiness.subject_ref):
            raise ApplicationError('SYNTHETIC_RESPONSE_BINDING_MISMATCH')
        raw = self.blob_store.read_verified(raw_response_ref)
        raw.decode('utf-8', errors='strict')
        yield self.readiness


def _params(state):
    return {'run_id': state['run_id'], 'expected_row_digest': state['row_digest'],
        'expected_condition_digest': state['condition_digest'],
        'expected_next_step_ordinal': state['next_step_ordinal']}


@pytest.fixture
def env(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'readiness.sqlite').resolve(),
        library_id='review-readiness-test', schema_version=14)
    factory = SQLiteUoWFactory(library)
    scope = _scope()
    input_ref = _create_source(factory, scope)
    with factory.begin(scope) as uow:
        method_marker = uow.workflow.write_material(kind='method', stable_id='readiness-test',
            revision=1, body={'test_only': True}, generated=False)
        uow.workflow.insert_run(run_id='run', method_ref=method_marker,
            registry_ref={'test_only': True}, inputs={}, now=_context(scope, 'setup').received_at)
        uow.workflow.update_run(run_id='run', status='WAITING_FOR_CONDITION', cursor=1,
            wait_reason='WAITING_FOR_CONDITION', now=_context(scope, 'setup').received_at)
        uow.commit()
    plan = _plan(scope, input_ref, 'readiness-review')
    with factory.begin(scope, 'read') as uow:
        artifact = uow.engineering.get_artifact(input_ref.artifact_id)
    reads = ReadSet(scope, (ReadVersion('artifact', input_ref.artifact_id, artifact.version),))
    raw = b'{"response":"test-only"}'
    digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
    blobs = SQLiteBlobStore(library)
    raw_ref = reference_for(library.library_id, raw, digest, 'application/json')
    blobs.put_verified(raw, digest, 'application/json')
    methods = SyntheticMethods(factory)
    try:
        yield library, factory, scope, input_ref, plan, reads, raw_ref, raw, blobs, methods
    finally:
        library.close()


def _make_service(env, family, *, request=False, expectation=None):
    library, factory, scope, input_ref, plan, reads, raw_ref, raw, blobs, methods = env
    if request:
        with factory.begin(scope) as uow:
            uow.reviews.create_plan(plan)
            uow.commit()
    requests = () if expectation is None else (expectation,)
    readiness = ReviewReadiness(plan, input_ref, input_ref,
        ReadSet(scope, reads.versions, review_requests=requests), raw_ref if expectation else None)
    bindings = SyntheticReadinessBindings(factory, methods, plan, readiness, family, blobs)
    admission = None if family == 'review_gate' else SimpleNamespace(methods=methods)
    service = CurrentRunWaitUseCases(factory, SyntheticAccess(), bindings, review_admission=admission)
    return bindings, service, readiness


def _request_expectation(env):
    _, _, scope, _, plan, _, _, _, _, _ = env
    return ReviewRequestExpectation(scope, plan.review_id, plan.plan_digest, 0, 1)


def test_plan_ready_advances_before_any_review_request_and_replays_exactly(env):
    library, factory, scope, _, plan, _, _, _, _, _ = env
    bindings, service, readiness = _make_service(env, 'review_plan_ready')
    assert readiness.read_set.review_requests == ()
    state = service.read({'run_id': 'run'}, _context(scope, 'query'))
    resume_context = _context(scope, 'resume')
    result = service.resume(_params(state), resume_context)
    assert result.status == 'completed'
    assert result.result['status'] == 'RUNNING'
    assert service.resume(_params(state), resume_context) == result
    assert bindings.plan_guard_calls == 2  # current read and resume, source guard remains in both
    with library._read_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM eng_review_requests WHERE review_id=?',
            (plan.review_id,)).fetchone()[0] == 0
    with factory.begin(scope, 'read') as uow:
        assert uow.workflow.run_row('run')['status'] == 'RUNNING'


def test_response_ready_requires_exact_requested_plan_but_not_a_record_or_gate(env):
    library, factory, scope, _, plan, _, _, _, _, _ = env
    expectation = _request_expectation(env)
    bindings, service, readiness = _make_service(env, 'review_response_ready',
        request=True, expectation=expectation)
    state = service.read({'run_id': 'run'}, _context(scope, 'query'))
    result = service.resume(_params(state), _context(scope, 'resume'))
    assert result.status == 'completed'
    assert result.result['status'] == 'RUNNING'
    assert bindings.response_guard_calls == 2
    with factory.begin(scope, 'read') as uow:
        request = uow.reviews.get_request(plan.review_id)
        assert request.state == 'requested' and request.version == 0 and request.fence == 1
    with library._read_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM eng_reviews WHERE review_id=?',
            (plan.review_id,)).fetchone()[0] == 0


def test_withdrawn_request_and_stale_work_row_refuse_without_advancing(env):
    _, factory, scope, _, plan, _, _, _, _, _ = env
    bindings, service, _ = _make_service(env, 'review_response_ready',
        request=True, expectation=_request_expectation(env))
    state = service.read({'run_id': 'run'}, _context(scope, 'query'))
    with factory.begin(scope) as uow:
        uow.reviews.withdraw_request(plan.review_id, expected_version=0, fence=1)
        uow.commit()
    with pytest.raises(ApplicationError, match='REVIEW_REQUEST_CHANGED'):
        service.resume(_params(state), _context(scope, 'resume'))
    with factory.begin(scope, 'read') as uow:
        assert uow.workflow.run_row('run')['status'] == 'WAITING_FOR_CONDITION'


def test_stale_request_expectation_and_changed_work_row_refuse(env):
    _, factory, scope, _, plan, _, _, _, _, _ = env
    stale = ReviewRequestExpectation(scope, plan.review_id, plan.plan_digest, 1, 1)
    _, service, _ = _make_service(env, 'review_response_ready', request=True, expectation=stale)
    with pytest.raises(ApplicationError, match='REVIEW_REQUEST_CHANGED'):
        service.read({'run_id': 'run'}, _context(scope, 'stale-query'))


def test_changed_work_row_refuses_resume(env):
    _, factory, scope, _, _, _, _, _, _, _ = env
    _, service, _ = _make_service(env, 'review_plan_ready')
    state = service.read({'run_id': 'run'}, _context(scope, 'row-query'))
    with factory.begin(scope) as uow:
        uow.workflow.update_run(run_id='run', status='WAITING_FOR_CONDITION', cursor=2,
            wait_reason='WAITING_FOR_CONDITION', now=_context(scope, 'row-change').received_at)
        uow.commit()
    with pytest.raises(ApplicationError, match='RUN_WAIT_CHANGED'):
        service.resume(_params(state), _context(scope, 'row-resume'))


def test_old_review_gate_still_requires_the_original_satisfied_gate(env):
    _, _, scope, _, _, _, _, _, _, _ = env
    bindings, service, _ = _make_service(env, 'review_gate')
    with pytest.raises(ApplicationError, match='REVIEW_AUTHORITY_UNAVAILABLE'):
        service.read({'run_id': 'run'}, _context(scope, 'query'))


def test_old_wait_digest_projection_does_not_add_null_readiness(env):
    _, _, scope, input_ref, _, _, _, _, _, _ = env
    condition = BoundRunWait(scope, 'run', Digest('sha256', 'c' * 64), 0,
        'object_exists', (input_ref,))
    historical_projection = asdict(condition)
    historical_projection.pop('readiness')
    assert condition.digest == record_digest('bound-run-wait', historical_projection)


def test_plan_readiness_requires_input_artifact_version_and_matching_scope(env):
    _, _, scope, input_ref, plan, _, raw_ref, _, _, _ = env
    with pytest.raises(ReferenceError, match='INVALID_REVIEW_READINESS'):
        ReviewReadiness(plan, input_ref, input_ref, ReadSet(scope, ()), None)
    wrong_scope = _scope('other-project')
    with pytest.raises(ReferenceError, match='REALM_MISMATCH'):
        ReviewReadiness(plan, input_ref, input_ref,
            ReadSet(wrong_scope, (ReadVersion('artifact', input_ref.artifact_id, 0),)), raw_ref)
