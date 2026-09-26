"""Work Order 093 stage 3: frozen execution -> native config, via the dispatcher.

The 092 passthrough (frozen execution now carries the record's `protocols` +
`endpoints`) meets the 093 renderers here. The gate that matters is the whole
"第二个上游真的落到原生文件" claim, and it must fail loudly if the wiring is
not real:

* a record-backed freeze renders that record's base URL + that family's dialect
  (NOT the `OFFICIAL_BASE_URL` constant);
* a family that cannot express the protocol is refused (`PROTOCOL_UNSUPPORTED_BY_HARNESS`)
  and writes nothing;
* a freeze with no endpoint facts materializes to ``None`` so the caller keeps
  the reviewed template bytes byte-for-byte (093 G6 "no facts => zero regression").
"""
from __future__ import annotations

import pytest

from ordessa_harness.native_materialization import (
    NativeMaterializationError, materialize_family,
)


def _frozen(provider="acme-loopback", model="m1", protocols=(), endpoints=None):
    frozen = {"provider": provider, "model": model, "credentialId": None, "configuration": {}}
    if protocols:
        frozen["protocols"] = list(protocols)
    if endpoints:
        frozen["endpoints"] = dict(endpoints)
    return frozen


URL = "http://127.0.0.1:9/v1"


def test_codex_renders_the_records_url_and_dialect_not_the_constant():
    out = materialize_family("codex", _frozen(
        protocols=["openai-chat"], endpoints={"openai-chat": URL}))
    assert out["target"] == "config.toml"
    toml = out["content"]
    assert "[model_providers.acme-loopback]" in toml
    assert f'base_url = "{URL}"' in toml          # the RECORD's url, not api.deepseek.com
    assert 'wire_api = "chat"' in toml            # the family dialect for openai-chat
    assert "api.deepseek.com" not in toml         # constant did NOT win
    # G1 hierarchy: keys live inside the provider table, never at top level.
    assert toml.index("[model_providers.") < toml.index("base_url")
    # idempotent (G5): same input -> byte-identical.
    assert materialize_family("codex", _frozen(
        protocols=["openai-chat"], endpoints={"openai-chat": URL}))["content"] == toml


def test_opencode_renders_endpoint_at_options_level():
    out = materialize_family("opencode", _frozen(
        protocols=["openai-chat"], endpoints={"openai-chat": URL}))
    content = out["content"]
    assert content["npm"] == "@ai-sdk/openai-compatible"
    assert content["options"]["baseURL"] == URL
    assert content["options"]["apiKey"].startswith("{env:")   # reference, no value


def test_claude_renders_anthropic_env():
    out = materialize_family("claude-code", _frozen(
        protocols=["anthropic-messages"], endpoints={"anthropic-messages": URL}))
    assert out["content"] == {"ANTHROPIC_BASE_URL": URL}


def test_unsupported_protocol_is_refused_and_writes_nothing():
    # claude with a chat-only upstream: typed refusal, no config produced.
    with pytest.raises(NativeMaterializationError) as exc:
        materialize_family("claude-code", _frozen(
            protocols=["openai-chat"], endpoints={"openai-chat": URL}))
    assert exc.value.code == "PROTOCOL_UNSUPPORTED_BY_HARNESS"


def test_no_facts_materializes_to_none_so_template_is_kept():
    # 093 G6: an unchanged record freezes without protocols/endpoints -> the
    # caller keeps the reviewed template bytes (this returns None, not empty write).
    assert materialize_family("codex", _frozen()) is None


def test_dsh_and_qwen_are_not_materializable_here():
    # their native protocol field is not pinned -> refuse to guess (return None).
    assert materialize_family("dsh", _frozen(
        protocols=["openai-chat"], endpoints={"openai-chat": URL})) is None
    assert materialize_family("qwen", _frozen(
        protocols=["openai-chat"], endpoints={"openai-chat": URL})) is None


def test_freeze_to_native_bytes_end_to_end_via_the_real_service(tmp_path):
    # The unblocked seam of 093: record -> freeze_execution_configuration (092's
    # passthrough) -> materialize_family, using the REAL service and repository,
    # not a hand-made frozen dict. Proves the record's URL+dialect actually reach
    # the native bytes without a live sidecar (the guest write itself is env-gated).
    from ordessa_server.idempotency import IdempotentRecords
    from ordessa_server_compat.model_configs.repository import ProviderModelRecords
    from ordessa_server_compat.model_configs.service import ProviderModelService
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
    from pacthold.storage import Database, ObjectStore

    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "codex", model_control_id="model",
        wire_protocols={"openai-chat": "chat", "openai-responses": "responses"}))
    svc = ProviderModelService(
        ProviderModelRecords(database, IdempotentRecords(database)), ObjectStore(root),
        harnesses=registry, credentials=None, profiles=None)
    created = svc.create("k1", {
        "displayName": "Loopback", "harness": None, "provider": "acme-loopback",
        "credentialId": None, "configuration": [],
        "protocols": ["openai-chat"], "endpoints": {"openai-chat": URL},
        "models": [{"modelId": "m1", "displayName": "m1", "availability": "available",
                    "unavailableReason": None}]})
    frozen = svc.freeze_execution_configuration("codex", {"model": {
        "providerId": created["id"], "modelId": "m1"}})
    out = materialize_family("codex", frozen)
    assert f'base_url = "{URL}"' in out["content"]      # record url, not the constant
    assert 'wire_api = "chat"' in out["content"]        # codex dialect for openai-chat
