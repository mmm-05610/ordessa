"""Injected HTTP client ownership stays with the real Typesafe SDK path."""
import json
import time

import httpx2
import pytest
from ordessa_decision.definitions import CallPermit, DecisionQuestion, ModelCallContext, PolicyRef
from ordessa_decision_jev import JevDecisionProvider, JevProviderError, JevProviderSettings


POLICY = PolicyRef("http-client-test", "1", "sha256:test")


def _question():
    return DecisionQuestion(
        "q", "1", "choice", {"sample": "data"}, "Choose the supported answer.",
        options={"a": "first", "b": "second"}, policy_ref=POLICY,
    )


def _context(provider, question):
    deadline = time.monotonic() + 10
    return ModelCallContext(
        "run", "call", 1, question.question_digest, provider.settings_digest,
        deadline, CallPermit("run", question.question_digest,
                             provider.settings_digest, deadline),
    )


def _response():
    return {
        "model": "jev-1.13.0",
        "usage": {},
        "answers": {
            "q": {
                "type": "choice", "choice": "a", "confidence": 0.8,
                "probabilities": {"a": 0.8, "b": 0.2},
            }
        },
    }


@pytest.mark.asyncio
async def test_sdk_uses_injected_client_and_closes_it_once():
    requests = []

    async def handler(request):
        requests.append((str(request.url), json.loads(request.content)))
        return httpx2.Response(200, json=_response())

    class CountedClient(httpx2.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.close_calls = 0

        async def aclose(self):
            self.close_calls += 1
            await super().aclose()

    client = CountedClient(transport=httpx2.MockTransport(handler))
    provider = JevDecisionProvider(
        JevProviderSettings(base_url="https://jev.test", model="jev-1.13.0"),
        secret_resolver=lambda _ref: "offline-test-key",
        http_client=client,
    )
    question = _question()
    try:
        assert provider._client._http_client is client
        answer = await provider.decide(question, _context(provider, question))
        assert answer.value == "a"
        assert len(requests) == 1
        url, payload = requests[0]
        assert url == "https://jev.test/v1/systemone"
        assert payload["model"] == "jev-1.13.0"
    finally:
        await provider.close()
        await provider.close()
    assert client.is_closed
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_injected_client_keeps_sdk_zero_retry_behavior():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx2.Response(503, json={"message": "offline failure"})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    provider = JevDecisionProvider(
        JevProviderSettings(base_url="https://jev.test", model="jev-1.13.0"),
        secret_resolver=lambda _ref: "offline-test-key",
        http_client=client,
    )
    question = _question()
    try:
        with pytest.raises(JevProviderError):
            await provider.decide(question, _context(provider, question))
        assert len(requests) == 1
        assert str(requests[0].url) == "https://jev.test/v1/systemone"
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_transport_and_http_client_are_rejected_before_secret_resolution():
    client = httpx2.AsyncClient()
    secret_reads = []
    try:
        with pytest.raises(JevProviderError, match="settings_invalid"):
            JevDecisionProvider(
                JevProviderSettings(),
                secret_resolver=lambda ref: secret_reads.append(ref) or "offline-test-key",
                transport=httpx2.MockTransport(lambda _request: httpx2.Response(200)),
                http_client=client,
            )
        assert secret_reads == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_invalid_http_client_is_rejected_before_secret_resolution():
    secret_reads = []
    with pytest.raises(JevProviderError, match="settings_invalid"):
        JevDecisionProvider(
            JevProviderSettings(),
            secret_resolver=lambda ref: secret_reads.append(ref) or "offline-test-key",
            http_client=object(),
        )
    assert secret_reads == []
