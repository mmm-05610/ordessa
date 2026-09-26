"""Work Order 126: the 092 x 112 union at the model_configs layer.

QA-014 found that merging the runtime tree (092 protocol normalization) with the
A line (Order 112 "omitted == keep, explicit null == clear") reddened BOTH sides,
because each rewrote `ProviderModelService.update` and `repository.update`. This
file pins the composed method so each guard stays green - and each is red if you
drop it. It exercises the real service + repository (not the wire handler, which
also carries an 112 half on the A line; that wire-side guard is the documented
residual, see the 126 status note).
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.model_configs.repository import ProviderModelRecords
from ordessa_server_compat.model_configs.service import ProviderModelService
from pacthold.storage import Database, ObjectStore


def _service(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    return ProviderModelService(
        ProviderModelRecords(database, IdempotentRecords(database)), ObjectStore(root),
        harnesses={}, credentials=None, profiles=None)


def _body(**over):
    body = {"displayName": "N", "harness": None, "provider": "acme", "credentialId": None,
            "configuration": [],
            "models": [{"modelId": "m1", "displayName": "m1", "availability": "available",
                        "unavailableReason": None}]}
    body.update(over)
    return body


def _find(svc, pid):
    return next(r for r in svc.list() if r["id"] == pid)


def test_update_omitting_everything_keeps_protocols_and_provenance(tmp_path):
    # 112 (provenance) + 092 (protocols): a bare rename preserves both.
    svc = _service(tmp_path)
    created = svc.create("k1", _body(
        protocols=["openai-chat"], baseUrl="https://api.acme.test/v1", wireApi="chat",
        fieldsSource="manual"))
    renamed = svc.update(created["id"], created["version"], "k2",
                         _body(displayName="Renamed"))
    assert renamed["displayName"] == "Renamed"
    assert renamed["protocols"] == ["openai-chat"]          # 092 fact carried
    assert renamed["provenance"]["baseUrl"] == "https://api.acme.test/v1"  # 112 kept
    assert renamed["provenance"]["wireApi"] == "chat"


def test_update_explicit_null_clears_provenance_but_keeps_protocols(tmp_path):
    # The 112 half COALESCE could not express: naming a provenance column null
    # clears it, while an un-named protocol set still survives via 092/project.
    svc = _service(tmp_path)
    created = svc.create("k1", _body(
        protocols=["openai-chat"], baseUrl="https://api.acme.test/v1", wireApi="chat"))
    cleared = svc.update(created["id"], created["version"], "k2", _body(
        displayName="N", wireApi=None))
    assert cleared["provenance"]["wireApi"] is None        # explicit null -> cleared
    assert cleared["provenance"]["baseUrl"] == "https://api.acme.test/v1"  # not named -> kept
    assert cleared["protocols"] == ["openai-chat"]         # 092 preserved


def test_update_replacing_protocols_still_normalizes_dialects(tmp_path):
    # 092 half: a new protocol value is normalized+validated on update, not just create.
    svc = _service(tmp_path)
    created = svc.create("k1", _body(protocols=["openai-chat"]))
    updated = svc.update(created["id"], created["version"], "k2",
                         _body(protocols=["anthropic_messages", "claude"]))
    assert updated["protocols"] == ["anthropic-messages"]  # deduped + canonical


def test_update_with_unknown_protocol_is_refused_and_changes_nothing(tmp_path):
    svc = _service(tmp_path)
    created = svc.create("k1", _body(protocols=["openai-chat"]))
    with pytest.raises(ServerError) as exc:
        svc.update(created["id"], created["version"], "k2",
                   _body(protocols=["martian-wire"]))
    assert exc.value.code == "PROTOCOL_UNKNOWN"
    assert _find(svc, created["id"])["protocols"] == ["openai-chat"]  # record untouched


def test_counterexample_repository_keeps_omitted_provenance(tmp_path):
    # Direct witness that KEEP (not None) is what preserves: omitting the arg at
    # the repository keeps the column, passing None clears it (COALESCE could not
    # do both). If the sentinel regressed to None/COALESCE, this would fail.
    root = tmp_path / "direct"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    idem = IdempotentRecords(database)
    records = ProviderModelRecords(database, idem)
    _s, res = records.create(key="c", request_digest="cd", display_name="x", harness_type=None,
                             provider_type="acme", credential_id=None, config_digest="cf",
                             models_digest="mf", base_url="https://keep.test")
    rid = res["providerModelId"]
    records.update(record_id=rid, expected_version=1, key="u", request_digest="ud",
                   display_name="x2", credential_id=None, config_digest="cf", models_digest="mf")
    assert records.get(rid)["base_url"] == "https://keep.test"        # omitted -> KEEP -> kept
