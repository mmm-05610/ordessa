"""Work Order 092 stage 4: compatibility derivation (G4) + freeze enforcement (G5).

The whole point of layer 1 is that the *answer to "can this harness use this
upstream?"* is derived from what both sides declare, never stored. So:

* G4 - with a provider declaring protocols and two families declaring
  ``wireProtocols``, ``providerModels.list`` carries exactly the derived pairs,
  stable-sorted, and re-derives live when a family's declaration changes;
* G4/unknown - an undeclared record is ``protocolsDeclared: false`` + empty
  compatibility, and is *not* treated as unavailable;
* G5 - a freeze whose two declared sides share no protocol is a typed
  ``PROTOCOL_INCOMPATIBLE``, and adding the missing protocol to the record makes
  the same reference pass (the counterexample must actually run).

The compatibility lives only in the read projection; the DB has no such column.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution import HarnessDescriptor, HarnessDescriptorError, HarnessRegistry
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.model_configs.repository import ProviderModelRecords
from ordessa_server_compat.model_configs.service import ProviderModelService
from pacthold.storage import Database, ObjectStore


def _descriptor(harness, *, wire=None, model_control="model", credential=None):
    return HarnessDescriptor(harness, credential_kind=credential,
                             model_control_id=model_control,
                             wire_protocols=wire or {})


def _service(tmp_path, registry):
    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    records = ProviderModelRecords(database, IdempotentRecords(database))
    objects = ObjectStore(root)
    return ProviderModelService(records, objects, harnesses=registry,
                                credentials=None, profiles=None)


def _model(mid="m1"):
    return {"modelId": mid, "displayName": mid, "availability": "available",
            "unavailableReason": None}


def _registry():
    registry = HarnessRegistry()
    registry.register(_descriptor("codex", wire={"openai-chat": "chat", "openai-responses": "responses"}))
    registry.register(_descriptor("claude", wire={"anthropic-messages": "anthropic"}))
    return registry


# ------------------------------------------------------------------ G4 derivation

def test_list_derives_compatibility_from_both_sides(tmp_path):
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "Multi", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat", "anthropic-messages"],
        "models": [_model()]})
    row = next(r for r in svc.list() if r["id"] == created["id"])
    # codex speaks openai-chat, claude speaks anthropic-messages; stable-sorted
    # by harness name.
    assert row["compatibility"] == [
        {"harness": "claude", "protocol": "anthropic-messages"},
        {"harness": "codex", "protocol": "openai-chat"}]
    # no DB column holds this - re-deriving after a declaration change proves it.
    changed = HarnessRegistry()
    changed.register(_descriptor("codex", wire={"openai-chat": "chat"}))
    changed.register(_descriptor("claude", wire={}))
    svc.harnesses = changed
    row2 = next(r for r in svc.list() if r["id"] == created["id"])
    assert row2["compatibility"] == [{"harness": "codex", "protocol": "openai-chat"}]


def test_list_undeclared_record_is_unknown_not_incompatible(tmp_path):
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "NoProto", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "models": [_model()]})   # no protocols key
    row = next(r for r in svc.list() if r["id"] == created["id"])
    assert row["protocolsDeclared"] is False
    assert row["protocols"] is None
    assert row["compatibility"] == []        # no "unavailable" verdict is emitted


# ------------------------------------------------------------------ G5 freeze guard

def _freeze(svc, harness, provider_id):
    return svc.freeze_execution_configuration(harness, {"model": {"providerId": provider_id, "modelId": "m1"}})


def test_freeze_rejects_declared_disjoint_protocols(tmp_path):
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "ChatOnly", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat"], "models": [_model()]})
    # claude declares only anthropic-messages -> disjoint -> typed refusal.
    with pytest.raises(ServerError) as exc:
        _freeze(svc, "claude", created["id"])
    assert exc.value.code == "PROTOCOL_INCOMPATIBLE"
    # codex declares openai-chat -> overlap -> passes.
    assert _freeze(svc, "codex", created["id"])["model"] == "m1"


def test_freeze_adding_the_protocol_makes_same_reference_pass(tmp_path):
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "ChatOnly", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat"], "models": [_model()]})
    with pytest.raises(ServerError) as exc:
        _freeze(svc, "claude", created["id"])
    assert exc.value.code == "PROTOCOL_INCOMPATIBLE"
    # counterexample actually runs: widen the record, same reference now freezes.
    svc.update(created["id"], created["version"], "k2", {
        "displayName": "ChatOnly", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat", "anthropic-messages"], "models": [_model()]})
    assert _freeze(svc, "claude", created["id"])["model"] == "m1"


def test_freeze_undeclared_harness_does_not_block(tmp_path):
    # a family that declares no protocols must never be blocked by a declared
    # provider record (unknown is not incompatible).
    registry = HarnessRegistry()
    registry.register(_descriptor("mystery", wire={}))
    svc = _service(tmp_path, registry)
    created = svc.create("k1", {
        "displayName": "ChatOnly", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat"], "models": [_model()]})
    assert _freeze(svc, "mystery", created["id"])["model"] == "m1"


# ------------------------------------------------------------------ 093 wiring input

def test_freeze_passes_through_record_protocol_facts(tmp_path):
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "Wireable", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "protocols": ["openai-chat"],
        "endpoints": {"openai-chat": "http://127.0.0.1:9/v1"}, "models": [_model()]})
    frozen = _freeze(svc, "codex", created["id"])
    # the native materializer (093) needs the record's base URL + protocol on the
    # frozen execution so it writes the record's value, not the template constant.
    assert frozen["protocols"] == ["openai-chat"]
    assert frozen["endpoints"] == {"openai-chat": "http://127.0.0.1:9/v1"}


def test_freeze_without_facts_has_no_new_keys(tmp_path):
    # 093 G6 "no facts => zero regression": an undeclared record freezes exactly
    # the pre-092 key set (no protocols/endpoints keys injected).
    svc = _service(tmp_path, _registry())
    created = svc.create("k1", {
        "displayName": "Plain", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [], "models": [_model()]})
    frozen = _freeze(svc, "codex", created["id"])
    assert "protocols" not in frozen and "endpoints" not in frozen
    assert set(frozen) == {
        "providerModelId", "providerModelVersion", "provider", "model",
        "credentialId", "configuration"}


# ------------------------------------------------------------------ descriptor validation

def test_descriptor_rejects_illegal_wire_protocols():
    with pytest.raises(HarnessDescriptorError):
        HarnessDescriptor("x", wire_protocols={"martian-wire": "z"})        # non-canonical key
    with pytest.raises(HarnessDescriptorError):
        HarnessDescriptor("x", wire_protocols={"openai-chat": ""})           # empty dialect
    # legal declaration normalizes to canonical order and round-trips.
    d = HarnessDescriptor("x", wire_protocols={"anthropic-messages": "anthropic",
                                               "openai-chat": "chat"})
    assert list(d.wire_protocols) == ["openai-chat", "anthropic-messages"]
