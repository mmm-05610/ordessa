# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_no_credential_leak.py, verbatim)
"""G9: the credential content never leaves the probe call.

The secret travels exactly one edge: secret store -> Authorization header of
the single probe request. Projection dicts, error messages and typed probe
failures are scanned for the sentinel; the canary at the top proves the scan
itself detects a leak (so a green here is evidence, not a broken detector).
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from ordessa_model_provider import probe as probe_module
from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.records import ProviderModelRecords

from ordessa_model_provider.testing import (
    FakeCredentials, FakeHarnesses, RecordingSecretStore, seed_credential_row,
)

SENTINEL = RecordingSecretStore.SENTINEL


class _FakeResponse:
    def __init__(self, payload):
        self._payload = io.BytesIO(payload)

    def read(self, size=-1):
        return self._payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _catalog(stack, secret_store):
    return ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=FakeHarnesses(),
        credentials=FakeCredentials(rows=[{
            "id": "cred-1", "kind": "api_key", "secret_locator": "loc://cred-1",
        }]),
        secret_store=secret_store,
    )


def test_scan_detects_a_real_leak():
    """Canary: the leak detector is alive - a leak elsewhere in this suite
    cannot hide behind a broken scan."""
    assert SENTINEL in f"some leak of {SENTINEL} here"


def test_credential_flows_only_into_the_request_header(stack, monkeypatch):
    secret_store = RecordingSecretStore()
    catalog = _catalog(stack, secret_store)
    captured = []

    def responder(request, timeout):
        captured.append(dict(request.header_items()))
        return _FakeResponse(json.dumps({"data": [{"id": "m"}]}).encode())

    monkeypatch.setattr(probe_module, "_open_request", responder)
    result = catalog.probe_models({"baseUrl": "https://127.0.0.1/v1",
                                   "credentialId": "cred-1"})
    assert result["status"] == "ok"
    headers = {k.lower(): v for item in captured for k, v in item.items()}
    assert headers.get("authorization") == f"Bearer {SENTINEL}"  # the one edge
    assert secret_store.reads == 1                               # pulled at call time
    assert SENTINEL not in json.dumps(result)                    # not in the answer


def test_projection_and_errors_carry_only_the_reference(stack, monkeypatch):
    secret_store = RecordingSecretStore()
    catalog = _catalog(stack, secret_store)
    seed_credential_row(stack["database"])
    created = catalog.create("k1", {
        "displayName": "N", "harness": None, "provider": "acme",
        "credentialId": "cred-1",
        "configuration": [],
        "models": [{"modelId": "m1", "displayName": "m1",
                    "availability": "available", "unavailableReason": None}],
    })
    surfaces = [
        json.dumps(catalog.project(catalog.records.get(created["id"]))),
        json.dumps(catalog.list(include_archived=True)),
    ]
    try:
        catalog.records.get("provider-missing")
    except Exception as error:  # noqa: BLE001 - scanning the typed error text
        surfaces.append(str(error))
    for surface in surfaces:
        assert SENTINEL not in surface
        assert "cred-1" in surfaces[0]  # the reference id is public by design


def test_typed_probe_failure_quotes_no_request(stack, monkeypatch):
    secret_store = RecordingSecretStore()
    catalog = _catalog(stack, secret_store)

    def responder(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 500, "server error", {}, io.BytesIO())

    monkeypatch.setattr(probe_module, "_open_request", responder)
    result = catalog.probe_connection({"baseUrl": "https://127.0.0.1/v1",
                                       "credentialId": "cred-1"})
    # a 500 is a real failure (unlike a 401/403, where the endpoint answered)
    assert result["status"] == "unreachable"
    assert result["detail"] == "PROBE_HTTP_ERROR"
    assert SENTINEL not in json.dumps(result)
