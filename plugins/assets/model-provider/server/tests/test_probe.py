# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_probe.py, verbatim)
"""G6 (backend half): the bounded one-shot probe.

Every test drives the transport through ``_open_request`` substitution - the
legacy test seam - so no test ever leaves the machine. The counterexamples are
the boundaries themselves: a redirect, a private address, a slow drip, a
non-loopback plain http all refuse type-wise, and nothing a probe learned is
ever written into a record.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from ordessa_model_provider import probe as probe_module
from ordessa_model_provider.probe import (
    ProbeError, MAX_MODEL_ENTRIES, _validate_endpoint, _parse_models_payload,
    probe_connection, pull_models,
)


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size=-1):
        return self._payload.read(size) if isinstance(self._payload, io.BytesIO) else self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_transport(monkeypatch, responder):
    monkeypatch.setattr(probe_module, "_open_request", responder)


def _ok_transport(payload: bytes, capture=None):
    def responder(request, timeout):
        if capture is not None:
            capture.append(request)
        return _FakeResponse(io.BytesIO(payload))
    return responder


def test_plain_http_refused_off_loopback():
    with pytest.raises(ProbeError) as excinfo:
        _validate_endpoint("http://10.0.0.5:8000/v1")
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_loopback_http_allowed_and_https_allowed():
    base, _host = _validate_endpoint("http://127.0.0.1:8080/v1")
    assert base == "http://127.0.0.1:8080/v1"
    base, _host = _validate_endpoint("https://127.0.0.1:9443/v1")
    assert base == "https://127.0.0.1:9443/v1"


def test_name_resolving_to_private_address_refused(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, None, None, "", ("10.0.0.9", 0))])
    with pytest.raises(ProbeError) as excinfo:
        _validate_endpoint("https://internal.acme.test/v1")
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_redirect_is_never_followed(monkeypatch):
    def responder(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 302, "moved", {}, io.BytesIO())
    _install_transport(monkeypatch, responder)
    with pytest.raises(ProbeError) as excinfo:
        pull_models("https://127.0.0.1/v1", None)
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_auth_failure_is_typed(monkeypatch):
    def responder(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO())
    _install_transport(monkeypatch, responder)
    with pytest.raises(ProbeError) as excinfo:
        pull_models("https://127.0.0.1/v1", "k")
    assert excinfo.value.code == "PROBE_AUTH_FAILED"


def test_unreachable_is_typed(monkeypatch):
    def responder(request, timeout):
        raise urllib.error.URLError(OSError("no route"))
    _install_transport(monkeypatch, responder)
    with pytest.raises(ProbeError) as excinfo:
        pull_models("https://127.0.0.1/v1", None)
    assert excinfo.value.code == "PROBE_UNREACHABLE"


def test_reachable_but_unauthorized_still_answers(monkeypatch):
    def responder(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO())
    _install_transport(monkeypatch, responder)
    result = probe_connection("https://127.0.0.1/v1", "k")
    assert result.status == "reachable"


def test_model_entries_parsed_and_capped(monkeypatch):
    entries = [{"id": f"m{i}"} for i in range(MAX_MODEL_ENTRIES + 50)]
    payload = json.dumps({"data": entries}).encode()
    _install_transport(monkeypatch, _ok_transport(payload))
    result = pull_models("https://127.0.0.1/v1", None)
    assert len(result.models) == MAX_MODEL_ENTRIES


def test_non_json_payload_refused(monkeypatch):
    _install_transport(monkeypatch, _ok_transport(b"<html>not json</html>"))
    with pytest.raises(ProbeError) as excinfo:
        pull_models("https://127.0.0.1/v1", None)
    assert excinfo.value.code == "PROBE_FORMAT_INVALID"


def test_parse_requires_data_list():
    with pytest.raises(ProbeError) as excinfo:
        _parse_models_payload(json.dumps({"models": ["x"]}).encode())
    assert excinfo.value.code == "PROBE_FORMAT_INVALID"


def test_probe_never_writes_into_a_record(stack, catalog, monkeypatch):
    """A probe is read-only reconnaissance: the record's stored model list is
    the user's saved fact, not the endpoint's current answer."""
    created = catalog.create("k1", {
        "displayName": "N", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [],
        "models": [{"modelId": "m1", "displayName": "m1",
                    "availability": "available", "unavailableReason": None}],
    })
    before = catalog.project(catalog.records.get(created["id"]))
    payload = json.dumps({"data": [{"id": "totally-new-model"}]}).encode()
    _install_transport(monkeypatch, _ok_transport(payload))
    result = catalog.probe_models({"baseUrl": "https://127.0.0.1/v1", "credentialId": None})
    assert result["status"] == "ok" and result["models"] == ["totally-new-model"]
    after = catalog.project(catalog.records.get(created["id"]))
    assert after["models"] == before["models"]
    assert after["version"] == before["version"]
