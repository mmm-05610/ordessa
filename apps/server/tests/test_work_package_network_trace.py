"""One-shot host diagnostics: native phases only; no network or credentials."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeNotFoundError

pytestmark = pytest.mark.asyncio
MODULE = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/probe-work-package-generation.py'
spec = importlib.util.spec_from_file_location('work_package_trace_test', MODULE)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
MARKER = 'private-header-body-host-exception-message'


async def attach(client):
    request = httpx2.Request('POST', 'https://example.invalid', headers={'authorization': MARKER}, content=MARKER)
    await client.event_hooks['request'][0](request)
    return request.extensions['trace']


async def test_connection_failure_keeps_only_native_phase_types_and_errno():
    holder = {}; client = driver.jev_http_client(holder, 20)
    try:
        assert client.trust_env is True and client.timeout == httpx2.Timeout(20)
        trace = await attach(client)
        root = OSError(-3, MARKER)
        error = httpx2.ConnectError(MARKER)
        error.__cause__ = root
        await trace('connection.connect_tcp.started', {'host': MARKER})
        await trace('connection.connect_tcp.failed', {'exception': error})
        record = holder['jev_network_trace'][0]
        assert record['origin_write_started'] is False
        assert record['response_headers_received'] is False
        assert record['events'][-1]['errno'] == -3
        assert record['events'][-1]['cause_types'] == ['ConnectError', 'OSError']
        assert MARKER not in json.dumps(holder)
    finally:
        await client.aclose()


async def test_proxy_connect_does_not_count_as_origin_send_or_response():
    holder = {}; client = driver.jev_http_client(holder, 20)
    try:
        trace = await attach(client)
        await trace('http11.send_request_headers.started', {'request': SimpleNamespace(method=b'CONNECT', headers=MARKER)})
        await trace('http11.receive_response_headers.complete', {'return_value': MARKER})
        record = holder['jev_network_trace'][0]
        assert record['proxy_tunnel_seen'] is True
        assert record['origin_write_started'] is record['response_headers_received'] is False
        await trace('proxy.start_tls.failed', {'exception': httpx2.ConnectError(MARKER)})
        assert record['events'][-1]['event'] == 'proxy.start_tls.failed'
        assert record['origin_write_started'] is False
        await trace('http11.send_request_headers.started', {'request': SimpleNamespace(method=b'POST', headers=MARKER)})
        await trace('http11.receive_response_headers.complete', {'return_value': MARKER})
        assert record['origin_write_started'] is record['response_headers_received'] is True
        for _ in range(40):
            await trace('http11.send_request_body.complete', {'return_value': MARKER})
        assert len(record['events']) == 32 and MARKER not in json.dumps(holder)
    finally:
        await client.aclose()


async def test_sdk_keeps_same_client_timeout_and_zero_retries():
    holder = {}; client = driver.jev_http_client(holder, 20)
    calls = []

    async def send(request, **kwargs):
        calls.append(request)
        for hook in client.event_hooks['request']:
            await hook(request)
        return httpx2.Response(404, json={'message': MARKER}, request=request)

    client.send = send
    async with AsyncTypeSafeClient(api_key='non-secret-test-placeholder',
            base_url='https://example.invalid', model='jev-1.13-free',
            timeout=20, retry=RetryPolicy(max_retries=0), http_client=client) as sdk:
        with pytest.raises(TypeSafeNotFoundError):
            await sdk.models.list()
    assert len(calls) == 1 and client.is_closed
    assert calls[0].extensions['timeout'] == {'connect': 20, 'read': 20, 'write': 20, 'pool': 20}
    assert MARKER not in json.dumps(holder)
