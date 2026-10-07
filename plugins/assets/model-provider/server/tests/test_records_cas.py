# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_records_cas.py, verbatim)
"""G8: CAS versions, idempotent replays, KEEP provenance semantics, soft delete.

The counterexamples are the classic storage regressions: a stale
``expectedVersion`` overwriting a newer row, a retried request creating a
second record, an un-named provenance field being cleared, and an archive
physically deleting a row the history still points at.
"""
from __future__ import annotations

import pytest
from ordessa_server.errors import ServerError

from ordessa_model_provider.records import ProviderModelRecords


def _records(stack):
    return ProviderModelRecords(stack["database"], stack["idempotency"])


def _create(records, key="k1"):
    return records.create(
        key=key, request_digest=key, display_name="N", harness_type="pi",
        provider_type="acme", credential_id=None,
        config_digest="cfg-1", models_digest="mdl-1", base_url="https://api.acme.test/v1",
    )


def test_stale_version_conflicts_and_carries_current(tmp_path, stack):
    records = _records(stack)
    _status, body = _create(records)
    records.update(record_id=body["providerModelId"], expected_version=1, key="u1",
                   request_digest="u1", display_name="N2", credential_id=None,
                   config_digest="cfg-2", models_digest="mdl-2")
    with pytest.raises(ServerError) as excinfo:
        records.update(record_id=body["providerModelId"], expected_version=1, key="u2",
                       request_digest="u2", display_name="N3", credential_id=None,
                       config_digest="cfg-3", models_digest="mdl-3")
    assert excinfo.value.code == "RECORD_VERSION_CONFLICT"
    assert excinfo.value.status == 409
    assert int(excinfo.value.current["version"]) == 2  # the current truth rides along


def test_matching_version_bumps_version(stack):
    records = _records(stack)
    _status, body = _create(records)
    _status, _body = records.update(record_id=body["providerModelId"], expected_version=1,
                                    key="u1", request_digest="u1", display_name="N2",
                                    credential_id=None, config_digest="cfg-2", models_digest="mdl-2")
    row = records.get(body["providerModelId"])
    assert int(row["version"]) == 2


def test_retried_create_replays_the_same_record(stack):
    records = _records(stack)
    first = _create(records, key="same-key")
    second = _create(records, key="same-key")
    assert first[1]["providerModelId"] == second[1]["providerModelId"]


def test_unnamed_provenance_keeps_named_null_clears(stack):
    records = _records(stack)
    _status, body = _create(records)
    rid = body["providerModelId"]
    # not named -> keeps
    records.update(record_id=rid, expected_version=1, key="u1", request_digest="u1",
                   display_name="N", credential_id=None, config_digest="c", models_digest="m")
    assert records.get(rid)["base_url"] == "https://api.acme.test/v1"
    # named null -> clears
    records.update(record_id=rid, expected_version=2, key="u2", request_digest="u2",
                   display_name="N", credential_id=None, config_digest="c", models_digest="m",
                   base_url=None)
    assert records.get(rid)["base_url"] is None


def test_archive_is_a_soft_delete_and_idempotent(stack):
    records = _records(stack)
    _status, body = _create(records)
    rid = body["providerModelId"]
    records.archive(record_id=rid, expected_version=1, key="a1", request_digest="a1")
    row = records.get(rid)
    assert row["archived_at"] is not None
    assert int(row["version"]) == 2
    # re-archive: COALESCE keeps the first fact, still one version bump shape
    records.archive(record_id=rid, expected_version=2, key="a2", request_digest="a2")
    assert records.get(rid)["archived_at"] == row["archived_at"]


def test_list_excludes_archived_by_default(stack):
    records = _records(stack)
    _status, body = _create(records)
    records.archive(record_id=body["providerModelId"], expected_version=1,
                    key="a1", request_digest="a1")
    assert records.list() == []
    assert len(records.list(include_archived=True)) == 1


def test_missing_record_is_a_typed_404(stack):
    records = _records(stack)
    with pytest.raises(ServerError) as excinfo:
        records.get("provider-nope")
    assert excinfo.value.code == "PROVIDER_MODEL_NOT_FOUND"
    assert excinfo.value.status == 404
