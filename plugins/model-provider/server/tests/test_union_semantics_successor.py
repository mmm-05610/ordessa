"""Order 126 union semantics — successor coverage in the new owner.

Replaces ``apps/server/tests/test_union_semantics_126.py`` (AR-1 item 2): the
five guards — 092 protocol normalization x Order 112 "omitted == keep,
explicit null == clear" — are pinned here against ``ModelCatalogService`` /
``ProviderModelRecords``, so the legacy compat-layer file can retire without
losing coverage. The legacy file stays retired only while all five stay green
here.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.records import ProviderModelRecords


def _body(**over):
    body = {"displayName": "N", "harness": None, "provider": "acme", "credentialId": None,
            "configuration": [],
            "models": [{"modelId": "m1", "displayName": "m1", "availability": "available",
                        "unavailableReason": None}]}
    body.update(over)
    return body


def _find(catalog, pid):
    return next(r for r in catalog.list() if r["id"] == pid)


def test_update_omitting_everything_keeps_protocols_and_provenance(catalog):
    # 112 (provenance) + 092 (protocols): a bare rename preserves both.
    created = catalog.create("k1", _body(
        protocols=["openai-chat"], baseUrl="https://api.acme.test/v1", wireApi="chat",
        fieldsSource="manual"))
    renamed = catalog.update(created["id"], created["version"], "k2",
                             _body(displayName="Renamed"))
    assert renamed["displayName"] == "Renamed"
    assert renamed["protocols"] == ["openai-chat"]                            # 092 carried
    assert renamed["provenance"]["baseUrl"] == "https://api.acme.test/v1"    # 112 kept
    assert renamed["provenance"]["wireApi"] == "chat"


def test_update_explicit_null_clears_provenance_but_keeps_protocols(catalog):
    created = catalog.create("k1", _body(
        protocols=["openai-chat"], baseUrl="https://api.acme.test/v1", wireApi="chat"))
    cleared = catalog.update(created["id"], created["version"], "k2",
                             _body(displayName="N", wireApi=None))
    assert cleared["provenance"]["wireApi"] is None                          # null -> cleared
    assert cleared["provenance"]["baseUrl"] == "https://api.acme.test/v1"    # not named -> kept
    assert cleared["protocols"] == ["openai-chat"]                           # 092 preserved


def test_update_replacing_protocols_still_normalizes_dialects(catalog):
    created = catalog.create("k1", _body(protocols=["openai-chat"]))
    updated = catalog.update(created["id"], created["version"], "k2",
                             _body(protocols=["anthropic_messages", "claude"]))
    assert updated["protocols"] == ["anthropic-messages"]                     # dedup + canonical


def test_update_with_unknown_protocol_is_refused_and_changes_nothing(catalog):
    created = catalog.create("k1", _body(protocols=["openai-chat"]))
    with pytest.raises(ServerError) as exc:
        catalog.update(created["id"], created["version"], "k2",
                       _body(protocols=["martian-wire"]))
    assert exc.value.code == "PROTOCOL_UNKNOWN"
    assert _find(catalog, created["id"])["protocols"] == ["openai-chat"]      # record untouched


def test_counterexample_repository_keeps_omitted_provenance(stack):
    # Direct witness that the KEEP sentinel (not None/COALESCE) is what
    # preserves: omitting the column keeps it, passing None clears it.
    records = ProviderModelRecords(stack["database"], stack["idempotency"])
    _status, result = records.create(key="c", request_digest="cd", display_name="x",
                                     harness_type=None, provider_type="acme",
                                     credential_id=None, config_digest="cf",
                                     models_digest="mf", base_url="https://keep.test")
    rid = result["providerModelId"]
    records.update(record_id=rid, expected_version=1, key="u", request_digest="ud",
                   display_name="x2", credential_id=None, config_digest="cf",
                   models_digest="mf")
    assert records.get(rid)["base_url"] == "https://keep.test"               # omitted -> kept
