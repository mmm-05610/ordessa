"""Order 101: five registered methods must answer typed, never 500.

`WireError`'s first positional argument is the *family* - one of twelve - and
these call sites were passing internal codes there, so constructing the error
raised `ValueError` and the HTTP layer answered 500. The internal code is not
lost: it moves to `details.internalCode`, which is what
`WireError.from_server_error` already does.

Every gate here drives the real wire with `raise_server_exceptions=False`,
because a test client that re-raises server exceptions turns "500" into a
Python traceback - the exact disguise this family of defects wears. The order's
own audit trail is 099/098: implementation plus its own tests green, the wire
never driven.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_compat.execution.artifact_store import ArtifactStore, ArtifactStoreError
from ordessa_server.transport.http import create_app
from ordessa_server_compat.usage_aggregate import UsageAggregator
from ordessa_server.wire import handlers as handlers_module
from ordessa_server_compat import core_wire as compat_wire
from ordessa_server.wire.errors import FAMILIES, WireError

FIVE_METHODS = ("usage.aggregate", "usage.export", "providerArtifacts.list",
                "providerArtifacts.install", "providerArtifacts.rollback")

PARAMS = {
    "usage.aggregate": {"sessions": []},
    "usage.export": {"sessions": []},
    "providerArtifacts.list": {"harness": "alpha"},
    "providerArtifacts.install": {"requestId": "art-101-install", "harness": "alpha",
                                  "version": "1.2.3", "sourceToken": "tok",
                                  "digest": "sha256:" + "a" * 64},
    "providerArtifacts.rollback": {"requestId": "art-101-rollback", "harness": "alpha",
                                   "version": "1.2.3"},
}


@pytest.fixture
def server(tmp_path):
    """A composition that has neither service - which is every composition the
    Server builds today (bootstrap imports neither implementation)."""
    runtime = build_runtime(tmp_path / "data")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}


def post(client, headers, method, params):
    return client.post(f"/wire/v1/{method}", headers=headers,
                       json={"jsonrpc": "2.0", "id": method, "method": method, "params": params})


# -- G1: no 500 -------------------------------------------------------------

@pytest.mark.parametrize("method", FIVE_METHODS)
def test_a_composition_without_the_service_refuses_by_type(server, method):
    _runtime, client, headers = server
    response = post(client, headers, method, PARAMS[method])
    assert response.status_code == 200, (
        f"{method} answered http={response.status_code}; a typed refusal must not be a 500")
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] in {
        "USAGE_AGGREGATOR_UNAVAILABLE", "ARTIFACT_STORE_UNAVAILABLE"}, error


def test_the_internal_code_says_which_of_the_two_faces_is_absent(server):
    """The two guards collapse onto one family and must stay tellable apart."""
    _runtime, client, headers = server
    usage = post(client, headers, "usage.aggregate", PARAMS["usage.aggregate"]).json()
    artifacts = post(client, headers, "providerArtifacts.list",
                     PARAMS["providerArtifacts.list"]).json()
    assert usage["error"]["details"]["internalCode"] == "USAGE_AGGREGATOR_UNAVAILABLE"
    assert artifacts["error"]["details"]["internalCode"] == "ARTIFACT_STORE_UNAVAILABLE"


# -- G2: every family argument in the file is a real family ----------------

def test_no_wire_error_is_constructed_with_a_non_family_first_argument():
    """Text scan plus runtime construction.

    The scan is the "did anyone add another one" gate; the construction loop is
    the "does the family set still accept these strings" gate. Both are needed:
    098 found two of these by reading, and the reason they survived is that no
    test ever built them.
    """
    source = Path(handlers_module.__file__).read_text(encoding="utf-8")
    source += Path(compat_wire.__file__).read_text(encoding="utf-8")
    found = re.findall(r'WireError\(\s*"([A-Z_]+)"', source)
    found += re.findall(r'WireError\(\s*\n\s*"([A-Z_]+)"', source)
    assert found, "the scan found nothing - it has stopped matching reality"
    illegal = sorted({name for name in found if name not in FAMILIES})
    assert illegal == [], illegal
    for name in sorted(set(found)):
        WireError(name, "constructed for real")


def test_the_families_are_the_twelve_locked_ones():
    """A new family would be a contract change, not a fix."""
    assert len(FAMILIES) == 12


# -- G1's other half: with the services, the methods work -----------------

def test_usage_aggregate_answers_with_real_numbers_once_injected(server):
    runtime, client, headers = server
    handlers = runtime.plugin_host.provided_port("compat.handlers")
    repository = runtime.plugin_host.provided_port("product.repository")
    handlers.usage_aggregator = UsageAggregator(repository)
    body = post(client, headers, "usage.aggregate", {"sessions": []}).json()
    assert "result" in body, body
    assert body["result"] == {"sessions": []}
    exported = post(client, headers, "usage.export", {"sessions": []}).json()
    assert "result" in exported, exported


def test_provider_artifacts_list_answers_once_the_store_is_injected(server, tmp_path):
    runtime, client, headers = server
    runtime.plugin_host.provided_port('compat.handlers').artifact_store = ArtifactStore(tmp_path / "artifacts")
    body = post(client, headers, "providerArtifacts.list", {"harness": "alpha"}).json()
    assert body["result"] == {"harness": "alpha", "versions": [], "current": None}, body


def test_rolling_back_to_an_uninstalled_version_is_not_found(server, tmp_path):
    """A user-correctable fact, measured before this order as a 500."""
    runtime, client, headers = server
    runtime.plugin_host.provided_port('compat.handlers').artifact_store = ArtifactStore(tmp_path / "artifacts")
    response = post(client, headers, "providerArtifacts.rollback",
                    PARAMS["providerArtifacts.rollback"])
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND", error
    assert error["details"]["internalCode"] == "ARTIFACT_VERSION_MISSING"


def test_a_digest_that_does_not_match_the_staged_tree_is_an_invalid_request(server, tmp_path):
    runtime, client, headers = server
    source = tmp_path / "artifacts" / "incoming" / "staged-token"
    source.mkdir(parents=True)
    (source / "harness.js").write_text("export default 1;\n", encoding="utf-8")
    runtime.plugin_host.provided_port('compat.handlers').artifact_store = ArtifactStore(tmp_path / "artifacts")
    response = post(client, headers, "providerArtifacts.install",
                    PARAMS["providerArtifacts.install"])
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST", error
    assert error["details"]["internalCode"] == "ARTIFACT_DIGEST_MISMATCH"


# -- the second wall: install was unreachable in both directions ----------

def test_install_declares_the_digest_its_locked_contract_requires():
    """The authoritative artifact lists `digest` in required (evidence §3); the
    Server's shape did not, so no request could ever succeed: omit it and the
    handler raised `KeyError` (a 500), send it and the shape rejected it.
    """
    required, optional = compat_wire._PARAM_SHAPES["providerArtifacts.install"]  # noqa: SLF001
    assert "digest" in required
    assert "digest" not in optional


def test_a_request_without_the_digest_is_refused_by_type(server):
    _runtime, client, headers = server
    params = {k: v for k, v in PARAMS["providerArtifacts.install"].items() if k != "digest"}
    response = post(client, headers, "providerArtifacts.install", params)
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST", error
    assert "digest" in error["message"], error


def test_an_already_installed_version_is_reported_as_a_state_conflict():
    """The third family in the mapping table, asserted on the mapping: staging a
    full install through the wire would need a bundle whose digest both sides
    compute identically, and that belongs to 57's tests, not to this gate.
    """
    error = compat_wire._artifact_error(  # noqa: SLF001
        ArtifactStoreError("ARTIFACT_VERSION_EXISTS", "alpha/1.2.3 is already installed"))
    assert (error.family, error.details["internalCode"]) == (
        "CONFLICT_REQUEST", "ARTIFACT_VERSION_EXISTS")


# -- counter-examples: the old shapes must go red -------------------------

def test_counter_example_the_internal_code_in_the_family_slot_is_no_longer_a_500(server, monkeypatch):
    """Restore exactly the defect: an internal code in the family position.

    Order 115 supersedes the assertion this gate used to carry ("back to a 500").
    The family slot now converges onto a real family and keeps the original code,
    so the *consequence* the client saw is gone even with the call-site defect
    put back; 101's own fix is what keeps the family honest rather than merely
    well-formed. `test_wire_error_family_closure_115.py` is where the bare-500
    shape is now falsified, and it needs both walls down to bring it back.
    """
    def old_shape(_self):
        raise WireError("ARTIFACT_STORE_UNAVAILABLE",
                        "this composition has no artifact management face")

    monkeypatch.setattr(compat_wire.CoreWireHandlers, "_artifact_store", old_shape)
    _runtime, client, headers = server
    response = post(client, headers, "providerArtifacts.list", {"harness": "alpha"})
    assert response.status_code == 200, (
        f"the family slot is still able to 500: http={response.status_code}")
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] == "ARTIFACT_STORE_UNAVAILABLE", error
    monkeypatch.undo()
    assert compat_wire.CoreWireHandlers._artifact_store is not old_shape


def test_counter_example_the_shape_without_digest_reports_a_crash_not_a_500(server):
    """And the half-fix that only touches the family slot: with `digest` still
    missing from the shape, a client that omits it walks into `KeyError`.

    Same supersession note as the gate above: 115's dispatch wall means the
    client now gets a JSON-RPC error object naming the exception type — which
    is why 101's shape fix still has to stand, since `UNAVAILABLE/KeyError` is a far
    worse answer than `INVALID_REQUEST` naming the missing field.

    The defect is restored on the live method registry (`amend_shape`) — the
    one table dispatch reads. A registry mutation is not monkeypatch-undoable,
    so the original descriptor's shape is re-declared before returning.
    """
    runtime, client, headers = server
    original = runtime.wire._registry.lookup("providerArtifacts.install")  # noqa: SLF001
    runtime.wire.amend_shape(
        "providerArtifacts.install",
        required={"requestId", "harness", "version", "sourceToken"}, optional=set())
    try:
        params = {k: v for k, v in PARAMS["providerArtifacts.install"].items() if k != "digest"}
        response = post(client, headers, "providerArtifacts.install", params)
        assert response.status_code == 200, response.text[:200]
        error = response.json()["error"]
        assert (error["code"], error["details"]["internalCode"]) == ("UNAVAILABLE", "KeyError"), error
    finally:
        runtime.wire.amend_shape(
            "providerArtifacts.install",
            required=original.required_params, optional=original.optional_params)
    restored_required, _ = compat_wire._PARAM_SHAPES["providerArtifacts.install"]  # noqa: SLF001
    assert "digest" in restored_required
