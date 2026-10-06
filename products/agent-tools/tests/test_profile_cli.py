"""Client wire contract tests over real HTTP, not product Server acceptance."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import pytest

from ordessa_agent_tools.cli import main
from ordessa_agent_tools.client import core_schema
from test_discovery import SECRET, config

REF = {"environmentNamespace": "fixture-env", "profileId": "reviewer", "manifestRevision": 1, "contentDigest": "sha256:" + "a" * 64}
ENTRY = {"profileId": "reviewer", "catalogRevision": 1, "displayName": "Reviewer", "archivedAt": None, "currentManifestRef": REF}
MANIFEST = {"schemaVersion": "1", "harnessDefinitionRef": {"environmentNamespace": "fixture-env", "id": "fixture-harness"}, "declarations": []}


@contextmanager
def profile_server(mode="healthy", version="agent-assembly/1"):
    calls = []
    contract = core_schema(version)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request)
            method = request["method"]
            result = ENTRY
            if method == "server.hello":
                result = {"serverId": "fixture", "protocolVersion": "wire/1", "auth": {"required": True, "schemes": ["session_token"]},
                          "capabilities": [{"id": "agents.capabilities", "supported": True}]}
            elif method == "agents.capabilities":
                result = {"contractVersion": contract["schema"]["contractVersion"], "schemaDigest": contract["schemaDigest"],
                          "schema": contract["schema"], "environmentNamespace": "fixture-env",
                          "supports": {"profileCatalog": mode != "missing", "nodes": False, "managedInput": False}}
                if version == "agent-assembly/3":
                    result["supports"].update(configurationManagement=False, nodePreparation=False,
                                              nodeLifecycle=False)
                    result["supportedMethods"] = [name for name in contract["schema"]["methods"] if name.startswith("agents.profiles.") or name == "agents.capabilities"]
                if mode == "digest":
                    result["schemaDigest"] = "sha256:" + "0" * 64
            elif method == "agents.profiles.list":
                result = {"entries": [ENTRY]}
            elif method == "agents.profiles.clone":
                # A valid clone result belongs to the requested new identity.
                result = {**ENTRY, "profileId": request["params"]["profileId"],
                          "displayName": request["params"]["displayName"],
                          "currentManifestRef": {**REF, "profileId": request["params"]["profileId"]}}
            elif method == "agents.profiles.read":
                result = {"ref": REF, "content": MANIFEST}
            elif method == "agents.profiles.preview":
                result = {"profileRef": REF, "status": "unresolved", "referenceCoverage": "unknown", "ready": False,
                          "error": {"code": "providerUnavailable", "retryable": False}}
            if method.startswith("agents.profiles.") and mode == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if method.startswith("agents.profiles.") and mode == "empty":
                result = {}
            body = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            if method.startswith("agents.profiles.") and mode in {"conflict", "forbidden"}:
                body = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": "FORBIDDEN" if mode == "forbidden" else "CONFLICT_VERSION", "message": SECRET}}
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(httpd.server_port), calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def invoke(tmp_path, monkeypatch, capsys, command, mode="healthy"):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    with profile_server(mode) as (endpoint, calls):
        path = config(tmp_path, endpoint)
        code = main(command + ["--config", str(path), "--service", "local", "--json"])
        output = capsys.readouterr()
        assert SECRET not in output.out + output.err
        return code, json.loads(output.out), calls


@pytest.mark.parametrize("command", ["doctor", "capabilities"])
def test_core_profile_support_is_distinct_from_nodes(tmp_path, monkeypatch, capsys, command):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, [command])
    assert code == 0
    assert result["data"]["coreAgent"]["supports"] == {"profileCatalog": True, "nodes": False, "managedInput": False}
    assert [item["method"] for item in calls] == ["server.hello", "agents.capabilities"]


@pytest.mark.parametrize("command,method", [
    (["list", "--include-archived"], "list"), (["show", json.dumps(REF)], "read"),
    (["entry", "reviewer"], "readEntry"),
    (["clone", json.dumps(REF), "--profile-id", "copy", "--name", "Copy", "--request-id", "clone-1"], "clone"),
    (["rename", "reviewer", "--name", "New", "--expected-catalog-revision", "1", "--request-id", "rename-1"], "rename"),
    (["archive", "reviewer", "--expected-catalog-revision", "1", "--request-id", "archive-1"], "archive"),
    (["restore", "reviewer", "--expected-catalog-revision", "1", "--request-id", "restore-1"], "restore"),
])
def test_profile_methods_use_published_schema(tmp_path, monkeypatch, capsys, command, method):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, ["profiles"] + command)
    assert code == 0 and result["status"] == "confirmed"
    last = calls[-1]
    assert last["method"] == "agents.profiles." + method
    schema = core_schema()["schema"]["methods"][last["method"]]
    assert set(schema["required"]) <= last["params"].keys()
    assert set(last["params"]) <= set(schema["required"] + schema["optional"])
    if "requestId" in last["params"]:
        assert result["requestId"] == last["params"]["requestId"]


@pytest.mark.parametrize("action", ["create", "edit"])
def test_manifest_files_and_full_base_ref(tmp_path, monkeypatch, capsys, action):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST))
    ref = tmp_path / "reference.json"
    ref.write_text(json.dumps(REF))
    command = ["profiles", action]
    command += ["--profile-id", "reviewer", "--name", "Reviewer"] if action == "create" else ["reviewer", "--expected-catalog-revision", "1", "--base-manifest", "@" + str(ref)]
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, command + ["--file", str(manifest), "--request-id", "stable-1"])
    assert code == 0
    assert calls[-1]["params"]["manifest"] == MANIFEST
    assert result["requestId"] == "stable-1"
    if action == "edit":
        assert calls[-1]["params"]["baseManifestRef"] == REF


@pytest.mark.parametrize("mode,expected", [("conflict", 5), ("forbidden", 3), ("disconnect", 6), ("empty", 6)])
def test_profile_mutation_never_retries(tmp_path, monkeypatch, capsys, mode, expected):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys,
        ["profiles", "archive", "reviewer", "--expected-catalog-revision", "1", "--request-id", "stable-1"], mode)
    assert code == expected
    assert len(calls) == 3
    assert result["requestId"] == "stable-1"
    if mode in {"disconnect", "empty"}:
        assert result["status"] == "unknown"


@pytest.mark.parametrize("mode", ["digest", "missing"])
def test_core_failure_prevents_mutation(tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys,
        ["profiles", "archive", "reviewer", "--expected-catalog-revision", "1", "--request-id", "stable-1"], mode)
    assert code == 4 and len(calls) == 2


def test_preview_is_unresolved_refusal(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, ["profiles", "preview", json.dumps(REF)])
    assert code == 4
    assert result["data"]["ready"] is False and result["data"]["referenceCoverage"] == "unknown"


def test_incomplete_ref_is_invalid_before_network(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, ["profiles", "show", '{"profileId":"reviewer"}'])
    assert code == 2 and not calls


def test_invalid_read_result_is_not_confirmed(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, ["profiles", "show", json.dumps(REF)], "empty")
    assert code == 4 and result["status"] == "refused" and len(calls) == 3


@pytest.mark.parametrize('field,value', [('manifestRevision',True),('manifestRevision',0),('contentDigest','bad'),('environmentNamespace','wrong env')])
def test_malformed_complete_reference_refused_before_http(tmp_path, monkeypatch, capsys, field, value):
    malformed = dict(REF)
    malformed[field] = value
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, ['profiles','show',json.dumps(malformed)])
    assert code == 2 and result['status'] == 'refused'
    assert calls == []


def test_profile_response_reference_scope_and_catalog_identity():
    from ordessa_agent_tools.cli import profile_result
    bad = {**ENTRY, 'currentManifestRef': {**REF, 'environmentNamespace':'other'}}
    assert not profile_result('entry', bad, 'fixture-env')
    bad = {**ENTRY, 'currentManifestRef': {**REF, 'profileId':'other'}}
    assert not profile_result('entry', bad, 'fixture-env')
    bad = {**ENTRY, 'currentManifestRef': {**REF, 'manifestRevision':True}}
    assert not profile_result('entry', bad, 'fixture-env')


@pytest.mark.parametrize('raw', [b'{"value":1e999}', b'{"value":"\\ud800"}'])
def test_invalid_finite_utf8_input_rejected(raw):
    from ordessa_agent_tools.client import parse_json
    with pytest.raises(ValueError):
        parse_json(raw)


def test_profile_cli_remains_available_on_exact_management_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    with profile_server(version="agent-assembly/3") as (endpoint, calls):
        code = main(["profiles", "list", "--config", str(config(tmp_path, endpoint)), "--service", "local", "--json"])
        output = capsys.readouterr()
        assert code == 0 and json.loads(output.out)["data"] == {"entries": [ENTRY]}
        assert SECRET not in output.out + output.err
        assert [call["method"] for call in calls] == ["server.hello", "agents.capabilities", "agents.profiles.list"]
