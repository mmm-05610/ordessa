"""The mem0 REST client against an in-process fake server: request shapes
(the MB-5 断言请求形状 surface), typed failures, liveness."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ordessa_memory.mem0_client import (
    Mem0Client, Mem0ClientError, Mem0ServerError, Mem0Unreachable)


class _Handler(BaseHTTPRequestHandler):
    def _log(self, body=None):
        self.server.requests.append(
            (self.command, self.path, dict(self.headers), body))

    def _respond(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        self._log()
        if self.path.startswith("/boom"):
            self._respond(503, {"detail": "upstream down"})
        elif self.path.startswith("/docs"):
            self._respond(200, {"ok": True})
        else:
            self._respond(200, {"results": [{"id": "m1", "memory": "x"}]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._log(body)
        if self.path == "/search":
            self._respond(200, {"results": [{"id": "m9", "memory": "命中", "score": 0.42}]})
        elif self.path == "/configure":
            self._respond(200, {"message": "Configuration set successfully"})
        else:
            self._respond(200, {"results": []})

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    s = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    s.requests = []
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()


@pytest.fixture
def client(server):
    return Mem0Client(f"http://127.0.0.1:{server.server_address[1]}",
                      lambda: "admin-key-abc", timeout=5.0)


def _hdr(headers, name):
    """HTTP header names are case-insensitive on the wire (urllib normalizes
    to ``X-Api-Key``); look up accordingly."""
    return {k.lower(): v for k, v in headers.items()}.get(name.lower())


def test_liveness_walks_docs(client):
    assert client.docs_liveness() is True


def test_add_messages_request_shape(server, client):
    client.add_messages(
        [{"role": "user", "content": "我喜欢深色模式"},
         {"role": "assistant", "content": "好的"}],
        "ordessa:srv-1:profile:p1")
    method, path, headers, body = server.requests[-1]
    assert (method, path) == ("POST", "/memories")
    assert _hdr(headers, "X-API-Key") == "admin-key-abc"
    assert body["user_id"] == "ordessa:srv-1:profile:p1"
    assert body["messages"] == [
        {"role": "user", "content": "我喜欢深色模式"},
        {"role": "assistant", "content": "好的"}]


def test_search_scopes_through_filters(server, client):
    client.search("深色", "ordessa:srv-1:profile:p2", top_k=5)
    method, path, headers, body = server.requests[-1]
    assert (method, path) == ("POST", "/search")
    assert body == {"query": "深色", "filters": {"user_id": "ordessa:srv-1:profile:p2"},
                    "top_k": 5}
    assert _hdr(headers, "X-API-Key") == "admin-key-abc"


def test_get_all_urlencodes_the_namespace(server, client):
    client.get_all("ordessa:srv-1:profile:p3")
    method, path, _, _ = server.requests[-1]
    assert (method, path) == ("GET", "/memories?user_id=ordessa%3Asrv-1%3Aprofile%3Ap3")


def test_configure_posts_the_admin_payload(server, client):
    answer = client.configure({"llm": {"config": {"openai_base_url": "http://fake"}}})
    assert answer["message"] == "Configuration set successfully"
    method, path, headers, body = server.requests[-1]
    assert (method, path) == ("POST", "/configure")
    assert _hdr(headers, "X-API-Key") == "admin-key-abc"


def test_5xx_is_a_typed_server_error(server):
    client = Mem0Client(f"http://127.0.0.1:{server.server_address[1]}", lambda: "k")
    with pytest.raises(Mem0ServerError) as excinfo:
        client._request("GET", "/boom")
    assert excinfo.value.status == 503


def test_unreachable_is_a_typed_error():
    client = Mem0Client("http://127.0.0.1:9", lambda: "k", timeout=2.0)
    with pytest.raises(Mem0Unreachable):
        client.docs_liveness()


def test_4xx_is_a_typed_client_error(server):
    class _Four(_Handler):
        def do_GET(self):  # noqa: N802
            self._respond(401, {"detail": "no"})

        def log_message(self, *args):
            pass

    s2 = ThreadingHTTPServer(("127.0.0.1", 0), _Four)
    t2 = threading.Thread(target=s2.serve_forever, daemon=True)
    t2.start()
    try:
        client = Mem0Client(f"http://127.0.0.1:{s2.server_address[1]}", lambda: "k")
        with pytest.raises(Mem0ClientError) as excinfo:
            client.docs_liveness()
        assert excinfo.value.status == 401
    finally:
        s2.shutdown()
        s2.server_close()


def test_the_key_never_lands_on_the_client_repr(server):
    client = Mem0Client(f"http://127.0.0.1:{server.server_address[1]}", lambda: "sekret-value")
    assert "sekret-value" not in repr(client)
