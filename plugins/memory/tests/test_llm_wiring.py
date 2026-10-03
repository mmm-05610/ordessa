"""LLM wiring (MB-4, AR-2): bundled provider resolution and the honest
unsupported path."""
from __future__ import annotations

import pytest

from ordessa_memory import llm_wiring
from ordessa_memory.llm_wiring import WiringUnsupported, configure_payload, env_key_rows, resolve_wiring

from conftest import FakeCatalog, provider_row


def test_bundled_openai_row_resolves_with_reference_and_models():
    plan = resolve_wiring(FakeCatalog([
        provider_row("openai", "ref://openai-cred", "https://api.acme.test/v1", ("gpt-x",))]))
    assert plan.llm.provider == "openai"
    assert plan.llm.credential_ref == "ref://openai-cred"
    assert plan.llm.base_url == "https://api.acme.test/v1"
    assert plan.llm_model == "gpt-x"
    assert plan.embedder.provider == "openai"


def test_anthropic_llm_pulls_the_embedder_from_a_separate_bundled_row():
    plan = resolve_wiring(FakeCatalog([
        provider_row("anthropic", "ref://anthropic-cred", None, ("claude-x",)),
        provider_row("openai", "ref://openai-cred", None, ("gpt-y",))]))
    assert plan.llm.provider == "anthropic"
    assert plan.embedder.provider == "openai"


def test_custom_endpoint_only_is_honest_unsupported_and_never_impersonates_openai():
    """AR-2 failure counterexample: a custom OpenAI-compatible endpoint saved
    under a non-bundled name must leave the feature off — the resolver must
    not fabricate an OPENAI_API_KEY row for it."""
    catalog = FakeCatalog([
        provider_row("acme", "ref://acme-cred", "https://relay.example/v1", ("gpt-x",))])
    with pytest.raises(WiringUnsupported) as excinfo:
        resolve_wiring(catalog)
    assert "bundled provider" in excinfo.value.reason
    with pytest.raises(WiringUnsupported):
        env_key_rows(resolve_wiring(catalog))


def test_bundled_provider_without_credential_reference_is_unsupported():
    catalog = FakeCatalog([provider_row("openai", credential_id=None)])
    with pytest.raises(WiringUnsupported):
        resolve_wiring(catalog)


def test_archived_bundled_row_is_ignored():
    catalog = FakeCatalog([provider_row("openai", archived_at="2026-09-01T00:00:00Z")])
    with pytest.raises(WiringUnsupported):
        resolve_wiring(catalog)


def test_absent_catalog_is_unsupported():
    with pytest.raises(WiringUnsupported):
        resolve_wiring(None)


def test_env_key_rows_map_to_the_upstream_env_names():
    plan = resolve_wiring(FakeCatalog([
        provider_row("anthropic", "ref://anthropic-cred"),
        provider_row("openai", "ref://openai-cred")]))
    rows = env_key_rows(plan)
    assert rows == {"ANTHROPIC_API_KEY": "ref://anthropic-cred",
                    "OPENAI_API_KEY": "ref://openai-cred"}


def test_embedder_reuses_the_llm_credential_when_the_llm_is_an_embedder():
    plan = resolve_wiring(FakeCatalog([
        provider_row("openai", "ref://openai-cred")]))
    assert env_key_rows(plan) == {"OPENAI_API_KEY": "ref://openai-cred"}


def test_configure_payload_carries_base_url_for_openai_and_never_keys():
    plan = resolve_wiring(FakeCatalog([
        provider_row("openai", "ref://openai-cred", "https://api.acme.test/v1", ("gpt-x",))]))
    payload = configure_payload(plan)
    assert payload["llm"]["provider"] == "openai"
    assert payload["llm"]["config"]["openai_base_url"] == "https://api.acme.test/v1"
    assert payload["llm"]["config"]["model"] == "gpt-x"
    blob = repr(payload)
    assert "ref://" not in blob and "credential" not in blob, "keys/config refs never ride the config"


def test_configure_payload_omits_base_url_for_anthropic_no_entry():
    plan = resolve_wiring(FakeCatalog([
        provider_row("anthropic", "ref://a-cred", None, ("claude-x",)),
        provider_row("openai", "ref://o-cred", None, ("gpt-y",))]))
    payload = configure_payload(plan)
    assert "openai_base_url" not in payload["llm"]["config"]
    assert payload["embedder"]["provider"] == "openai"
