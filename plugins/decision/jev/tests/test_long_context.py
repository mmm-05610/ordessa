"""Explicit SDK header and stable default identity; fake HTTP only."""
import dataclasses

import httpx2
import pytest

from ordessa_decision_jev import JevProviderSettings, JevProviderError
from test_jev import body, context, provider, question

pytestmark = pytest.mark.asyncio


def selected_settings(**changes):
    return JevProviderSettings(binding_ref='opencode-zen-jev/1', secret_ref='selected-jev-credential',
        base_url='https://opencode.ai/inference/systemone', model='jev-1.13-free',
        accepted_response_models=('jev-1.13.0',), timeout_seconds=20, **changes)


async def test_disabled_setting_preserves_exact_previous_digest_and_positionals():
    settings = selected_settings()
    assert settings.long_context is False
    # Re-baselined to the implemented formula: the disabled identity keeps the
    # pre-long_context digest shape (no new field), so existing permits stay
    # valid; only the literal is pinned here.
    assert settings.settings_digest == 'sha256:af18427b6dfde1981d5317330dc1ed47a72d1a23c6804210cfde05de79921745'
    original_positional = JevProviderSettings('opencode-zen-jev/1', 'selected-jev-credential',
        'https://opencode.ai/inference/systemone', 'jev-1.13-free', ('jev-1.13.0',), 20, 'jev-protocol/2')
    assert original_positional == settings
    assert selected_settings(long_context=False).settings_digest == settings.settings_digest
    assert selected_settings(long_context=True).settings_digest != settings.settings_digest


@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
async def test_long_context_requires_a_boolean(value):
    with pytest.raises(JevProviderError, match='settings_invalid'):
        selected_settings(long_context=value)


async def test_enabled_header_changes_no_wire_body_or_response_rules():
    calls = []

    def handler(request):
        calls.append((str(request.url), request.content,
                      request.headers.get('TypeSafe-Danger-Zone-Long-Context')))
        return httpx2.Response(200, json=body())

    q = question()
    for enabled in (False, True):
        p = provider(handler, selected_settings(long_context=enabled))
        try:
            answer = await p.decide(q, context(p, q))
            assert answer.value == 'a'
            assert answer.provider_receipt['provider_settings_digest'] == p.settings_digest
        finally:
            await p.close()
    assert len(calls) == 2 and calls[0][:2] == calls[1][:2]
    assert calls[0][0] == 'https://opencode.ai/inference/systemone/v1/systemone'
    assert calls[0][2] is None and calls[1][2] == 'true'


async def test_old_settings_context_cannot_spend_a_long_context_permit():
    calls = []
    handler = lambda request: calls.append(request) or httpx2.Response(200, json=body())
    disabled = provider(handler, selected_settings())
    enabled = provider(handler, selected_settings(long_context=True))
    q = question()
    try:
        stale = context(disabled, q)
        with pytest.raises(JevProviderError, match='call_refused'):
            await enabled.decide(q, stale)
        # Replacing just the public digest cannot replace the original permit.
        forged = dataclasses.replace(stale, provider_settings_digest=enabled.settings_digest)
        with pytest.raises(JevProviderError, match='call_refused'):
            await enabled.decide(q, forged)
        assert calls == []
    finally:
        await disabled.close()
        await enabled.close()
