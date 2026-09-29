"""Security policy of the managed HTTP client (explicit, default strictest).

https-only with the EXACT loopback host exception (the storage rule
prefix-matches, so ``127.0.0.1.evil.test`` is refused here before any
socket - the probe's ruling, reused), redirects never followed, and an
origin-consistency guard in front of every request.
"""
from __future__ import annotations

import pytest

from backend.errors import McpError
from backend.managed.client_http import (
    MCP_HTTP_HOST_ORIGIN_MISMATCH,
    MCP_HTTP_REDIRECT_REFUSED,
    MCP_HTTP_URL_NOT_ALLOWED,
    HttpClientPolicy,
    HttpManagedClient,
)
from http_helpers import FAST  # noqa: F401 (policy presets)


def test_plain_http_allowed_only_to_the_exact_loopback_host(endpoint):
    server = endpoint("normal")
    # exact loopback: allowed (this is what every L2 test rides)
    ok = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    ok.start()
    ok.close()
    # prefix spoof: the storage-side ``startswith("http://127.0.0.1")``
    # would ACCEPT this url; the client must refuse before touching net I/O
    with pytest.raises(McpError) as refused:
        HttpManagedClient(url=f"http://127.0.0.1.evil.test:{ _port(server) }/mcp",
                          policy=FAST)
    assert refused.value.code == MCP_HTTP_URL_NOT_ALLOWED
    # non-loopback plain http: refused
    with pytest.raises(McpError) as refused:
        HttpManagedClient(url="http://mcp.example.test/a", policy=FAST)
    assert refused.value.code == MCP_HTTP_URL_NOT_ALLOWED
    # an unknown scheme: refused
    with pytest.raises(McpError) as refused:
        HttpManagedClient(url="ftp://127.0.0.1:21/mcp", policy=FAST)
    assert refused.value.code == MCP_HTTP_URL_NOT_ALLOWED


def test_loopback_exception_itself_can_be_switched_off(endpoint):
    server = endpoint("normal")
    strict = HttpClientPolicy(allow_loopback_http=False)
    with pytest.raises(McpError) as refused:
        HttpManagedClient(url=f"{server.base_url}/mcp", policy=strict)
    assert refused.value.code == MCP_HTTP_URL_NOT_ALLOWED


def test_redirect_is_refused_and_never_followed(endpoint):
    server = endpoint("redirect")
    client = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == MCP_HTTP_REDIRECT_REFUSED
    # exactly one request reached the wire; /moved was NEVER fetched, and
    # the auth/session surface therefore never moved origin
    assert len(server.requests) == 1
    assert all(record["path"] == "/mcp" for record in server.requests)
    assert client.closed  # local session torn down by the refusal


def test_origin_consistency_guard_blocks_repointing(endpoint):
    server = endpoint("normal")
    client = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    client.start()
    client.connect()
    before = list(server.methods_seen())
    # any later re-pointing of the connection target is refused BEFORE the
    # frame is written - the session (and its headers) never follow _host.
    client._host = "127.0.0.2"
    with pytest.raises(McpError) as refused:
        client.list_tools()
    assert refused.value.code == MCP_HTTP_HOST_ORIGIN_MISMATCH
    assert server.methods_seen() == before


def _port(server) -> int:
    return server.server_address[1]
