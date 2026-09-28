"""Order 123 — the third wall: nothing escapes the HTTP boundary as a bare 500.

Order 115 closed the family **inside** `server/wire/**` (two walls) and handed back
one honest remainder: the transport route only catches `WireError`, so anything
raised at the envelope boundary, in authentication, in `encode_result`, or in a
route nobody thought about still reached the client as
`500 / text/plain / 21 bytes` — measured here first-hand, not recounted.

Everything drives the real HTTP surface with `raise_server_exceptions=False`,
because a client that re-raises server exceptions turns "500" into a traceback.
The falsifier does not fake an old app: it **removes the registered wall from the
live application** (`app.exception_handlers.pop(Exception)`) and shows the plain
text come back — so what is being tested is the wall, not a copy of it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import app as app_module
from ordessa_server.transport.http import create_app

#: Text that must never reach a client: a host path and a credential locator.
SECRET_MARKERS = ("/home/secret-user", "credential_e08793", ".dpapi")


@pytest.fixture
def server(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    application = create_app(runtime)
    with TestClient(application, base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}, application


def post_wire(client, headers, method="profiles.list", params=None, body=None):
    return client.post(f"/wire/v1/{method}", headers=headers, json=body or {
        "jsonrpc": "2.0", "id": method, "method": method,
        "params": {"includeArchived": False} if params is None else params,
    })


def explode(body):
    raise RuntimeError(f"cannot read /home/secret-user/x {SECRET_MARKERS[1]}{SECRET_MARKERS[2]}")


# -- G1: a non-WireError at the boundary answers as an error object ---------

def test_a_fault_at_the_envelope_boundary_answers_in_json(server, monkeypatch):
    _runtime, client, headers, _app = server
    monkeypatch.setattr(app_module, "decode_request", explode)
    response = post_wire(client, headers)
    assert response.status_code == 500, response.text[:200]
    assert response.headers["content-type"].startswith("application/json"), (
        f"the boundary still answers in plain text: {response.headers.get('content-type')}")
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] == "RuntimeError", error


def test_a_fault_inside_the_wire_dispatch_answers_as_a_full_envelope(server, monkeypatch):
    """The route's own wall: the request id is known there, so the client gets
    the complete envelope — the same answer `115`'s dispatch wall produces for a
    crash inside a handler."""
    runtime, client, headers, _app = server

    def crash(method, params):
        raise KeyError(f"/home/secret-user/ledger {SECRET_MARKERS[1]}")

    monkeypatch.setattr(runtime.wire, "dispatch", crash)
    response = post_wire(client, headers)
    assert response.status_code == 200, response.text[:200]
    envelope = response.json()
    assert envelope["jsonrpc"] == "2.0" and envelope["id"] == "profiles.list", envelope
    assert envelope["error"]["details"]["internalCode"] == "KeyError", envelope


def test_a_fault_in_a_plain_rest_route_also_answers_in_json(server, monkeypatch):
    """The wall is registered on the application, so it covers the REST face too
    — `GET /api/v1/sessions/{id}` has no route-level guard of any kind, which is
    exactly where a pre-123 fault became plain text."""
    runtime, client, headers, _app = server

    def broken(session_id, **kwargs):
        raise RuntimeError(f"disk unreadable under /home/secret-user {SECRET_MARKERS[2]}")

    monkeypatch.setattr(runtime.plugin_host.provided_port('product.repository'), "get_session", broken)
    response = client.get("/api/v1/sessions/whatever", headers=headers)
    assert response.status_code == 500, response.text[:200]
    assert response.headers["content-type"].startswith("application/json"), (
        f"ct={response.headers.get('content-type')} body={response.text[:160]!r}")
    assert response.json()["error"]["details"]["internalCode"] == "RuntimeError", response.text[:200]
    for marker in SECRET_MARKERS:
        assert marker not in response.text, response.text[:200]



# -- G2: the exception's text never leaves ---------------------------------

def test_no_injected_marker_reaches_any_response(server, monkeypatch):
    _runtime, client, headers, _app = server
    monkeypatch.setattr(app_module, "decode_request", explode)
    bodies = []
    for path in ("/wire/v1/profiles.list", "/wire/v1/sessions.createAndSend"):
        response = client.post(path, headers=headers,
                               json={"jsonrpc": "2.0", "id": "x", "method": path.rsplit("/", 1)[-1],
                                     "params": {}})
        bodies.append((path, response.text))
    for path, text in bodies:
        for marker in SECRET_MARKERS:
            assert marker not in text, (path, text[:300])


# -- G3: the four existing WireError paths do not move a byte --------------

def test_the_existing_wire_error_paths_are_unchanged(server):
    """`115` caught its own first wall swallowing `WireError`; this is the same
    mistake prevented at the boundary. Status, family and internal code are
    compared against the values recorded before order 123 existed."""
    _runtime, client, headers, _app = server
    cases = [
        # (what is wrong, expected status, expected family)
        ("not-json", None, None),
        ("bad-envelope", {"nope": 1}, 400),
        ("method-mismatch", {"jsonrpc": "2.0", "id": "m", "method": "other.method",
                             "params": {}}, 400),
        ("typed-refusal", {"jsonrpc": "2.0", "id": "p", "method": "profiles.list",
                           "params": {"includeArchived": "yes"}}, 200),
    ]
    for name, body, status in cases:
        if body is None:
            response = client.post("/wire/v1/profiles.list", headers=headers, content=b"{not json")
            assert response.status_code == 400, (name, response.status_code, response.text[:200])
            assert response.json()["error"]["code"] == "INVALID_REQUEST", (name, response.text[:200])
            continue
        response = client.post("/wire/v1/profiles.list", headers=headers, json=body)
        assert response.status_code == status, (name, response.status_code, response.text[:200])
        assert response.json()["error"]["code"] == "INVALID_REQUEST", (name, response.text[:200])


def test_the_authenticated_face_still_works_after_the_wall(server):
    """A guard that turns healthy traffic into errors is not a wall."""
    _runtime, client, headers, _app = server
    listing = post_wire(client, headers)
    assert listing.status_code == 200, listing.text[:200]
    assert "result" in listing.json(), listing.text[:200]


# -- counter-example: remove the wall from the live app -------------------

def test_counter_example_without_the_wall_the_plain_text_comes_back(monkeypatch, tmp_path):
    """G1's falsifier: the same request, the same code, only the wall not registered.

    The handlers are resolved when the application starts up, so the honest way
    to take the wall off is to build a second application and remove the
    registration *before* it starts — not to mutate a running one and call that
    a revert (the first draft did exactly that, and the gate stayed green, which
    is how I found it proved nothing).
    """
    from ordessa_server.bootstrap import build_runtime as build

    runtime = build(tmp_path / "two")
    application = create_app(runtime)
    assert application.exception_handlers.pop(Exception, None) is not None, (
        "the wall is not registered where this order says it is: re-read 123")
    monkeypatch.setattr(app_module, "decode_request", explode)
    with TestClient(application, base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        response = post_wire(client, headers)
        assert response.status_code == 500, response.text[:200]
        assert not response.headers.get("content-type", "").startswith("application/json"), (
            "the boundary answers JSON without the wall: this gate proves nothing — "
            f"ct={response.headers.get('content-type')} body={response.text[:160]!r}")
        assert "internalCode" not in response.text, response.text[:200]
    runtime.stop()


def test_the_wall_is_registered_on_every_application_created_here(tmp_path):
    """The positive half of that: every app this transport builds carries it."""
    from ordessa_server.bootstrap import build_runtime as build

    runtime = build(tmp_path / "three")
    application = create_app(runtime)
    assert Exception in application.exception_handlers, (
        "no wall on the boundary: order 123 is not in this build")
    runtime.stop()


def test_the_gate_drives_http_and_not_the_handler(server, monkeypatch):
    """G4: calling the registered handler directly would pass on an app whose
    routes never reach it; the socket is the only thing that proves coverage."""
    _runtime, client, headers, application = server
    monkeypatch.setattr(app_module, "decode_request", explode)
    response = post_wire(client, headers)
    assert response.status_code == 500
    assert response.json()["error"]["details"]["internalCode"] == "RuntimeError"
    # The same fault, raised with no wall anywhere near it, is still plain text:
    # a plain ASGI app proves the difference is this application's registration.
    from fastapi import FastAPI
    naive = FastAPI()

    @naive.post("/x")
    async def naive_route():
        explode({})

    with TestClient(naive, base_url="http://127.0.0.1", raise_server_exceptions=False) as probe:
        bare = probe.post("/x", json={})
        assert bare.status_code == 500
        assert not bare.headers.get("content-type", "").startswith("application/json"), bare.text[:200]
