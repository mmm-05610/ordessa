"""TLS on the managed HTTP lane: verification is never optional, the trust
anchor IS an explicit parameter (``ca_bundle``).

The https fake on loopback proves the injected-CA path completes a real
TLS handshake + MCP roundtrip; the same endpoint WITHOUT the injected CA
must be refused by default-store verification before any frame is sent.
"""
from __future__ import annotations

import pytest

from backend.errors import CONNECTION_FAILED, McpError
from backend.managed.client_http import HttpClientPolicy, HttpManagedClient
from http_helpers import bring_up, secret_remote
from http_helpers import FAST, HttpRealFactory
from managed_helpers import AllowingAuthority


def test_https_roundtrip_with_injected_ca_bundle(harness, endpoint, self_signed_tls):
    cert, key = self_signed_tls
    server = endpoint("normal", tls=(cert, key))
    revision = secret_remote(harness, server.base_url, headers={})
    policy = HttpClientPolicy(request_timeout=5.0, initialize_timeout=5.0,
                              ca_bundle=cert)
    factory = HttpRealFactory(harness.definitions, policy=policy)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease, catalog = bring_up(mgr, harness, caller, "srv-http", revision)
    assert catalog.tool_names and server.methods_seen().count("initialize") == 1
    client = factory.produced[-1]
    assert client.negotiated_protocol_version == "2025-11-25"
    mgr.close_lease(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id)


def test_unknown_authority_is_refused_by_default_verification_zero_frames(
        endpoint, self_signed_tls):
    cert, key = self_signed_tls
    server = endpoint("normal", tls=(cert, key))
    # no ca_bundle: the system trust store must reject the throwaway cert
    client = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    with pytest.raises(McpError) as refused:
        client.start()  # the handshake is up-front: nothing was ever sent
    assert refused.value.code == CONNECTION_FAILED
    assert server.requests == []  # zero application frames reached the peer
    # and a start failure is terminal for this instance (no restart path)
    client.close()
    with pytest.raises(McpError):
        client.start()
