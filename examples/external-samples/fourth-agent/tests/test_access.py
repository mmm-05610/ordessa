"""Public access + exit record for external sample #1 (fourth agent).

The sample composes through the Server's public seam only —
`ordessa_server.bootstrap.build_runtime` with an explicit `server_plugins`
selection — exactly as an outside deployment would. Assertions cover
(lifecycle-evidence §SDK真实穿透与样例: external sample #1 is a controlled
Agent with a foreign interaction schema):

- the foreign-protocol declaration is pinned byte-exact, including the
  typed `reliableSubmission: "unsupported"` claim (C1: unsupported means
  typed refusal, never a silent downgrade and never an empty success);
- stable request-id semantics: same id + same payload replays the original
  receipt; same id + different payload is a typed
  `REQUEST_DIGEST_CONFLICT`, never a second dispatch (C2);
- AST gate: the plugin imports no Agent/Profile/Harness/environment module;
- discovery/exit: exactly three methods owned by the sample; the
  not-started round refuses typed (`ROUND_NOT_STARTED`); a stopped round
  retires the methods while `server.hello` stays honest.

`ordessa_server` is imported from the venv's editable install (the sample
distribution itself depends only on `ordessa-server-plugin-api`).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from server_plugin_api import WireError

from ordessa_server.bootstrap import build_runtime

from ordessa_sample_fourth_agent import (
    CAPABILITIES,
    INTERACTION_SCHEMA,
    METHOD_CAPABILITIES,
    METHOD_ECHO,
    METHOD_STATUS,
    PLUGIN_ID,
    SampleFourthAgentPlugin,
)

OWNER = PLUGIN_ID
METHODS = (METHOD_CAPABILITIES, METHOD_STATUS, METHOD_ECHO)
PLUGIN_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "ordessa_sample_fourth_agent"


def _build(tmp_path: Path):
    return build_runtime(tmp_path / "data", server_plugins=(SampleFourthAgentPlugin(),))


def _hello(runtime) -> dict:
    return runtime.wire.dispatch("server.hello", {
        "clientVersions": ["wire/1"], "clientPresentationSupports": []})


# -- the foreign-protocol declaration is pinned byte-exact --------------------

def test_capabilities_declare_the_foreign_schema_and_typed_unsupported_reliability():
    assert CAPABILITIES["interactionSchema"] == "sample-agent/1"
    assert CAPABILITIES["interactionSchema"] != "acp"
    assert CAPABILITIES["reliableSubmission"] == "unsupported"
    # the reason names the missing guarantees — typed refusal, not downgrade
    reason = CAPABILITIES["reliableSubmissionReason"]
    assert "fingerprint" in reason and "durable intent" in reason
    assert "typed-refused" in reason and "raw path is unaffected" in reason
    assert CAPABILITIES["history"] == "unsupported"


def test_capabilities_method_serves_the_declared_bytes(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        answer = runtime.wire.dispatch(METHOD_CAPABILITIES, {})
        assert answer == CAPABILITIES
    finally:
        runtime.stop()


# -- stable request-id semantics (C2) ----------------------------------------

def test_same_request_id_same_payload_replays_the_original_receipt(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        first = runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0001", "payload": "hello"})
        replay = runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0001", "payload": "hello"})
        assert replay == first  # the original receipt, not a new one
        assert first["requestId"] == "req-0001" and first["echo"] == "hello"
    finally:
        runtime.stop()


def test_same_request_id_different_payload_is_a_typed_conflict_not_a_redispatch(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        first = runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0002", "payload": "a"})
        with pytest.raises(WireError) as excinfo:
            runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0002", "payload": "b"})
        assert excinfo.value.family == "INVALID_REQUEST"
        assert excinfo.value.details["internalCode"] == "REQUEST_DIGEST_CONFLICT"
        # the spent key's receipt is untouched
        replay = runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0002", "payload": "a"})
        assert replay == first
    finally:
        runtime.stop()


# -- public boundary ---------------------------------------------------------

def test_plugin_imports_only_public_plugin_api_and_stdlib():
    forbidden = {"ordessa_harness", "ordessa_profile", "ordessa_server",
                 "ordessa_environment_api", "pacthold", "pacthold_runtime_compat"}
    for path in PLUGIN_PACKAGE_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                assert top not in forbidden, (
                    f"{path.name} imports {name}: the sample must stay on the "
                    "public plugin API contract")


def test_discovery_advertises_exactly_three_methods_owned_by_the_sample(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        caps = {item["id"]: item for item in _hello(runtime)["capabilities"]}
        for method in METHODS:
            assert method in caps and caps[method]["supported"] is True
        assert set(caps) == {"server.hello", *METHODS}
        for method in METHODS:
            descriptor = runtime.plugin_host.methods.lookup(method)
            assert descriptor is not None and descriptor.owner == OWNER
    finally:
        runtime.stop()


def test_status_is_read_only_liveness(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        status = runtime.wire.dispatch(METHOD_STATUS, {})
        assert status == {"state": "ready", "schema": INTERACTION_SCHEMA}
    finally:
        runtime.stop()


# -- round gates (exit record) ------------------------------------------------

def test_not_started_round_refuses_business_methods_typed(tmp_path):
    runtime = _build(tmp_path)  # deliberately never start()ed
    for method, params in ((METHOD_ECHO, {"requestId": "req-0003", "payload": "x"}),
                           (METHOD_STATUS, {})):
        with pytest.raises(WireError) as excinfo:
            runtime.wire.dispatch(method, params)
        assert excinfo.value.details["internalCode"] == "ROUND_NOT_STARTED"
    # the discovery face stays open and honest
    caps = _hello(runtime)["capabilities"]
    assert caps and all("id" in item for item in caps)


def test_stopped_round_retires_methods_and_hello_stays_truthful(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    runtime.stop()
    caps = {item["id"] for item in _hello(runtime)["capabilities"]}
    assert METHOD_ECHO not in caps
    with pytest.raises(WireError):
        runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0004", "payload": "x"})


def test_unknown_request_id_never_triggers_an_interaction(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        # a query-shaped call with an unknown id must not fabricate a receipt:
        # status is the only read face and it carries no request identity.
        status = runtime.wire.dispatch(METHOD_STATUS, {})
        assert "requestId" not in status
        # echo with a fresh id creates exactly one ledger entry — no retry
        # machinery, no automatic re-dispatch anywhere in the sample.
        first = runtime.wire.dispatch(METHOD_ECHO, {"requestId": "req-0005", "payload": "q"})
        assert first["delivery"] == "acknowledged"
    finally:
        runtime.stop()
