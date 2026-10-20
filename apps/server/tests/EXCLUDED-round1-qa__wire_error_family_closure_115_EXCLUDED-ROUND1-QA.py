"""Order 115 — the error-family misuse is **closed**, not patched at one call site.

Order 101 fixed the two call sites that were passing an internal code into
`WireError`'s family slot. It did not close the family: constructing a
`WireError` with anything unknown there raised `ValueError`, and the HTTP route
answers anything escaping `dispatch` with a bare status, so the client received
`HTTP 500` and twenty-one bytes of plain text instead of a JSON-RPC error object
(`QA-008`, `R-0052 ①(a)`). Any *new* call site could reintroduce exactly that,
and 101's unit gates could not see it.

Closure here has two structural halves, both inside `server/wire/**`:

    `errors.converge_family`   a value in the family slot is projected onto a
                               real family, original kept as `details.internalCode`
    `WireService.dispatch`     anything else a handler raises still leaves as a
                               compliant error object, with the exception's *type*
                               as `details.internalCode` and never its text

Everything here drives the real wire with `raise_server_exceptions=False`: a
client that re-raises server exceptions turns "500" into a traceback, which is
the disguise this family wears (101's note, and the reason its own gates missed
the boundary).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_interfaces.http.serialization import errors as errors_module
from ordessa_interfaces.http.serialization import handlers as handlers_module
from ordessa_interfaces.http.serialization.errors import FAMILIES, WireError

#: A domain code that exists nowhere: not a family, not in `_BY_CODE`.
UNHEARD_OF = "PROVIDER_SYNC_LEDGER_CORRUPT"

FIVE_METHODS = ("usage.aggregate", "usage.export", "providerArtifacts.list",
                "providerArtifacts.install", "providerArtifacts.rollback")

PARAMS = {
    "usage.aggregate": {"sessions": []},
    "usage.export": {"sessions": []},
    "providerArtifacts.list": {"harness": "alpha"},
    "providerArtifacts.install": {"requestId": "art-115-install", "harness": "alpha",
                                  "version": "1.2.3", "sourceToken": "tok",
                                  "digest": "sha256:" + "a" * 64},
    "providerArtifacts.rollback": {"requestId": "art-115-rollback", "harness": "alpha",
                                   "version": "1.2.3"},
}


@pytest.fixture
def server(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}


def post(client, headers, method, params=None):
    return client.post(f"/wire/v1/{method}", headers=headers, json={
        "jsonrpc": "2.0", "id": method, "method": method,
        "params": PARAMS[method] if params is None else params,
    })


def refuse_with_family_slot_code(_self):
    """The 101 defect's own shape: an internal code where a family belongs."""
    raise WireError(UNHEARD_OF, "the provider sync ledger could not be read")


# -- G1: an unregistered domain code cannot become a bare 500 ---------------

def test_an_unregistered_domain_code_leaves_as_a_compliant_error_object(server, monkeypatch):
    monkeypatch.setattr(handlers_module.WireService, "_artifact_store", refuse_with_family_slot_code)
    _runtime, client, headers = server
    response = post(client, headers, "providerArtifacts.list")
    assert response.status_code == 200, (
        f"the family-slot misuse is still open: http={response.status_code} "
        f"content_type={response.headers.get('content-type')} body={response.text[:200]!r}")
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert error["code"] in FAMILIES, error
    assert error["details"]["internalCode"] == UNHEARD_OF, error


def test_a_code_the_mapping_knows_keeps_its_mapped_family(server):
    """Convergence is not "everything becomes UNAVAILABLE": `family_for` already
    knows this code, and the client branches on the family it was mapped to."""
    error = WireError("SESSION_BUSY", "another turn holds this session")
    assert (error.family, error.details["internalCode"]) == ("CONFLICT_REQUEST", "SESSION_BUSY")


def test_construction_never_raises_out_of_the_family_slot():
    """The old rule raised here, which is what turned into the 500 two frames up."""
    for value in (UNHEARD_OF, "", "not-a-code", "usage.aggregate", "SESSION_NOT_FOUND"):
        error = WireError(value, "constructed for real")
        assert error.family in FAMILIES, (value, error.family)
        if value not in FAMILIES:
            assert error.details["internalCode"] == value, (value, error.details)


# -- G2: the outbound family is always one of the twelve --------------------

def test_every_outbound_error_family_is_a_registered_family(server, monkeypatch):
    monkeypatch.setattr(handlers_module.WireService, "_artifact_store", refuse_with_family_slot_code)
    _runtime, client, headers = server
    bodies = [post(client, headers, method).json() for method in FIVE_METHODS]
    for method, body in zip(FIVE_METHODS, bodies, strict=True):
        assert "error" in body, (method, body)
        assert body["error"]["code"] in FAMILIES, (method, body["error"])


# -- G3: the wire is driven, not the implementation -------------------------

def test_the_gate_drives_real_http_and_not_a_direct_call(server):
    """A direct call can assert a Python object; only the socket answers whether
    the client's contract survived."""
    _runtime, client, headers = server
    response = post(client, headers, "providerArtifacts.list")
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["jsonrpc"] == "2.0" and envelope["id"] == "providerArtifacts.list"
    assert "error" in envelope and "result" not in envelope


def test_an_unexpected_exception_also_leaves_as_an_error_object(server, monkeypatch):
    """The second half of the closure: a handler that crashes on its own (101's
    `KeyError` face) must not reach the client as a bare status either."""
    def crash(_params):
        raise KeyError("/home/secret-user/credentials/ledger.json")

    runtime, client, headers = server
    monkeypatch.setitem(runtime.wire._handlers, "providerArtifacts.list", crash)  # noqa: SLF001
    response = post(client, headers, "providerArtifacts.list")
    assert response.status_code == 200, response.text[:200]
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] == "KeyError", error
    assert "secret-user" not in response.text, "the exception text reached the client"


def test_a_typed_refusal_is_never_re_projected_by_the_wall(server, monkeypatch):
    """The wall must not swallow the contract it protects.

    A `WireError` is the Server answering in family terms; re-wrapping it as
    `UNAVAILABLE` would turn every `NOT_FOUND` and `CONFLICT_REQUEST` on the
    face of this Server into a lie. This gate exists because the first version of
    the wall did exactly that, and the failure was only visible as a lost family.
    """
    def refuse(_params):
        raise WireError("NOT_FOUND", "that version is not installed",
                        {"internalCode": "ARTIFACT_VERSION_MISSING"})

    runtime, client, headers = server
    monkeypatch.setitem(runtime.wire._handlers, "providerArtifacts.list", refuse)  # noqa: SLF001
    error = post(client, headers, "providerArtifacts.list").json()["error"]
    assert error["code"] == "NOT_FOUND", error
    assert error["details"]["internalCode"] == "ARTIFACT_VERSION_MISSING", error


# -- the five methods of 101 keep their typed answers ----------------------

@pytest.mark.parametrize("method", FIVE_METHODS)
def test_the_five_methods_still_refuse_by_type(server, method):
    response = post(client_of(server), headers_of(server), method)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["error"]["code"] in FAMILIES


def client_of(server):
    return server[1]


def headers_of(server):
    return server[2]


# -- counter-examples: the pre-115 implementation must go red --------------

def _old_rule(value, details):
    """101's rule, restored verbatim: raise out of the family slot."""
    if value not in FAMILIES:
        raise ValueError(f"unknown wire error family: {value}")
    return value


def _dispatch_without_wall(self, method, params):
    """`dispatch` with the last wall taken out and nothing else changed."""
    handler = self._handlers.get(method)
    if handler is None:
        raise WireError("INVALID_REQUEST", f"{method} is not a wire/1 method")
    try:
        return handler(params)
    except handlers_module.ServerError as exc:
        raise WireError.from_server_error(exc) from exc


def test_counter_example_reverting_the_convergence_loses_the_original_code(server, monkeypatch):
    """G1's first falsifier, measured rather than assumed.

    Restoring 101's rule while the dispatch wall stands does **not** put the 500
    back — that is the point of having two walls — but the request no longer
    carries the domain code: `internalCode` comes out as the exception type
    `ValueError`. G1 asserts the code survives, so this reverts to red.
    """
    monkeypatch.setattr(errors_module, "converge_family", _old_rule)
    monkeypatch.setattr(handlers_module.WireService, "_artifact_store", refuse_with_family_slot_code)
    _runtime, client, headers = server
    response = post(client, headers, "providerArtifacts.list")
    assert response.status_code == 200, response.text[:200]
    error = response.json()["error"]
    assert error["details"].get("internalCode") != UNHEARD_OF, (
        "the convergence is not what carries the original code here: re-check G1")
    assert error["details"].get("internalCode") == "ValueError", error


def test_the_two_walls_of_115_are_no_longer_the_last_ones(server, monkeypatch):
    """G1's second falsifier, rewritten by what order 123 did.

    With both of 115's walls reverted, the request used to answer
    `500 / text/plain`. It now answers **200 with a typed refusal**, because 123
    added a wall around the wire route itself. The family is therefore closed at
    three layers, and what this gate asserts is the honest remainder: reverting
    115 still loses the *domain code* (`internalCode` becomes the exception type
    instead of `PROVIDER_SYNC_LEDGER_CORRUPT`), so 115's own convergence is not
    made redundant — it is what keeps the diagnostic true.

    The bare-500 shape is falsified where it now actually lives: at the envelope
    boundary, in `tests/server/test_transport_boundary_wall_123.py`.
    """
    monkeypatch.setattr(errors_module, "converge_family", _old_rule)
    monkeypatch.setattr(handlers_module.WireService, "dispatch", _dispatch_without_wall)
    monkeypatch.setattr(handlers_module.WireService, "_artifact_store", refuse_with_family_slot_code)
    _runtime, client, headers = server
    response = post(client, headers, "providerArtifacts.list")
    assert response.status_code == 200, (
        f"the boundary wall did not catch the reverted family: {response.text[:200]!r}")
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"].get("internalCode") == "ValueError", error
    assert error["details"].get("internalCode") != UNHEARD_OF, (
        "this gate would be green even without 115's convergence: re-check it")


# -- the guard's presence is part of the deliverable ------------------------

def test_the_101_guard_test_is_still_in_this_tree():
    """`D-002`/`D-005`: a guard that exists on one side silently reverts on merge."""
    assert Path("tests/server/test_wire_error_family_101.py").is_file()
    assert Path(__file__).name == "test_wire_error_family_closure_115.py"
