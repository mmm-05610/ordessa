"""Work Order 092 stage 3: canonical protocol vocabulary + model facts.

Two things must be true and this file pins both, at the service boundary (the
``server/wire/**`` param table that *exposes* these to clients is A-line and its
acceptance rides the relock chain - same split as stage 2):

* the four-value canonical vocabulary: real dialects collapse to it, an unknown
  string is a typed ``PROTOCOL_UNKNOWN`` and the record is not created;
* model facts round-trip verbatim and an *unverified* fact stays absent (a
  missing ``capabilities`` must not come back as ``{}`` or as all-false), while a
  wrong shape is a typed ``PROVIDER_MODEL_INVALID``.

The pure module is also exercised directly so the dialect table and strict
validators are pinned independently of persistence.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.model_configs import provider_protocols as pv
from ordessa_server_compat.model_configs.repository import ProviderModelRecords
from ordessa_server_compat.model_configs.service import ProviderModelService
from pacthold_runtime_compat.storage import Database, ObjectStore


# ---------------------------------------------------------------- module: vocabulary

def test_module_dialect_normalization_is_deduped_and_canonically_ordered():
    # "openai-completions"/"chat"/"chat_completions" all land on openai-chat;
    # anthropic_messages + claude dedupe to one; order is the canonical table.
    out = pv.normalize_protocols(
        ["anthropic_messages", "claude", "chat", "openai-chat", "responses"])
    assert out == ["openai-chat", "openai-responses", "anthropic-messages"]


def test_module_gemini_dialect():
    assert pv.normalize_protocol("generateContent") == "gemini-generate"
    assert pv.normalize_protocol("GEMINI") == "gemini-generate"


def test_module_unknown_string_is_typed_rejection_naming_it():
    with pytest.raises(ServerError) as exc:
        pv.normalize_protocols(["openai-chat", "martian-wire"])
    assert exc.value.code == "PROTOCOL_UNKNOWN"
    assert "martian-wire" in str(exc.value.message)


# ---------------------------------------------------------------- module: capabilities

def test_module_capabilities_wrong_type_and_unknown_key_rejected():
    with pytest.raises(ServerError) as exc:
        pv.validate_capabilities({"toolCall": "yes"})
    assert exc.value.code == "PROVIDER_MODEL_INVALID"
    with pytest.raises(ServerError) as exc:
        pv.validate_capabilities({"unknownField": 1})
    assert exc.value.code == "PROVIDER_MODEL_INVALID"
    # bool is not an int for limits
    with pytest.raises(ServerError):
        pv.validate_capabilities({"limits": {"context": True}})


def test_module_capabilities_absent_stays_absent():
    assert pv.validate_capabilities(None) is None


# ---------------------------------------------------------------- module: endpoints

def test_module_endpoint_key_must_be_a_declared_protocol():
    with pytest.raises(ServerError) as exc:
        pv.validate_endpoints({"anthropic-messages": "https://x.invalid/v1"}, ["openai-chat"])
    assert exc.value.code == "PROFILE_CONFIGURATION_INVALID"


def test_module_endpoint_reuses_probe_url_discipline():
    # plain http to a non-loopback host is refused exactly as the probe would.
    with pytest.raises(ServerError) as exc:
        pv.validate_endpoints({"openai-chat": "http://api.deepseek.com/v1"}, ["openai-chat"])
    assert exc.value.code == "PROFILE_CONFIGURATION_INVALID"
    # loopback http is allowed and normalized to the base form.
    ok = pv.validate_endpoints({"openai-chat": "http://127.0.0.1:9/v1/"}, ["openai-chat"])
    assert ok == {"openai-chat": "http://127.0.0.1:9/v1"}


# ---------------------------------------------------------------- service round-trip

def _service(tmp_path, harnesses=None):
    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    records = ProviderModelRecords(database, IdempotentRecords(database))
    objects = ObjectStore(root)
    svc = ProviderModelService(records, objects, harnesses=harnesses or {},
                               credentials=None, profiles=None)
    return svc


def _body(**over):
    body = {
        "displayName": "DeepSeek shared", "harness": None, "provider": "deepseek",
        "credentialId": None, "configuration": [],
        "models": [{"modelId": "m1", "displayName": "M1",
                    "availability": "available", "unavailableReason": None}],
    }
    body.update(over)
    return body


def test_service_stores_and_reads_back_normalized_protocols_and_facts(tmp_path):
    svc = _service(tmp_path)
    created = svc.create("k1", _body(
        protocols=["anthropic_messages", "claude", "chat"],
        models=[{"modelId": "m1", "displayName": "M1", "availability": "available",
                 "unavailableReason": None, "protocols": ["openai-completions"],
                 "capabilities": {"toolCall": True, "reasoning": True,
                                  "limits": {"context": 1_000_000, "output": 131_072}}}]))
    got = next(r for r in svc.list() if r["id"] == created["id"])
    assert got["protocols"] == ["openai-chat", "anthropic-messages"]   # deduped+canonical
    assert got["protocolsDeclared"] is True
    model = got["models"][0]
    assert model["protocols"] == ["openai-chat"]
    assert model["capabilities"]["limits"] == {"context": 1_000_000, "output": 131_072}
    assert model["capabilities"]["toolCall"] is True


def test_service_absent_capabilities_stay_absent(tmp_path):
    svc = _service(tmp_path)
    created = svc.create("k1", _body(
        protocols=["openai-chat"],
        models=[{"modelId": "m1", "displayName": "M1", "availability": "available",
                 "unavailableReason": None}]))
    got = next(r for r in svc.list() if r["id"] == created["id"])
    model = got["models"][0]
    # the counter-example to "fill in defaults": neither key may appear.
    assert "capabilities" not in model
    assert "protocols" not in model
    assert got["endpoints"] is None


def test_service_unknown_protocol_does_not_persist_the_record(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(ServerError) as exc:
        svc.create("k1", _body(protocols=["openai-chat", "martian-wire"]))
    assert exc.value.code == "PROTOCOL_UNKNOWN"
    # G2 "record not created": nothing landed in the list.
    assert svc.list() == []


def test_service_bad_capability_shape_is_typed_and_blocks_creation(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(ServerError) as exc:
        svc.create("k1", _body(models=[{"modelId": "m1", "displayName": "M1",
                                        "availability": "available", "unavailableReason": None,
                                        "capabilities": {"toolCall": "yes"}}]))
    assert exc.value.code == "PROVIDER_MODEL_INVALID"
    assert svc.list() == []


def test_service_update_without_protocols_preserves_them(tmp_path):
    svc = _service(tmp_path)
    created = svc.create("k1", _body(protocols=["openai-chat"]))
    updated = svc.update(created["id"], created["version"], "k2", _body(
        displayName="Renamed"))     # no protocols key in the update body
    assert updated["protocols"] == ["openai-chat"]
    assert updated["displayName"] == "Renamed"
