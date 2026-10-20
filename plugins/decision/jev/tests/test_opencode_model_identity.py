"""Exact official route alias; original SDK/native identity still enforced."""
import asyncio
import dataclasses
from types import SimpleNamespace

import httpx2
import pytest

from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings, JevProviderError
from test_jev import body, context, question

pytestmark = pytest.mark.asyncio


def settings(**changes):
    return JevProviderSettings(base_url='https://opencode.ai/inference/systemone',
        model='jev-1.13-free', accepted_response_models=('jev-1.13.0',), **changes)


async def test_official_free_route_echo_keeps_native_receipt_and_no_retry():
    calls=[]
    payload=body(); payload['model']='jev-1.13-free'
    def handler(request):
        calls.append(request)
        return httpx2.Response(200,json=payload)
    p=JevDecisionProvider(settings(),secret_resolver=lambda _:'offline-test-key',
        transport=httpx2.MockTransport(handler)); q=question()
    try:
        answer=await p.decide(q,context(p,q))
        assert len(calls)==1
        assert str(calls[0].url)=='https://opencode.ai/inference/systemone/v1/systemone'
        assert answer.value=='a'
        assert answer.provider_receipt['requested_model']=='jev-1.13-free'
        assert answer.provider_receipt['resolved_model']=='jev-1.13-free'
        assert answer.provider_receipt['protocol_validation_version']=='jev-protocol/2'
    finally:await p.close()


@pytest.mark.parametrize('changes,returned',[
    ({},'jev-1.13'), ({},'jev-1.13.1'), ({},'jev-latest'), ({},'untrusted'),
    ({'model':'jev-1.13'},'jev-1.13-free'),
    ({'accepted_response_models':('different',)},'jev-1.13-free'),
    ({'base_url':'https://api.typesafe.ai'},'jev-1.13-free'),
    ({'base_url':'https://opencode.ai/zen'},'jev-1.13-free'),
    ({'base_url':'https://opencode.ai/inference'},'jev-1.13-free'),
    ({'base_url':'https://opencode.ai.evil.test/inference'},'jev-1.13-free'),
    ({'base_url':'https://opencode.ai:444/inference'},'jev-1.13-free'),
])
async def test_other_model_or_route_still_refuses(changes,returned):
    selected=dataclasses.replace(settings(),**changes)
    payload=body();payload['model']=returned
    calls=[]
    def handler(request):calls.append(request);return httpx2.Response(200,json=payload)
    p=JevDecisionProvider(selected,secret_resolver=lambda _:'offline-test-key',
        transport=httpx2.MockTransport(handler));q=question()
    try:
        with pytest.raises(JevProviderError) as error:await p.decide(q,context(p,q))
        assert error.value.code=='protocol_invalid'
        assert error.value.diagnostic=='model_identity'
        assert len(calls)==1
    finally:await p.close()


async def test_route_alias_does_not_hide_sdk_native_model_mismatch():
    payload=body();payload['model']='jev-1.13-free'
    p=JevDecisionProvider(settings(),secret_resolver=lambda _:'offline-test-key',
        transport=httpx2.MockTransport(lambda _:httpx2.Response(200,json=payload)))
    try:
        with pytest.raises(JevProviderError) as error:
            p._map_response(question(),SimpleNamespace(
                model='jev-1.13.0',raw_http_response=httpx2.Response(200,json=payload)))
        assert error.value.diagnostic=='model_identity'
    finally:await p.close()


async def test_changed_validation_rule_has_new_settings_fingerprint():
    assert settings().settings_digest != dataclasses.replace(
        settings(), base_url='https://opencode.ai/inference').settings_digest
    with pytest.raises(JevProviderError,match='settings_invalid'):
        settings(protocol_validation_version='jev-protocol/1')
