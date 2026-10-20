"""HTTP-route closure for Order 098 using the current Server product assembly."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from ordessa_model_provider.plugin import PLUGIN_ID
from ordessa_model_provider.testing import wire_body
from ordessa_interfaces.http import create_app
from ordessa_server.composition.runtime import build_runtime

PROVENANCE = {
    "baseUrl": "https://api.deepseek.com",
    "authStyle": "api_key",
    "wireApi": "chat_completions",
    "fieldsSource": "manual",
}


@pytest.fixture
def http_rig(tmp_path):
    runtime = build_runtime(tmp_path / "server-data")
    app = create_app(runtime)
    with TestClient(app, base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        assert runtime.started
        assert runtime.plugin_host.provided_port("model_provider.catalog") is not None
        assert runtime.plugin_host.active(PLUGIN_ID) is not None
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}


def _post(client, headers, method, params, *, request_id=None):
    request_id = request_id or params.get("requestId", method)
    return client.post(
        f"/wire/v1/{method}",
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id,
              "method": method, "params": params},
    )


def _envelope(response, request_id):
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == request_id
    return body


def _create(client, headers, request_id, *, provenance=...):
    params = {"requestId": request_id, **wire_body()}
    if provenance is not ...:
        params["provenance"] = provenance
    body = _envelope(_post(client, headers, "providerModels.create", params), request_id)
    assert "result" in body, body
    return body["result"]["providerModel"]


def _update_params(record, request_id, **changes):
    params = {
        "requestId": request_id,
        "providerModelId": record["id"],
        "expectedVersion": record["version"],
        "displayName": record["displayName"],
        "credentialId": record["credentialId"],
        "configuration": record["configuration"],
        "models": record["models"],
    }
    params.update(changes)
    return params


def _read(client, headers, record_id, request_id):
    body = _envelope(_post(
        client, headers, "providerModels.list", {"includeArchived": False},
        request_id=request_id,
    ), request_id)
    assert "result" in body, body
    return next(row for row in body["result"]["items"] if row["id"] == record_id)


def test_http_create_list_and_update_preserve_provenance_omission_and_named_null(http_rig):
    _runtime, client, headers = http_rig
    saved = _create(client, headers, "http-prov-create", provenance=PROVENANCE)
    assert saved["provenance"] == PROVENANCE
    assert _read(client, headers, saved["id"], "http-prov-list-create")["provenance"] == PROVENANCE

    omitted = _update_params(saved, "http-prov-omitted")
    body = _envelope(_post(client, headers, "providerModels.update", omitted), "http-prov-omitted")
    assert body["result"]["providerModel"]["provenance"] == PROVENANCE
    after_omission = body["result"]["providerModel"]

    cleared = _update_params(
        after_omission, "http-prov-named-null",
        provenance={"baseUrl": None, "authStyle": "oauth"},
    )
    body = _envelope(_post(client, headers, "providerModels.update", cleared), "http-prov-named-null")
    expected = dict(PROVENANCE, baseUrl=None, authStyle="oauth")
    assert body["result"]["providerModel"]["provenance"] == expected
    assert _read(client, headers, saved["id"], "http-prov-list-updated")["provenance"] == expected


def test_http_invalid_provenance_and_required_null_refuse_without_mutation(http_rig):
    _runtime, client, headers = http_rig
    saved = _create(client, headers, "http-prov-refusal-create", provenance=PROVENANCE)

    invalid = _update_params(
        saved, "http-prov-invalid-enum", provenance={"authStyle": "telepathy"},
    )
    body = _envelope(_post(client, headers, "providerModels.update", invalid), "http-prov-invalid-enum")
    assert body["error"]["code"] == "INVALID_REQUEST"

    null_required = _update_params(saved, "http-prov-null-name", displayName=None)
    body = _envelope(_post(client, headers, "providerModels.update", null_required), "http-prov-null-name")
    assert body["error"]["code"] == "INVALID_REQUEST"

    unchanged = _read(client, headers, saved["id"], "http-prov-list-after-refusal")
    assert unchanged["version"] == saved["version"]
    assert unchanged["provenance"] == PROVENANCE


def test_http_scope_failure_is_typed_jsonrpc_and_restores_the_real_handler(
        http_rig, monkeypatch):
    from ordessa_model_provider import plugin as plugin_module
    _runtime, client, headers = http_rig
    original = plugin_module._Handlers._provenance

    def broken(params):
        raw = params.get("provenance")
        if raw is None:
            return None
        if not set(raw) <= set(_UNBOUND_PROVENANCE_FIELDS):  # noqa: F821
            raise plugin_module.WireError("INVALID_REQUEST", "provenance carries unknown fields")
        return dict(raw)

    monkeypatch.setattr(plugin_module._Handlers, "_provenance", staticmethod(broken))
    body = _envelope(_post(client, headers, "providerModels.create", {
        "requestId": "http-prov-scope-error", **wire_body(), "provenance": PROVENANCE,
    }), "http-prov-scope-error")
    assert body["error"]["code"] == "UNAVAILABLE"
    assert body["error"]["details"]["internalCode"] == "NameError"

    monkeypatch.setattr(plugin_module._Handlers, "_provenance", staticmethod(original))
    restored = _create(client, headers, "http-prov-scope-restored", provenance=PROVENANCE)
    assert restored["provenance"] == PROVENANCE


def test_http_probe_uses_controlled_loopback_without_forwarding_credentials(http_rig):
    _runtime, client, headers = http_rig
    seen = []

    class ControlledReject(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(403)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledReject)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request_id = "http-prov-controlled-probe"
        body = _envelope(_post(client, headers, "providerModels.probeModels", {
            "requestId": request_id,
            "baseUrl": f"http://127.0.0.1:{port}/v1",
            "provenance": {"authStyle": "api_key", "fieldsSource": "manual"},
        }), request_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["result"] == {"status": "failed", "code": "PROBE_AUTH_FAILED", "models": []}
    assert seen == [("/v1/models", None)]
