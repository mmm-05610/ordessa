"""Real temporary HTTP fixture; not an Ordessa Server product acceptance test."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import pytest

from ordessa_agent_tools.cli import main
from ordessa_agent_tools.client import ClientError, Service, WireClient, load_service

SECRET = "fixture-private-bearer-do-not-print"


@contextlib.contextmanager
def server(mode="healthy"):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("Authorization"), request))
            if mode == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if mode == "timeout":
                time.sleep(0.2)
            if mode == "401":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(SECRET.encode())
                return
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "/leaked/" + SECRET)
                self.end_headers()
                return
            hello = {"serverId": "fixture-server", "protocolVersion": "wire/2" if mode == "version" else "wire/1",
                     "auth": {"required": True, "schemes": ["session_token"]},
                     "capabilities": [{"id": "server.hello", "supported": True},
                                      {"id": "agent.submitInput", "supported": False, "reason": SECRET}]}
            body = {"jsonrpc": "2.0", "id": request["id"], "result": hello}
            if mode == "mismatched":
                body["id"] = "different"
            if mode == "overlap":
                body["error"] = {"code": "UNAVAILABLE", "message": SECRET}
            if mode == "wire403":
                body = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": "FORBIDDEN", "message": SECRET}}
            if mode == "badcap":
                hello["capabilities"][0]["supported"] = "true"
            raw = SECRET.encode() if mode == "badjson" else json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(httpd.server_port), calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def config(tmp_path, endpoint):
    path = tmp_path / "services.json"
    path.write_text(json.dumps({"services": {"local": {"endpoint": endpoint, "tokenEnv": "TOOLS_TEST_TOKEN"}}}))
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("command", ["doctor", "capabilities"])
def test_actual_http_discovery_reports_core_gap(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    with server() as (endpoint, calls):
        path = config(tmp_path, endpoint)
        assert main([command, "--config", str(path), "--service", "local", "--json"]) == 4
        output = capsys.readouterr()
        body = json.loads(output.out)
        assert body["data"]["discovery"]["status"] == "confirmed"
        assert body["error"]["code"] == "CORE_API_UNAVAILABLE"
        assert body["evidence"]["level"] == "wireDiscoveryObserved"
        assert SECRET not in output.out + output.err
        assert len(calls) == 1
        assert calls[0][0] == "/wire/v1/server.hello"
        assert calls[0][1] == "Bearer " + SECRET
        assert calls[0][2]["params"] == {"clientVersions": ["wire/1"], "clientPresentationSupports": []}


@pytest.mark.parametrize("mode,exit_code,code", [
    ("401", 3, "AUTHORIZATION_REFUSED"), ("wire403", 3, "AUTHORIZATION_REFUSED"),
    ("version", 4, "WIRE_VERSION_UNSUPPORTED"), ("badjson", 4, "WIRE_RESPONSE_INVALID"),
    ("mismatched", 4, "WIRE_RESPONSE_INVALID"), ("overlap", 4, "WIRE_RESPONSE_INVALID"),
    ("badcap", 4, "WIRE_RESPONSE_INVALID"), ("redirect", 4, "REDIRECT_REFUSED"),
    ("disconnect", 4, "SERVICE_UNAVAILABLE"), ("timeout", 7, "OBSERVATION_TIMEOUT"),
])
def test_http_failures_are_safe_and_never_retry(tmp_path, monkeypatch, capsys, mode, exit_code, code):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    with server(mode) as (endpoint, calls):
        path = config(tmp_path, endpoint)
        assert main(["doctor", "--config", str(path), "--service", "local", "--timeout", "0.05", "--json"]) == exit_code
        output = capsys.readouterr()
        assert json.loads(output.out)["error"]["code"] == code
        assert SECRET not in output.out + output.err
        assert len(calls) == 1


def test_effectful_transport_loss_is_unknown_without_retry():
    with server("disconnect") as (endpoint, calls):
        with pytest.raises(ClientError) as caught:
            WireClient(Service("local", endpoint, SECRET)).call("fixture.write", {}, "stable", effectful=True)
        assert caught.value.exit_code == 6
        assert caught.value.code == "OUTCOME_UNKNOWN"
        assert len(calls) == 1


@pytest.mark.parametrize("endpoint", ["http://example.com", "http://localhost", "https://user:secret@example.com",
                                        "https://example.com/path", "https://example.com?token=secret"])
def test_invalid_endpoint_is_rejected_locally(tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    with pytest.raises(ClientError) as caught:
        load_service(str(config(tmp_path, endpoint)), "local")
    assert caught.value.exit_code == 2


def test_group_write_plaintext_and_symlink_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_TEST_TOKEN", SECRET)
    path = config(tmp_path, "http://127.0.0.1:12345")
    path.chmod(0o620)
    with pytest.raises(ClientError, match="write access"):
        load_service(str(path), "local")
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ClientError):
        load_service(str(link), "local")
    path.write_text(json.dumps({"services": {"local": {"endpoint": "http://127.0.0.1", "tokenEnv": "TOOLS_TEST_TOKEN", "token": SECRET}}}))
    with pytest.raises(ClientError):
        load_service(str(path), "local")


def test_token_and_bad_arguments_do_not_leak(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TOOLS_TEST_TOKEN", raising=False)
    path = config(tmp_path, "http://127.0.0.1:12345")
    assert main(["doctor", "--config", str(path), "--service", "local", "--json"]) == 3
    assert main(["doctor", "--token", SECRET, "--json"]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
