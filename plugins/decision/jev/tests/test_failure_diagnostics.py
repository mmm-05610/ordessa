"""Allowlisted HTTP diagnostics through the real SDK; fake transport only."""
import json
import logging
import traceback

import httpx2
import pytest
from typesafe_sdk import TypeSafeBadRequestError

from ordessa_decision_jev import JevProviderError
from ordessa_decision_jev.provider import _safe_request_errors
from test_jev import context, provider, question

pytestmark = pytest.mark.asyncio
MARKER = 'private-source-key-question-option-message'


@pytest.mark.parametrize('status', [400, 422])
async def test_schema_error_retains_only_codes_and_canonical_paths(status, caplog):
    detail = [
        {'type': 'too_long', 'loc': ['body', 'state', MARKER, 7]},
        {'type': 'literal_error', 'loc': ['body', 'model']},
        {'type': 'missing', 'loc': ['body', 'questions', MARKER, 'choice', 'criteria', MARKER]},
        {'type': 'string_type', 'loc': ['body', 'questions', MARKER, 'instructions', MARKER]},
        {'type': 'extra_forbidden', 'loc': ['body', 'questions', MARKER, MARKER]},
        {'type': MARKER, 'loc': ['body', 'model']},
        {'type': 'missing', 'loc': ['headers', MARKER]},
        {'type': 'missing', 'loc': ['body', MARKER]},
    ]
    for item in detail:
        item.update(msg=MARKER, input=MARKER, ctx={'actual': MARKER})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={'detail': detail, 'message': MARKER,
                                            'error': {'code': MARKER}},
                               headers={'x-typesafe-request-id': MARKER})

    p = provider(handler); q = question(); ctx = context(p, q)
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(JevProviderError) as caught:
            await p.decide(q, ctx)
        projection = p.last_failure_for(ctx.run_id)
        assert projection['request_errors'] == (
            {'code': 'too_long', 'path': 'body.state'},
            {'code': 'literal_error', 'path': 'body.model'},
            {'code': 'missing', 'path': 'body.questions.*.criteria'},
            {'code': 'string_type', 'path': 'body.questions.*.instructions'},
            {'code': 'extra_forbidden', 'path': 'body.questions'},
        )
        assert projection['http_status'] == status and projection['category'] == 'http_status'
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert MARKER not in (json.dumps(projection) + caplog.text + repr(caught.value)
                              + ''.join(traceback.format_exception(caught.value)))
        with pytest.raises(JevProviderError, match='call_refused'):
            await p.decide(q, ctx)
        assert len(calls) == 1
    finally:
        await p.close()


@pytest.mark.parametrize('payload', [
    MARKER, None, [MARKER], {'error': {'code': MARKER, 'message': MARKER}},
    {'detail': MARKER}, {'detail': [{'type': MARKER, 'loc': ['body', 'model']}]},
    {'detail': [{'type': 'missing', 'loc': MARKER}]},
])
async def test_unrecognized_error_body_has_no_new_projection(payload):
    p = provider(lambda request: httpx2.Response(400, json=payload))
    q = question(); ctx = context(p, q)
    try:
        with pytest.raises(JevProviderError) as caught:
            await p.decide(q, ctx)
        projection = p.last_failure_for(ctx.run_id)
        assert projection['http_status'] == 400 and 'request_errors' not in projection
        assert MARKER not in repr(projection) + str(caught.value)
    finally:
        await p.close()


async def test_diagnostic_work_and_output_are_bounded():
    codes = ('missing', 'extra_forbidden', 'string_type', 'dict_type', 'list_type',
             'model_type', 'literal_error', 'union_tag_invalid', 'union_tag_not_found',
             'too_short', 'too_long', 'int_type', 'float_type', 'bool_type',
             'value_error', 'json_invalid')
    detail = [{'type': code, 'loc': ['body', 'model'], 'input': MARKER} for code in codes]
    detail.extend([{'type': 'missing', 'loc': ['body', 'state'], 'msg': MARKER}] * 1000)
    error = TypeSafeBadRequestError(400, {'detail': detail}, httpx2.Headers(), message='unused')
    result = _safe_request_errors(error)
    assert len(result) == 16 and all(path == 'body.model' for _, path in result)
    assert ('missing', 'body.state') not in result and MARKER not in repr(result)


async def test_diagnostic_does_not_inspect_other_exception_attributes():
    class GuardedError(TypeSafeBadRequestError):
        @property
        def headers(self):
            raise AssertionError('Headers must not be read')

        @headers.setter
        def headers(self, value):
            pass

        def __str__(self):
            raise AssertionError('Exception text must not be read')

        def __repr__(self):
            raise AssertionError('Exception representation must not be read')

    error = GuardedError(400, {'detail': [{'type': 'missing', 'loc': ['body', 'model'],
                                        'msg': MARKER}]}, httpx2.Headers(), message=MARKER)
    assert _safe_request_errors(error) == (('missing', 'body.model'),)


@pytest.mark.parametrize('payload,expected', [
    ({'error': {'code': 'max_tokens_exceeded', 'message': MARKER}}, ('max_tokens_exceeded',)),
    ({'detail': 'max_tokens_exceeded', 'input': MARKER}, ('max_tokens_exceeded',)),
    ({'detail': {'error_type': 'max_tokens_exceeded', 'message': MARKER}}, ('max_tokens_exceeded',)),
    ({'detail': {'error_type': MARKER}}, ()),
    ({'message': 'Invalid API key', 'input': MARKER}, ('invalid_api_key',)),
    ({'error': {'message': MARKER}}, ()),
    ({'message': MARKER + 'max_tokens_exceeded'}, ()),
])
async def test_only_finite_provider_codes_are_retained(payload, expected):
    p = provider(lambda request: httpx2.Response(400, json=payload))
    q = question(); ctx = context(p, q)
    try:
        with pytest.raises(JevProviderError):
            await p.decide(q, ctx)
        projection = p.last_failure_for(ctx.run_id)
        assert projection.get('provider_codes', ()) == expected
        assert MARKER not in json.dumps(projection)
    finally:
        await p.close()
