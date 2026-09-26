"""Order 104: a probe leaves exactly one request, to the endpoint it was given.

Three boundaries are asserted here, all of them by *counting what arrived* at a
loopback fake rather than by reading the source:

* a 3xx is refused and the second hop is never attempted (G1);
* the credential therefore has no second hop to travel in (G1);
* a name is refused for the addresses it resolves to, not for its spelling (G2).

A fourth, quieter boundary is what the whole file rests on: `getaddrinfo` is
replaced by a table that only knows the loopback fakes and the addresses named
below, and everything else raises. So a test that accidentally tried to dial a
real provider would fail here rather than send a request (G4 - this order costs
nothing because nothing can leave the machine).
"""
from __future__ import annotations

import ipaddress
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ordessa_server_compat.model_configs import probe

FAKE_KEY = "DUMMY-NOT-A-REAL-SECRET-0123456789"

#: Addresses that may appear in a stub answer. Named as data so the test that
#: refuses them and the test that allows them cannot drift apart.
IMDS = "169.254.169.254"
PUBLIC_V4 = "93.184.216.34"
PRIVATE_V4 = "10.0.0.1"

DNS_TABLE: dict[str, list[tuple[str, int]]] = {
    "imds-behind-a-name.test": [(IMDS, 443)],
    "mixed-answer.test": [(PUBLIC_V4, 443), (PRIVATE_V4, 443)],
    "public-only.test": [(PUBLIC_V4, 443)],
    "v6-link-local.test": [("fe80::1", 443)],
}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


#: Every *name* this file answered, and every numeric literal it
#: answered itself - the two sets of names that could have gone anywhere. The G4
#: gate is a statement over the first list; the second exists because a real
#: resolver answers an address without asking anyone. A name neither branch
#: knows was never resolved here: it came back `gaierror`.
RESOLVED: list[str] = []
ANSWERED_DIRECTLY: list[str] = []

_LOOPBACK_ADDRESS = {"localhost": (socket.AF_INET, "127.0.0.1")}


def _stubbed_getaddrinfo(host, port, *args, **kwargs):
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        ANSWERED_DIRECTLY.append(host)
        return [(socket.AF_INET6 if literal.version == 6 else socket.AF_INET,
                 socket.SOCK_STREAM, 6, "", (host, port))]
    if host in DNS_TABLE:
        RESOLVED.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))
                for ip, p in DNS_TABLE[host]]
    if host in LOOPBACK:
        RESOLVED.append(host)
        family, address = _LOOPBACK_ADDRESS.get(host, (socket.AF_INET6, host))
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]
    # Anything else stays unresolvable, and the code under test is required to
    # call that PROBE_UNREACHABLE rather than try a different name.
    raise socket.gaierror(8, f"this file does not resolve {host!r}")


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _stubbed_getaddrinfo)


class _Recorder:
    def __init__(self):
        self.requests: list[dict] = []

    def record(self, method, path, headers):
        self.requests.append({
            "method": method, "path": path,
            "authorization": headers.get("Authorization"),
            "host": headers.get("Host"),
        })

    @property
    def count(self):
        return len(self.requests)


class _Server:
    """A loopback fake, and the only thing these tests ever connect to."""

    def __init__(self, responder, recorder, tag):
        recorder_ref, tag_ref = recorder, tag

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _talk(self, method):
                recorder_ref.record(method, self.path, self.headers)
                responder(self, recorder_ref)

            def do_GET(self):
                self._talk("GET")

            def do_CONNECT(self):
                self._talk("CONNECT")
                self.close_connection = True
                self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.recorder = recorder
        self.tag = tag
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # Under a real listener the accept thread can lag the bound port; wait
        # for one accepted connection before the first request under test.
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close()
                recorder.requests.clear()
                break
            except OSError:
                time_sleep()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def time_sleep():
    threading.Event().wait(0.02)


def models_json(target: _Server):
    def responder(handler, _recorder):
        body = json.dumps({"data": [{"id": "model-a"}]}).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    return responder


def redirect_to(target: _Server):
    def responder(handler, _recorder):
        handler.send_response(302)
        handler.send_header("Location", f"http://127.0.0.1:{target.port}/models")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
    return responder


@pytest.fixture
def declared():
    """The endpoint the user declares: a loopback fake that answers normally."""
    server = _Server(models_json(None), _Recorder(), "declared")
    yield server
    server.close()


@pytest.fixture
def redirector():
    """A declared endpoint that answers 302 to a *second* live fake."""
    target = _Server(models_json(None), _Recorder(), "target")
    origin = _Server(redirect_to(target), _Recorder(), "origin")
    yield origin, target
    origin.close()
    target.close()


# -- G1: one request, to the declared endpoint -----------------------------

def test_a_redirect_is_refused_as_a_typed_endpoint_block(redirector):
    origin, target = redirector
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models(f"http://127.0.0.1:{origin.port}", FAKE_KEY)
    assert caught.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_exactly_one_request_leaves_when_the_endpoint_redirects(redirector):
    """The assertion the order asks for by name: the second hop is not read,
    not fetched, not attempted. A guard that follows and *then* complains would
    pass the code check above and fail this one."""
    origin, target = redirector
    with pytest.raises(probe.ProbeError):
        probe.pull_models(f"http://127.0.0.1:{origin.port}", FAKE_KEY)
    assert origin.recorder.count == 1, origin.recorder.requests
    assert target.recorder.count == 0, (
        f"the redirect target was contacted: {target.recorder.requests}")


def test_the_credential_reaches_the_declared_endpoint_and_no_one_else(redirector):
    origin, target = redirector
    with pytest.raises(probe.ProbeError):
        probe.pull_models(f"http://127.0.0.1:{origin.port}", FAKE_KEY)
    assert origin.recorder.requests[0]["authorization"] == f"Bearer {FAKE_KEY}"
    assert target.recorder.requests == []


def test_probe_connection_refuses_the_redirect_too(redirector):
    """Both public entries, not just the one the order names: `probeConnection`
    reaches the same transport and used to follow the same redirect."""
    origin, target = redirector
    result = probe.probe_connection(f"http://127.0.0.1:{origin.port}", FAKE_KEY)
    assert result.status == "unreachable"
    assert result.detail == "PROBE_ENDPOINT_BLOCKED"
    assert target.recorder.count == 0


def test_a_configured_proxy_is_not_used_even_for_a_plain_http_probe(declared, monkeypatch):
    """The hop the order did not name: with `http_proxy` set, `urlopen` sends the
    absolute URI *and* the Authorization header to the intermediary and reports
    the exchange as a probe of the declared endpoint.

    Asserted two ways: the fake proxy records nothing, and the declared endpoint
    sees an origin-form path (a proxied request would say `http://127.0.0.1:PORT/...`).
    """
    proxy = _Server(models_json(None), _Recorder(), "proxy")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.port}")
    monkeypatch.setenv("https_proxy", f"http://127.0.0.1:{proxy.port}")
    monkeypatch.setenv("no_proxy", "")
    try:
        result = probe.pull_models(f"http://127.0.0.1:{declared.port}", FAKE_KEY)
    finally:
        proxy.close()
    assert result.status == "ok", result
    assert proxy.recorder.count == 0, proxy.recorder.requests
    assert all(not request["path"].startswith("http") for request in declared.recorder.requests), (
        declared.recorder.requests)


def test_the_module_does_not_go_through_the_shared_default_opener(declared, monkeypatch):
    """Behavioural proof of the same fact, independent of the environment:
    poison `urllib`'s global opener and show a probe still works."""
    class _Exploding:
        def open(self, *args, **kwargs):
            raise AssertionError("the probe used urllib's shared default opener")

    monkeypatch.setattr(probe.urllib.request, "_opener", _Exploding())
    assert probe.pull_models(f"http://127.0.0.1:{declared.port}", FAKE_KEY).models == ("model-a",)


# -- G2: what the name resolves to, not how it is spelled ------------------

def test_a_name_resolving_to_imds_is_refused(monkeypatch):
    attempts = _patch_connect(monkeypatch)
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models("https://imds-behind-a-name.test", FAKE_KEY)
    assert caught.value.code == "PROBE_ENDPOINT_BLOCKED"
    assert attempts == [], "refused, but a socket was opened anyway"


def test_a_name_offering_public_and_private_together_is_refused(monkeypatch):
    """"Resolved to something fine" is only safe if *every* answer is fine."""
    _patch_connect(monkeypatch)
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models("https://mixed-answer.test", FAKE_KEY)
    assert caught.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_an_ipv6_link_local_answer_is_refused(monkeypatch):
    _patch_connect(monkeypatch)
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models("https://v6-link-local.test", FAKE_KEY)
    assert caught.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_literal_private_addresses_are_still_refused(monkeypatch):
    """The leg that already worked must not have moved: same code, same verdict."""
    _patch_connect(monkeypatch)
    for url in (f"https://{PRIVATE_V4}", "https://192.168.1.9", f"https://{IMDS}"):
        with pytest.raises(probe.ProbeError) as caught:
            probe.pull_models(url, FAKE_KEY)
        assert caught.value.code == "PROBE_ENDPOINT_BLOCKED", url


# -- G3: the honest paths stay honest --------------------------------------

def test_a_public_name_still_passes_the_endpoint_check(monkeypatch):
    """The positive control for G2: this order must not turn the probe off.

    The connect is patched out, so passing here means the *check* allowed it -
    not that a request happened to fail later.
    """
    _patch_connect(monkeypatch)
    base, host = probe._validate_endpoint("https://public-only.test")
    assert (base, host) == ("https://public-only.test", "public-only.test")


def test_an_unresolvable_name_is_still_unreachable_not_blocked(monkeypatch):
    """A name with no answer is not a forbidden endpoint; the wire vocabulary for
    "could not get there" must not quietly become "we refused you"."""
    _patch_connect(monkeypatch)
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models("https://nothing-here.test", FAKE_KEY)
    assert caught.value.code == "PROBE_UNREACHABLE"


def test_both_public_entries_still_succeed_against_a_loopback_fake(declared):
    pulled = probe.pull_models(f"http://127.0.0.1:{declared.port}", FAKE_KEY)
    assert (pulled.status, pulled.models) == ("ok", ("model-a",))
    connection = probe.probe_connection(f"http://localhost:{declared.port}", FAKE_KEY)
    assert connection.status == "reachable"


def test_the_scheme_rule_is_checked_before_any_resolution(monkeypatch):
    """`ftp://` was refused before this order and must still be refused *without*
    resolving: the order's forbiddance is about the URL, not the address."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("a forbidden scheme must not be resolved")

    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    with pytest.raises(probe.ProbeError) as caught:
        probe.pull_models("ftp://example.com", FAKE_KEY)
    assert caught.value.code == "PROBE_ENDPOINT_BLOCKED"


# -- G4: nothing left this machine -----------------------------------------

def test_nothing_was_resolved_outside_this_files_own_table():
    """G4, mechanically: the whole file's DNS traffic is this list.

    Anything not in it would have come back `gaierror`, so an accidental real
    call could not have happened *and* the assertion still says so after the
    fact. Runs last in file order by position, and a test that broke the rule
    fails on its own name first.
    """
    allowed = set(DNS_TABLE) | LOOPBACK
    assert set(RESOLVED) <= allowed, sorted(set(RESOLVED) - allowed)
    # A numeric address needs no resolver, so answering those is not egress -
    # but every one of them has to be a constant this file declared, so a test
    # cannot quietly start dialing a real host by spelling out its IP.
    declared_numbers = {PRIVATE_V4, PUBLIC_V4, IMDS, "192.168.1.9", "127.0.0.1", "::1"}
    assert set(ANSWERED_DIRECTLY) <= declared_numbers, sorted(set(ANSWERED_DIRECTLY) - declared_numbers)


def _patch_connect(monkeypatch):
    """Replace socket creation so a connect attempt is recorded, never performed.

    Returns the list the caller asserts on; an empty list is the proof that a
    refusal happened before any socket, which is what "the probe is not a port
    scanner" is supposed to mean.
    """
    attempts: list[tuple] = []

    def _no_connect(address, *args, **kwargs):
        attempts.append(address)
        raise AssertionError(f"a probe attempted to connect to {address!r}")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    return attempts
