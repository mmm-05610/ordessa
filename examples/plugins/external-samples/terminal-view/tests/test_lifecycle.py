"""Document lifecycle and exit legs for external sample #3 (terminal-view).

Complements test_access.py (kept intact, its six tests unchanged) with the
lifecycle half of the sample's public record:

- open/read semantics over the frozen document (stable receipt per
  requestId, byte-exact body, sha256 recomputed by the test, typed
  NOT_FOUND, requestId bounds, shape refusals);
- round gates in both directions (not-started round refuses typed; stop
  retires the methods);
- the three exit legs: stop unregisters the methods, hello stays honest,
  and plugin calls write nothing under the data root;
- the honest gap: the sample is a counting plugin with no replay ledger,
  and its counters are in-memory instance state, not durable. The tests
  below pin those facts instead of inventing idempotency the sample does
  not declare.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from server_plugin_api import WireError

from ordessa_server.composition.runtime import build_runtime

from ordessa_sample_terminal import (
    FROZEN_DIGEST,
    METHOD_CAPABILITIES,
    METHOD_OPEN,
    METHOD_READ,
    SampleTerminalPlugin,
)

# The frozen body is anchored byte-for-byte from the test side (not echoed
# back from the plugin) so any change to the sample's document is a visible
# contract change, never a tautology.
EXPECTED_DOCUMENT = b"line 1: a frozen document body\nline 2: read-only surface\n"
BUSINESS_METHODS = (METHOD_OPEN, METHOD_READ, METHOD_CAPABILITIES)
HELLO_PARAMS = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}


def _build(tmp_path: Path, plugin: SampleTerminalPlugin | None = None):
    return build_runtime(
        tmp_path / "data",
        server_plugins=(plugin if plugin is not None else SampleTerminalPlugin(),),
    )


def _hello(runtime) -> dict:
    return runtime.wire.dispatch("server.hello", HELLO_PARAMS)


def _snapshot(root: Path) -> dict[str, str]:
    """Content hashes of every file under the data root (the zero-write probe)."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- document lifecycle: open/read over the frozen document -------------------

def test_open_replays_the_same_receipt_for_the_same_request_id(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        first = runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        replay = runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        assert replay == first
        assert first == {
            "documentId": "doc-1",
            "contentSha256": FROZEN_DIGEST,
            "readOnly": True,
            "viewKind": "terminal-document",
        }
    finally:
        runtime.stop()


def test_open_is_counting_not_deduping_and_that_gap_is_pinned(tmp_path):
    plugin = SampleTerminalPlugin()
    runtime = _build(tmp_path, plugin)
    runtime.start()
    try:
        runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        # Honest pin of the sample's current semantics: there is no replay
        # ledger. The same requestId is served and counted twice; the stable
        # receipt comes from the frozen answer, not from de-duplication.
        assert plugin._open_count == 2
    finally:
        runtime.stop()


def test_read_round_trip_recomputes_sha256_over_the_returned_bytes(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        opened = runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        read = runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        body = read["document"].encode("utf-8")
        assert hashlib.sha256(body).hexdigest() == read["contentSha256"]
        assert read["contentSha256"] == opened["contentSha256"] == FROZEN_DIGEST
    finally:
        runtime.stop()


def test_read_returns_the_frozen_bytes_exactly(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        read = runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        assert read["document"].encode("utf-8") == EXPECTED_DOCUMENT
        assert hashlib.sha256(EXPECTED_DOCUMENT).hexdigest() == FROZEN_DIGEST
        assert read["readOnly"] is True
        # exactly the read face: no index/revisions/preview keys invented
        assert set(read) == {"document", "contentSha256", "readOnly"}
    finally:
        runtime.stop()


def test_unknown_ids_are_typed_not_found_and_never_an_empty_document(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        for document_id in ("doc-2", "DOC-1", "", "doc-1 "):
            with pytest.raises(WireError) as excinfo:
                runtime.wire.dispatch(METHOD_READ, {"id": document_id})
            assert excinfo.value.family == "NOT_FOUND", document_id
    finally:
        runtime.stop()


def test_read_without_id_is_a_missing_param_refusal_not_an_empty_document(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        with pytest.raises(WireError) as excinfo:
            runtime.wire.dispatch(METHOD_READ, {})
        assert excinfo.value.family == "INVALID_REQUEST"
        assert "missing" in excinfo.value.message and "id" in excinfo.value.message
    finally:
        runtime.stop()


def test_open_request_id_length_bounds_are_inclusive_at_8_and_128(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        assert runtime.wire.dispatch(METHOD_OPEN, {"requestId": "a" * 8})["documentId"] == "doc-1"
        assert runtime.wire.dispatch(METHOD_OPEN, {"requestId": "b" * 128})["documentId"] == "doc-1"
        for too_short_or_long in ("c" * 7, "d" * 129):
            with pytest.raises(WireError) as excinfo:
                runtime.wire.dispatch(METHOD_OPEN, {"requestId": too_short_or_long})
            assert excinfo.value.family == "INVALID_REQUEST"
    finally:
        runtime.stop()


def test_open_rejects_non_string_request_id_without_opening_anything(tmp_path):
    plugin = SampleTerminalPlugin()
    runtime = _build(tmp_path, plugin)
    runtime.start()
    try:
        for bad in (None, 12345678, b"req-0001", ["req-0001"], {"id": "req-0001"}):
            with pytest.raises(WireError) as excinfo:
                runtime.wire.dispatch(METHOD_OPEN, {"requestId": bad})
            assert excinfo.value.family == "INVALID_REQUEST"
        assert plugin._open_count == 0
    finally:
        runtime.stop()


def test_extra_params_are_refused_instead_of_ignored(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        cases = (
            (METHOD_OPEN, {"requestId": "req-0001", "force": True}),
            (METHOD_READ, {"id": "doc-1", "preview": True}),
            (METHOD_CAPABILITIES, {"depth": 1}),
        )
        for method, params in cases:
            with pytest.raises(WireError) as excinfo:
                runtime.wire.dispatch(method, params)
            assert excinfo.value.family == "INVALID_REQUEST"
            assert "unexpected" in excinfo.value.message
    finally:
        runtime.stop()


# -- round gates: not-started refuses typed, stop retires ---------------------

def test_not_started_round_refuses_all_business_methods_with_the_typed_gate(tmp_path):
    runtime = _build(tmp_path)  # deliberately never started
    for method, params in (
        (METHOD_OPEN, {"requestId": "req-0001"}),
        (METHOD_READ, {"id": "doc-1"}),
        (METHOD_CAPABILITIES, {}),
    ):
        with pytest.raises(WireError) as excinfo:
            runtime.wire.dispatch(method, params)
        assert excinfo.value.family == "INVALID_REQUEST"
        assert excinfo.value.details.get("internalCode") == "ROUND_NOT_STARTED"
    # the discovery face stays open and honest even with no live round
    caps = _hello(runtime)["capabilities"]
    assert {item["id"] for item in caps} >= {"server.hello", *BUSINESS_METHODS}


def test_stop_retires_the_three_methods_from_registry_and_discovery(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    for method in BUSINESS_METHODS:
        descriptor = runtime.plugin_host.methods.lookup(method)
        assert descriptor is not None and descriptor.owner == "ordessa.sample-terminal"
    runtime.stop()
    for method in BUSINESS_METHODS:
        assert runtime.plugin_host.methods.lookup(method) is None
    assert set(runtime.plugin_host.methods.method_ids()) == {"server.hello"}
    caps = {item["id"] for item in _hello(runtime)["capabilities"]}
    assert caps == {"server.hello"}
    with pytest.raises(WireError) as excinfo:
        runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
    assert excinfo.value.family == "INVALID_REQUEST"


def test_restart_re_registers_the_methods_and_serves_the_document_again(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    runtime.stop()
    runtime.start()
    try:
        assert runtime.plugin_host.methods.lookup(METHOD_READ) is not None
        read = runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        assert read["contentSha256"] == FROZEN_DIGEST
    finally:
        runtime.stop()


def test_idempotency_state_is_in_memory_so_a_fresh_instance_starts_from_zero(tmp_path):
    first = SampleTerminalPlugin()
    runtime = _build(tmp_path, first)
    runtime.start()
    opened = runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
    assert first._open_count == 1
    runtime.stop()
    # A fresh composition over the same data root carries no durable replay
    # ledger: the counter is zero and the same requestId is served again.
    second = SampleTerminalPlugin()
    restarted = _build(tmp_path, second)
    restarted.start()
    try:
        assert second._open_count == 0
        replay = restarted.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        assert replay == opened
    finally:
        restarted.stop()


# -- exit legs: zero data-root writes -----------------------------------------

def test_plugin_calls_leave_the_data_root_byte_identical(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        before = _snapshot(runtime.data_root)
        runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        runtime.wire.dispatch(METHOD_CAPABILITIES, {})
        after = _snapshot(runtime.data_root)
        assert after == before
    finally:
        runtime.stop()


def test_frozen_document_never_lands_in_the_data_root(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
    runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
    runtime.stop()
    for path in runtime.data_root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert EXPECTED_DOCUMENT not in data, f"document body written to {path}"
        assert FROZEN_DIGEST.encode() not in data, f"document digest written to {path}"
