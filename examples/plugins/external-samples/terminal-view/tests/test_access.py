"""Public access + exit record for external sample #3 (T007-09/T009-07)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from ordessa_server_plugin_api import WireError

from ordessa_server.composition.runtime import build_runtime

from ordessa_sample_terminal import (
    CAPABILITIES,
    FROZEN_DIGEST,
    METHOD_CAPABILITIES,
    METHOD_OPEN,
    METHOD_READ,
    PLUGIN_ID,
    SampleTerminalPlugin,
)

PLUGIN_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "ordessa_sample_terminal"


def _build(tmp_path: Path):
    return build_runtime(tmp_path / "data", server_plugins=(SampleTerminalPlugin(),))


def test_capabilities_declare_the_non_chat_readonly_face():
    assert CAPABILITIES["viewKind"] == "terminal-document"
    assert CAPABILITIES["interactionSchema"] == "sample-terminal/1"
    assert CAPABILITIES["requires"] == {"agent": False, "chat": False, "profile": False}
    assert CAPABILITIES["writable"] is False
    assert CAPABILITIES["reliableSubmission"] == "unsupported"
    assert "never silently downgraded" in CAPABILITIES["reliableSubmissionReason"]


def test_document_round_trip_is_read_only_and_sha256_anchored(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        opened = runtime.wire.dispatch(METHOD_OPEN, {"requestId": "req-0001"})
        assert opened["documentId"] == "doc-1"
        assert opened["contentSha256"] == FROZEN_DIGEST
        assert opened["readOnly"] is True
        read = runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        assert read["contentSha256"] == FROZEN_DIGEST
        assert read["readOnly"] is True
    finally:
        runtime.stop()


def test_counterexample_unknown_document_is_not_found_not_empty_success(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        with pytest.raises(WireError) as excinfo:
            runtime.wire.dispatch(METHOD_READ, {"id": "doc-404"})
        assert excinfo.value.family == "NOT_FOUND"
    finally:
        runtime.stop()


def test_counterexample_request_id_discipline_is_enforced(tmp_path):
    runtime = _build(tmp_path)
    runtime.start()
    try:
        with pytest.raises(WireError):
            runtime.wire.dispatch(METHOD_OPEN, {"requestId": "short"})
    finally:
        runtime.stop()


def test_plugin_imports_only_public_plugin_api_and_stdlib():
    forbidden = {"ordessa_harness", "ordessa_profile", "ordessa_server",
                 "ordessa_execution_api.environment", "pacthold", "pacthold_runtime_compat"}
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
                assert top not in forbidden, f"{path.name} imports {name}"


def test_discovery_advertises_exactly_three_methods_and_round_gates(tmp_path):
    runtime = _build(tmp_path)
    hello = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
    # not started: business methods refuse typed; hello stays open
    with pytest.raises(WireError):
        runtime.wire.dispatch(METHOD_CAPABILITIES, {})
    runtime.start()
    try:
        caps = {item["id"] for item in runtime.wire.dispatch("server.hello", hello)["capabilities"]}
        assert set(caps) == {"server.hello", METHOD_OPEN, METHOD_READ, METHOD_CAPABILITIES}
        descriptor = runtime.plugin_host.methods.lookup(METHOD_READ)
        assert descriptor is not None and descriptor.owner == PLUGIN_ID
    finally:
        runtime.stop()
    caps_after = {item["id"] for item in runtime.wire.dispatch("server.hello", hello)["capabilities"]}
    assert METHOD_READ not in caps_after
