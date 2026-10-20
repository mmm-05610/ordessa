"""Public review text and Work use the same original response journal identity."""
import asyncio
from dataclasses import asdict

import pytest

from ordessa_engineering.application.api import EngineeringService, ReadSet, ApplicationError
from test_review_usecases import environment, _scope, _context, _create_source, _plan


def test_public_utf8_record_has_original_journal_digest_and_exact_replay(environment):
    library, factory, access, admission, _control = environment
    scope = _scope()
    plan = _plan(scope, _create_source(factory, scope))
    service = EngineeringService(factory, access, review_admission=admission, blobs=admission.blobs)
    assert asyncio.run(service.execute('engineering.reviews.request', {'plan': asdict(plan)},
        _context(scope, 'phase3-digest-request'))).status == 'completed'
    params = {'review_id': plan.review_id, 'request_version': 0, 'fence': 1,
              'raw_response_utf8': '{"answer":"受控审核内容"}'}
    context = _context(scope, 'phase3-digest-record')
    first = asyncio.run(service.execute('engineering.reviews.record', params, context))
    assert first.status == 'completed'
    with factory.begin(scope, 'read') as uow:
        entry = uow.commands.get(context.key)
    assert entry.request_digest == service.command_request_digest(
        'engineering.reviews.record', params, context, ReadSet(scope, ()))
    assert admission.blobs.read_verified(admission.last_raw_response_ref) == params['raw_response_utf8'].encode('utf-8')
    assert asyncio.run(service.execute('engineering.reviews.record', params, context)) == first
    with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT'):
        asyncio.run(service.execute('engineering.reviews.record',
            {**params, 'raw_response_utf8': params['raw_response_utf8'] + ' '}, context))
