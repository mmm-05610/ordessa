# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_protocols.py, verbatim)
"""G1: the protocol vocabulary and model-fact validation, frozen.

The canonical set is pinned byte-for-byte against the legacy shared vocabulary
(research.md R-5); the dialect folds and the typed refusals are the behavior
existing wire consumers observe. A counterexample here is any loosening - an
unknown protocol that normalizes instead of refusing, or an invented default
fact - and each test below fails on exactly that.
"""
from __future__ import annotations

import pytest
from ordessa_server.errors import ServerError

from ordessa_model_provider.protocols import (
    CANONICAL_PROTOCOLS, normalize_model_facts, normalize_protocol,
    normalize_protocols, normalize_wire_api, validate_capabilities,
    validate_endpoints,
)


def test_canonical_vocabulary_is_frozen():
    assert CANONICAL_PROTOCOLS == (
        "openai-chat", "openai-responses", "anthropic-messages", "gemini-generate",
    )


def test_dialects_collapse_onto_canonical_values():
    assert normalize_protocol("chat") == "openai-chat"
    assert normalize_protocol("chat_completions") == "openai-chat"
    assert normalize_protocol("  Responses ") == "openai-responses"
    assert normalize_protocol("anthropic") == "anthropic-messages"
    assert normalize_protocol("gemini") == "gemini-generate"
    assert normalize_protocol("openai-chat") == "openai-chat"  # passthrough


def test_unknown_protocol_is_a_typed_refusal():
    with pytest.raises(ServerError) as excinfo:
        normalize_protocol("gpt-talk")
    assert excinfo.value.code == "PROTOCOL_UNKNOWN"
    assert excinfo.value.status == 422


def test_refusal_covers_every_entry_point():
    """Counterexample proof: loosening any single entry to a passthrough fails
    its assertion here - the refusal is not an implementation detail of one
    function."""
    for call in (
        lambda: normalize_protocol("gpt-talk"),
        lambda: normalize_protocols(["gpt-talk"]),
        lambda: normalize_wire_api("gpt-talk"),
    ):
        with pytest.raises(ServerError) as excinfo:
            call()
        assert excinfo.value.code == "PROTOCOL_UNKNOWN"


def test_normalize_protocols_dedupes_and_orders_canonically():
    assert normalize_protocols(["gemini", "chat", "ANTHROPIC"]) == [
        "openai-chat", "anthropic-messages", "gemini-generate",
    ]


def test_normalize_protocols_requires_a_list():
    with pytest.raises(ServerError) as excinfo:
        normalize_protocols("openai-chat")
    assert excinfo.value.code == "PROTOCOL_UNKNOWN"


def test_normalize_wire_api_preserves_absence():
    assert normalize_wire_api(None) is None
    assert normalize_wire_api("responses") == "openai-responses"


def test_endpoint_keys_must_be_declared():
    with pytest.raises(ServerError) as excinfo:
        validate_endpoints({"gemini": "https://x.test/v1"}, ["openai-chat"])
    assert excinfo.value.code == "PROFILE_CONFIGURATION_INVALID"


def test_endpoint_urls_follow_storage_syntax_not_probe_dns_policy():
    with pytest.raises(ServerError):
        validate_endpoints({"chat": "http://10.0.0.5/v1"}, ["openai-chat"])
    assert validate_endpoints({"chat": "https://10.0.0.5/v1"}, ["openai-chat"]) == {
        "openai-chat": "https://10.0.0.5/v1",
    }
    normalized = validate_endpoints(
        {"chat": "http://127.0.0.1:8080/v1", "responses": "https://127.0.0.1:9443/v1"},
        ["openai-chat", "openai-responses"],
    )
    assert normalized == {
        "openai-chat": "http://127.0.0.1:8080/v1",
        "openai-responses": "https://127.0.0.1:9443/v1",
    }


def test_storing_endpoint_never_resolves_dns_but_probe_still_blocks_fake_ip(monkeypatch):
    import socket
    from ordessa_model_provider.probe import ProbeError, _validate_endpoint

    calls = []
    def fake_dns(*args, **kwargs):
        calls.append(args)
        return [(socket.AF_INET, None, None, "", ("198.18.0.53", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    assert validate_endpoints({"chat": "https://opencode.ai/zen/go/v1/"}, ["openai-chat"]) == {
        "openai-chat": "https://opencode.ai/zen/go/v1",
    }
    assert calls == []
    with pytest.raises(ProbeError) as excinfo:
        _validate_endpoint("https://opencode.ai/zen/go/v1/")
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"
    assert len(calls) == 1


def test_capabilities_refuse_undocumented_keys():
    with pytest.raises(ServerError) as excinfo:
        validate_capabilities({"toolCall": True, "mystery": 1})
    assert excinfo.value.code == "PROVIDER_MODEL_INVALID"


@pytest.mark.parametrize("url", ["ftp://example.com/v1", "https://", "https://x.test:bad/v1",
                                 "https://x.test:70000/v1", "https://x.test:0/v1",
                                 "https://user:secret@x.test/v1", "https://x.test/v1?key=secret",
                                 "https://x.test/v1#fragment", "https://[broken/v1"])
def test_stored_endpoint_still_refuses_invalid_or_secret_bearing_urls(url):
    with pytest.raises(ServerError) as caught:
        validate_endpoints({"chat": url}, ["openai-chat"])
    assert caught.value.code == "PROFILE_CONFIGURATION_INVALID"


def test_model_facts_preserve_absence():
    bare = normalize_model_facts({"modelId": "m1", "displayName": "m1",
                                  "availability": "available", "unavailableReason": None})
    assert "protocols" not in bare
    assert "capabilities" not in bare
    stated = normalize_model_facts({"modelId": "m2", "displayName": "m2",
                                    "availability": "available", "unavailableReason": None,
                                    "protocols": ["chat"],
                                    "capabilities": {"reasoning": True}})
    assert stated["protocols"] == ["openai-chat"]
    assert stated["capabilities"] == {"reasoning": True}
