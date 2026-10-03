"""Public access + exit record for external sample #2 (static resource).

The sample composes through the Server's public seam only —
`ordessa_server.bootstrap.build_runtime` with an explicit `server_plugins`
selection — exactly as an outside deployment would. The assertions below
are the sample's public access and exit records
(lifecycle-evidence §SDK真实穿透与样例: external sample #2 is a static
resource package that installs without Server/Harness/Profile):

- discovery: `server.hello` advertises exactly the sample's two methods,
  owned by `ordessa.sample-static-resource`;
- round-trip: `sample.resources.list`/`sample.resources.get` return the
  frozen package content, pinned by sha256 against the packaged bytes;
- scope: nothing session/model/profile-like appears in this composition;
- exit: the not-started round refuses typed (`ROUND_NOT_STARTED`), and a
  stopped round retires both methods — `server.hello` stays answerable and
  honestly drops them.

`ordessa_server` is imported from the venv's editable install (the sample
distribution itself depends only on `ordessa-server-plugin-api`); see
README.md "Test dependencies".
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from server_plugin_api import WireError

from ordessa_server.bootstrap import build_runtime

from ordessa_sample_static_resource import (
    FROZEN_RESOURCES_SHA256,
    METHOD_GET,
    METHOD_LIST,
    PLUGIN_ID,
    SampleStaticResourcePlugin,
)
from ordessa_sample_static_resource.plugin import PACKAGE_ROOT

OWNER = PLUGIN_ID
METHODS = (METHOD_LIST, METHOD_GET)
PLUGIN_PACKAGE_DIR = PACKAGE_ROOT


def _build(tmp_path: Path):
    return build_runtime(
        tmp_path / "data", server_plugins=(SampleStaticResourcePlugin(),))


def _hello(runtime):
    return runtime.wire.dispatch("server.hello", {
        "clientVersions": ["static-resource-sample-test/1"],
        "clientPresentationSupports": [],
    })


def _capability_ids(runtime) -> set[str]:
    return {entry["id"] for entry in _hello(runtime)["capabilities"]}


# -- the round gate: a built-but-not-started composition refuses typed -------

def test_not_started_round_refuses_dispatch_and_hello_still_answers(tmp_path):
    runtime = _build(tmp_path)
    try:
        # The registry carries the rows (activate_all ran at composition), but
        # the round is closed: every business method refuses with the existing
        # wire family and the internal code in details — never a fake answer.
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch(METHOD_LIST, {})
        assert refused.value.family == "INVALID_REQUEST"
        assert refused.value.details.get("internalCode") == "ROUND_NOT_STARTED"
        with pytest.raises(WireError) as refused_get:
            runtime.wire.dispatch(METHOD_GET, {"id": "sample-wire-notes"})
        assert refused_get.value.details.get("internalCode") == "ROUND_NOT_STARTED"
        # Discovery never lies about the Server's existence.
        assert {METHOD_LIST, METHOD_GET} <= _capability_ids(runtime)
    finally:
        runtime.stop()


# -- discovery: two methods, one owner ---------------------------------------

def test_hello_advertises_both_methods_with_sample_owner(tmp_path):
    runtime = _build(tmp_path)
    try:
        runtime.start()
        capabilities = {entry["id"]: entry for entry in
                        _hello(runtime)["capabilities"]}
        for method in METHODS:
            assert method in capabilities
            assert capabilities[method]["supported"] is True
        # The owner is the sample plugin, read from the live dispatch registry.
        for method in METHODS:
            descriptor = runtime.plugin_host.methods.lookup(method)
            assert descriptor is not None
            assert descriptor.owner == OWNER
        active = runtime.plugin_host.active(PLUGIN_ID)
        assert active is not None
        assert active.descriptor.id == PLUGIN_ID
        assert active.descriptor.requires == ()
        assert active.registration.provided_ports == {}
    finally:
        runtime.stop()


# -- content round-trip: byte-pinned frozen document --------------------------

def test_list_and_get_round_trip_matches_frozen_bytes(tmp_path):
    raw = (PLUGIN_PACKAGE_DIR / "data" / "resources.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    # The packaged bytes are the pinned content, and the plugin pins the same
    # digest: the self-check and this test pin each other.
    assert digest == FROZEN_RESOURCES_SHA256
    frozen = json.loads(raw.decode("utf-8"))

    runtime = _build(tmp_path)
    try:
        runtime.start()
        listed = runtime.wire.dispatch(METHOD_LIST, {})
        assert listed["contentSha256"] == digest
        assert listed["schema"] == frozen["schema"]
        assert listed["items"] == frozen["resources"]

        for entry in frozen["resources"]:
            got = runtime.wire.dispatch(METHOD_GET, {"id": entry["id"]})
            assert got["contentSha256"] == digest
            assert got["resource"] == entry

        with pytest.raises(WireError) as missing:
            runtime.wire.dispatch(METHOD_GET, {"id": "no-such-resource"})
        assert missing.value.family == "NOT_FOUND"
    finally:
        runtime.stop()


# -- scope: no session/model/profile capability composes here -----------------

def test_composition_carries_no_session_model_profile_capability(tmp_path):
    runtime = _build(tmp_path)
    try:
        runtime.start()
        ids = _capability_ids(runtime)
        # The composition is the host plus exactly this sample.
        assert ids == {"server.hello", METHOD_LIST, METHOD_GET}
        forbidden_markers = (
            "session", "sessions", "model", "profile", "profiles",
            "harness", "chat", "agent", "environment",
        )
        for method_id in ids:
            for marker in forbidden_markers:
                assert marker not in method_id.lower()
        # No native execution identity is composed either.
        assert runtime.native_harness_id is None
        assert runtime.native_profile_id is None
    finally:
        runtime.stop()


# -- structural gate: the plugin imports only the public contract -------------

def test_plugin_imports_only_public_plugin_api_and_stdlib():
    allowed = {"__future__", "hashlib", "json", "pathlib", "typing",
               "server_plugin_api",
               # the package's own intra-package imports (__init__ -> plugin)
               "ordessa_sample_static_resource"}
    forbidden = ("ordessa_server", "ordessa_harness", "ordessa_profile",
                 "ordessa_agent", "ordessa_environment", "agent_box",
                 "harness", "profile", "environment")
    seen: set[str] = set()
    for source in sorted(PLUGIN_PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                seen.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                if node.module:
                    seen.add(node.module.split(".")[0])
    assert seen <= allowed, sorted(seen - allowed)
    for name in forbidden:
        assert name not in seen


# -- exit: a stopped round retires the methods, discovery stays honest --------

def test_stop_retires_methods_and_discovery_drops_them(tmp_path):
    runtime = _build(tmp_path)
    try:
        runtime.start()
        assert {METHOD_LIST, METHOD_GET} <= _capability_ids(runtime)
    finally:
        runtime.stop()

    # The rows retired with the round: typed refusal, not silence.
    with pytest.raises(WireError) as refused:
        runtime.wire.dispatch(METHOD_LIST, {})
    assert refused.value.family == "INVALID_REQUEST"
    assert "not a wire/1 method" in refused.value.message
    with pytest.raises(WireError) as refused_get:
        runtime.wire.dispatch(METHOD_GET, {"id": "sample-wire-notes"})
    assert refused_get.value.family == "INVALID_REQUEST"

    # Discovery stays answerable and honestly drops the retired rows.
    assert _capability_ids(runtime) == {"server.hello"}
