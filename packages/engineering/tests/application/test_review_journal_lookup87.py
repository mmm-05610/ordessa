"""Exact scoped journal lookup on original SQLite; proof bodies are explicit peers."""
from dataclasses import asdict

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest


SCOPE = Scope('realm', 'project')
DIGEST = Digest('sha256', 'a' * 64)


@pytest.fixture
def journal_factory(tmp_path):
    path = (tmp_path / 'journal.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='review-journal87', schema_version=5)
    try:
        yield SQLiteUoWFactory(library), path
    finally:
        library.close()


def append(factory, request_id, *, scope=SCOPE, state='completed', review_id='review',
           digest=DIGEST, operation='engineering.reviews.request', with_proof=True):
    key = CommandKey(scope.realm_id, 'principal', request_id)
    with factory.begin(scope) as uow:
        entry = uow.commands.reserve(key, project_id=scope.project_id, operation=operation,
            operation_id='operation-' + request_id, request_digest=DIGEST).entry
        if state != 'pending':
            result = ({'work_review': {'review_id': review_id, 'plan_digest': asdict(digest)}}
                      if with_proof else {'request': {'review_id': review_id}})
            entry = uow.commands.complete(key, expected_version=entry.version,
                state=state, result_bytes=canonical_bytes(result))
        uow.commit()
        return entry


def lookup(factory, *, scope=SCOPE, review_id='review', digest=DIGEST):
    with factory.begin(scope, 'read') as uow:
        return uow.commands.find_completed_review_request(scope,
            review_id=review_id, plan_digest=digest)


def test_exact_original_entry_is_recovered_after_reopen(journal_factory):
    factory, path = journal_factory
    original = append(factory, 'original')
    assert lookup(factory) == original
    reopened = EngineeringLibrary.open(path, library_id='review-journal87')
    try:
        assert lookup(SQLiteUoWFactory(reopened)) == original
    finally:
        reopened.close()


def test_query_does_not_adopt_other_scope_plan_digest_or_operation(journal_factory):
    factory, _ = journal_factory
    append(factory, 'foreign', scope=Scope('realm', 'other-project'))
    append(factory, 'other-review', review_id='other-review')
    append(factory, 'other-digest', digest=Digest('sha256', 'b' * 64))
    append(factory, 'other-operation', operation='engineering.artifacts.create')
    assert lookup(factory) is None
    original = append(factory, 'original')
    assert lookup(factory) == original
    with factory.begin(SCOPE, 'read') as uow:
        with pytest.raises(ApplicationError, match='SCOPE_MISMATCH'):
            uow.commands.find_completed_review_request(Scope('realm', 'other-project'),
                review_id='review', plan_digest=DIGEST)


@pytest.mark.parametrize('state,with_proof', (
    ('pending', True), ('rejected', True), ('completed', False),
))
def test_pending_rejected_and_historical_missing_proof_are_not_evidence(
        journal_factory, state, with_proof):
    factory, _ = journal_factory
    append(factory, 'unavailable', state=state, with_proof=with_proof)
    assert lookup(factory) is None


def test_ambiguous_results_refuse_instead_of_selecting_latest(journal_factory):
    factory, _ = journal_factory
    append(factory, 'first')
    append(factory, 'second')
    with pytest.raises(ApplicationError, match='REVIEW_WORK_PROOF_AMBIGUOUS'):
        lookup(factory)
