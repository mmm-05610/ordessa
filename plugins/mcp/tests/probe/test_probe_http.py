"""V03 HTTP (Streamable) probe tests: loopback fakes only, never external.

The fake endpoint records every request, so "carries no credentials",
"never follows a redirect" and "requests initialize with the newest
supported version" are proven by server-side evidence, not by the client's
own word.
"""
from __future__ import annotations

import json
import ssl
import threading

import pytest
from backend import probe
from backend.errors import MCP_DEFINITION_INVALID, McpError
from backend.probe_policy import ProbePolicy
from helpers import remote_canonical

FAST = ProbePolicy(timeout=2.0)
BRIEF = ProbePolicy(timeout=0.5)


# -- happy path + wire shape --------------------------------------------------------


def test_http_handshake_facts_and_request_shape(probe_primitives, http_endpoint):
    endpoint = http_endpoint("ok")
    facts = probe.probe_http(remote_canonical(endpoint.base_url + "/mcp"), policy=FAST)
    assert facts["status"] == "ok" and facts["transport"] == "remote"
    assert facts["serverInfo"] == {"name": "fake-http-mcp", "version": "0.1"}
    assert facts["protocolVersion"] == "2025-11-25"
    assert facts["credentialScope"] == "unproven"
    assert len(endpoint.seen) == 1
    headers, body = endpoint.seen[0]
    request = json.loads(body)
    assert request["method"] == "initialize" and request["id"] == 1
    assert request["params"]["protocolVersion"] == "2025-11-25"
    assert request["params"]["clientInfo"]["name"] == "ordessa-mcp-probe"
    assert headers["Content-Type"] == "application/json"


def test_http_downgrade_negotiated_from_response(probe_primitives, http_endpoint):
    endpoint = http_endpoint("downgrade")
    facts = probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert facts["protocolVersion"] == "2024-11-05"
    assert facts["negotiation"] == {
        "requested": "2025-11-25",
        "supported": ["2025-11-25", "2024-11-05"],
        "negotiated": "2024-11-05",
    }


def test_http_sse_answer_parsed(probe_primitives, http_endpoint):
    endpoint = http_endpoint("sse")
    facts = probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert facts["protocolVersion"] == "2025-11-25"


def test_http_initialize_is_never_a_catalog(probe_primitives, http_endpoint):
    endpoint = http_endpoint("ok")  # envelope carries a tools list on purpose
    facts = probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert "unseen-http-tool" not in json.dumps(facts)
    assert "tools" not in facts
    assert "tool-catalog" in facts["doesNotProve"]


# -- no credentials, ever -------------------------------------------------------------


def test_http_never_carries_declared_headers(probe_primitives, http_endpoint):
    endpoint = http_endpoint("ok")
    canonical = remote_canonical(endpoint.base_url, headers={
        "X-Cred": {"secretRef": "cred-t03"},
        "X-Plain": {"literal": "abc"},
    })
    facts = probe.probe_http(canonical, policy=FAST)
    headers, _ = endpoint.seen[0]
    lowered = {k.lower() for k in headers}
    assert "x-cred" not in lowered and "x-plain" not in lowered
    assert "authorization" not in lowered
    assert facts["credentialsExcluded"] == ["X-Cred", "X-Plain"]
    assert facts["credentialScope"] == "unproven"


# -- typed refusals --------------------------------------------------------------------


def test_http_auth_401_refused(probe_primitives, http_endpoint):
    endpoint = http_endpoint("auth401")
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_AUTH_REQUIRED


def test_http_auth_403_refused(probe_primitives, http_endpoint):
    endpoint = http_endpoint("auth403")
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_AUTH_REQUIRED


def test_http_redirect_never_followed(probe_primitives, http_endpoint):
    endpoint = http_endpoint("redirect")
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_REDIRECT_REFUSED
    assert len(endpoint.seen) == 1  # exactly the one POST; no second hop


@pytest.mark.parametrize("mode", ["badid", "noresult", "nonjson", "html"])
def test_http_format_refusals(probe_primitives, http_endpoint, mode):
    endpoint = http_endpoint(mode)
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_FORMAT_INVALID


def test_http_oversized_answer_refused(probe_primitives, http_endpoint):
    endpoint = http_endpoint("oversized")
    policy = ProbePolicy(timeout=2.0, max_bytes=1024)
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=policy)
    assert refused.value.code == probe.PROBE_RESPONSE_TOO_LARGE


def test_http_timeout_bounded(probe_primitives, http_endpoint):
    endpoint = http_endpoint("slow")
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=BRIEF)
    assert refused.value.code == probe.PROBE_TIMEOUT
    assert str(refused.value) == f"{probe.PROBE_TIMEOUT}: the server did not answer in time"


def test_http_connection_failed(probe_primitives):  # real socket attempt, nothing listening
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical("http://127.0.0.1:9/mcp"), policy=BRIEF)
    assert refused.value.code == probe.PROBE_CONNECTION_FAILED


def test_http_protocol_mismatch(probe_primitives, http_endpoint):
    endpoint = http_endpoint("mismatch")
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_PROTOCOL_MISMATCH


def test_http_cancel_before_request(probe_primitives, http_endpoint):
    endpoint = http_endpoint("ok")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST, cancel=cancel)
    assert refused.value.code == probe.PROBE_CANCELLED
    assert endpoint.seen == []  # the endpoint was never touched


# -- TLS: verification is the default, not a suggestion ----------------------------------


def test_https_rejects_self_signed_without_trust(probe_primitives, http_endpoint,
                                                self_signed_tls):
    endpoint = http_endpoint("ok", tls_cert=self_signed_tls)
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert refused.value.code == probe.PROBE_CONNECTION_FAILED
    assert "TLS handshake failed" in refused.value.message


def test_https_completes_handshake_when_ca_trusted(probe_primitives, http_endpoint,
                                                   self_signed_tls, monkeypatch):
    # The probe never overrides the SSL context; trust comes only from the
    # process-default context, which we anchor to the throwaway CA here.
    def _context(*args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(self_signed_tls[0])
        return context

    monkeypatch.setattr(ssl, "_create_default_https_context", _context)
    endpoint = http_endpoint("ok", tls_cert=self_signed_tls)
    facts = probe.probe_http(remote_canonical(endpoint.base_url), policy=FAST)
    assert facts["status"] == "ok" and facts["transport"] == "remote"


# -- remote definition policy (read-only reuse of the validator) --------------------------


def test_remote_plain_http_off_loopback_refused_before_network():
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical("http://example.invalid/mcp"), policy=FAST)
    assert refused.value.code == MCP_DEFINITION_INVALID


def test_remote_loopback_prefix_lookalike_refused():
    # canonical_definition_v2 matches a *prefix*; the probe demands the
    # exact host, so "127.0.0.1.evil" cannot ride through as loopback.
    with pytest.raises(McpError) as refused:
        probe.probe_http(remote_canonical("http://127.0.0.1.evil.test:8080/mcp"),
                         policy=FAST)
    assert refused.value.code == probe.PROBE_URL_NOT_ALLOWED


def test_probe_definition_dispatches_remote(probe_primitives, http_endpoint):
    endpoint = http_endpoint("ok")
    facts = probe.probe_definition(remote_canonical(endpoint.base_url), policy=FAST)
    assert facts["transport"] == "remote"
