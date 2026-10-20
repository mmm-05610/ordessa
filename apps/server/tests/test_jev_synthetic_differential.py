"""Bounded diagnostic errors and stop conditions; no network or credentials."""
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest


MODULE = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/probe-jev-synthetic-differential.py'
spec = importlib.util.spec_from_file_location('jev_synthetic_test', MODULE)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
SECRET = 'sk-non-secret-error-echo-canary'


@pytest.mark.parametrize(('body', 'category'), [
    ({'error': {'code': 'max_tokens_exceeded', 'message': 'Maximum tokens 32768 exceeded'}}, 'model_context_limit'),
    ('Context length limit exceeded: maximum 32768 tokens', 'model_context_limit'),
    ('Invalid API key', 'credential_or_permission_refused'),
    ('Permission denied', 'credential_or_permission_refused'),
    ('No provider found for model', 'model_route_refused'),
    ('Insufficient balance', 'quota_or_service_refused'),
    ('State size exceeds maximum 100000 characters', 'state_size_limit'),
])
def test_error_projection_keeps_public_reason_and_discards_secret_values(body, category):
    if type(body) is dict:
        body['error']['private-canary-field'] = SECRET
        response = httpx2.Response(400, json=body)
    else:
        response = httpx2.Response(400, text=body + '\n' + SECRET,
                                  headers={'content-type': 'text/plain', 'x-private': SECRET})
    result = driver.project_error(response, SECRET, 'synthetic-marker')
    assert result['category'] == category
    assert result['key_echo_redacted'] is True and result['raw_saved'] is False
    assert SECRET not in json.dumps(result) and 'private-canary-field' not in json.dumps(result)
    if '32768' in str(body):
        assert 32768 in result['public_limits']


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure_at', 'failure', 'expected_ids'), [
    (0, 'Invalid API key', ['A-flat-small']),
    (0, 'Unclassified upstream rejection', ['A-flat-small', 'A-two-options-only']),
    (1, 'Malformed schema', ['A-flat-small', 'B-nesting-only']),
    (2, 'max_tokens_exceeded', ['A-flat-small', 'B-nesting-only', 'C-size-only', 'C-long-header-only']),
    (3, 'max_tokens_exceeded', ['A-flat-small', 'B-nesting-only', 'C-size-only', 'D-size-only', 'D-long-header-only']),
    (0, httpx2.ConnectError('private-transport-canary'), ['A-flat-small']),
])
async def test_native_sdk_matrix_stops_without_replaying_failed_requests(monkeypatch, tmp_path,
                                                                        failure_at, failure, expected_ids):
    class KeyInput:
        def __init__(self, *args, **kwargs):
            pass

        def read(self):
            return bytearray(b'non-secret-test-placeholder')

    monkeypatch.setattr(driver, 'ExistingOpenCodeInput', KeyInput)
    posts = []
    clients = []

    async def send(client, request, **kwargs):
        clients.append(client)
        for hook in client.event_hooks['request']:
            await hook(request)
        if request.method == 'GET':
            response = httpx2.Response(404, request=request)
        else:
            payload = json.loads(request.content)
            posts.append(request)
            if len(posts) - 1 == failure_at:
                if isinstance(failure, Exception):
                    raise failure
                response = httpx2.Response(400, text=failure, request=request)
            else:
                options = payload['questions']['diagnostic']['criteria']
                response = httpx2.Response(200, request=request, json={
                    'model': 'jev-1.13.0', 'answers': {'diagnostic': {
                        'type': 'choice', 'choice': 'ready', 'confidence': 1.0,
                        'probabilities': {key: float(key == 'ready') for key in options}}},
                    'usage': {'input_tokens': 100, 'output_tokens': 10}})
        for hook in client.event_hooks['response']:
            await hook(response)
        return response

    monkeypatch.setattr(httpx2.AsyncClient, 'send', send)
    result = await driver.run(tmp_path)
    assert [case['id'] for case in result['cases']] == expected_ids
    assert len(posts) == len(expected_ids) <= 5
    assert all(client.is_closed for client in clients)
    assert result['work_created'] is result['review_ref_created'] is result['real_DID_sent'] is False
    assert 'private-transport-canary' not in json.dumps(result)
    assert all(case['wire']['question_count'] == 1 for case in result['cases'])
    if expected_ids[-1].endswith('long-header-only'):
        assert posts[-1].content == posts[-2].content
        assert posts[-1].headers[driver.LONG_HEADER] == 'true'
        assert driver.LONG_HEADER not in posts[-2].headers
