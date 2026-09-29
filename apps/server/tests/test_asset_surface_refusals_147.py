"""Order 147: the wire's asset surface must not lie about who broke, and must
not read the same object once per row.

`AUD-B-037` found five copies of one fallback that wrote
`INVALID_REQUEST: <ClassName>: <str(exc)>`. Two consequences, both measured here
rather than argued: a Server-side fault is reported as the client's mistake, and
`str(PermissionError)` carries absolute paths - the data root among them.
`AUD-B-040` is the read path: `profiles.list` walked the model resolution per
row, so 40 rows over one provider issued 80 `objects.read`s (each of which
re-hashes the whole object) where 41 are enough.

Everything is driven through the real wire method entry with
`raise_server_exceptions=False`; nothing calls `_asset_refusal` directly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

import _w1_seed

REPO = Path(__file__).resolve().parents[3]
ABSOLUTE_PATH = re.compile(r"(^|[\s:'\"])/[A-Za-z0-9._/-]{2,}")

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.transport.http import create_app
from ordessa_server_compat import core_wire as handlers_module
from ordessa_server.wire.errors import FAMILIES, family_for


def _registry() -> HarnessRegistry:
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True},
        model_control_id="model", control_options={"model": ()}))
    return registry


class Api:
    """The smallest wire client that keeps every gate on the real HTTP path."""

    def __init__(self, client, headers):
        self.client = client
        self.headers = headers

    def call(self, method, params):
        return self.client.post(f"/wire/v1/{method}", headers=self.headers, json={
            "jsonrpc": "2.0", "id": method, "method": method, "params": params}).json()

    def ok(self, method, params):
        body = self.call(method, params)
        assert "result" in body, (method, body)
        return body["result"]


@pytest.fixture
def server(tmp_path):
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(harnesses=_registry()))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, Api(client, {"Authorization": f"Bearer {runtime.token}"})


def source_dir(tmp_path, *, content="{\"schema_version\": 1, \"entries\": []}"):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "index.json").write_text(content, encoding="utf-8")
    return source


# -- G1/G2/G3: a Server fault answers as one ---------------------------------

def test_an_unreadable_index_is_a_server_fault_not_a_bad_request(server, tmp_path):
    """⑤: `index.read_bytes()` on a file with mode 000 raises `PermissionError`."""
    _runtime, api = server
    source = source_dir(tmp_path)
    os.chmod(source / "index.json", 0o000)
    try:
        error = api.call("assets.syncCatalog", {
            "requestId": "p147-read", "sourceId": "community", "sourcePath": str(source)})["error"]
    finally:
        os.chmod(source / "index.json", 0o600)
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] == "PermissionError", error
    assert not ABSOLUTE_PATH.search(error["message"]), error["message"]


def test_an_unwritable_snapshot_dir_is_the_same_shape(server, tmp_path):
    """⑥: `staging.write_bytes` / `os.replace` raise an `OSError`."""
    runtime, api = server
    source = source_dir(tmp_path)
    # The store creates its root lazily, so the unwritable directory has to
    # exist before the write is what fails (that is failure ⑥, not ⑤).
    runtime.plugin_host.provided_port('compat.handlers').catalogs.root.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime.plugin_host.provided_port('compat.handlers').catalogs.root, 0o500)
    try:
        error = api.call("assets.syncCatalog", {
            "requestId": "p147-write", "sourceId": "community", "sourcePath": str(source)})["error"]
    finally:
        os.chmod(runtime.plugin_host.provided_port('compat.handlers').catalogs.root, 0o700)
    assert error["code"] == "UNAVAILABLE", error
    assert error["details"]["internalCode"] in {
        "PermissionError", "OSError", "FileExistsError", "IsADirectoryError"}, error
    assert not ABSOLUTE_PATH.search(error["message"]), error["message"]


def test_counter_example_the_old_fallback_blamed_the_client_and_leaked_the_path(
        server, tmp_path, monkeypatch):
    """The defect, restored verbatim, so the two gates above have teeth."""
    _runtime, api = server
    source = source_dir(tmp_path)
    os.chmod(source / "index.json", 0o000)

    def old_fallback(exc, **_injected):
        return handlers_module.WireError(
            "INVALID_REQUEST",
            f"{getattr(exc, 'code', type(exc).__name__)}: {getattr(exc, 'message', exc)}")

    try:
        monkeypatch.setattr(handlers_module, "_asset_refusal", old_fallback)
        error = api.call("assets.syncCatalog", {
            "requestId": "p147-old", "sourceId": "community", "sourcePath": str(source)})["error"]
        assert error["code"] == "INVALID_REQUEST", error
        assert "PermissionError" in error["message"], error
        assert ABSOLUTE_PATH.search(error["message"]), (
            "the old shape leaked no path, so it is not the defect being gated")
        assert "internalCode" not in error.get("details", {}), error
        monkeypatch.undo()
        after = api.call("assets.syncCatalog", {
            "requestId": "p147-new", "sourceId": "community", "sourcePath": str(source)})["error"]
        assert after["code"] == "UNAVAILABLE", after
    finally:
        os.chmod(source / "index.json", 0o600)


# -- G4: the domain codes keep their words ----------------------------------

def test_a_missing_index_keeps_its_domain_code_and_wording_verbatim(server, tmp_path):
    _runtime, api = server
    source = tmp_path / "empty-source"
    source.mkdir()
    error = api.call("assets.syncCatalog", {
        "requestId": "p147-missing", "sourceId": "community", "sourcePath": str(source)})["error"]
    assert error["code"] == "INVALID_REQUEST", error
    assert error["message"] == "CATALOG_SOURCE_MISSING: the source has no index.json", error
    assert error["details"]["internalCode"] == "CATALOG_SOURCE_MISSING", error


def test_a_malformed_index_keeps_its_domain_code_and_wording(server, tmp_path):
    _runtime, api = server
    source = source_dir(tmp_path, content="{ nope")
    error = api.call("assets.syncCatalog", {
        "requestId": "p147-malformed", "sourceId": "community", "sourcePath": str(source)})["error"]
    assert error["code"] == "INVALID_REQUEST", error
    assert error["message"].startswith("CATALOG_INVALID: "), error
    assert error["details"]["internalCode"] == "CATALOG_INVALID", error


def test_the_catalog_codes_are_registered_and_no_family_was_invented(tmp_path):
    """Same predicates, now answered through the composition (T014-S2a/R).

    The four CATALOG rows live with the plugin that raises them and reach the
    wire table as a `wire.error-families` contribution, so "registered" means
    "registered in an active composition": the gate composes the default
    product and asks the identical question against THAT host's aggregate —
    S2a-R made the contributed half per-composition state, and the golden
    answer must be proven where the behaviour lives, not through a process
    global. Nothing was softened - the unregistered fall-through and the
    closed twelve-family set are asserted unchanged.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        composed = runtime.plugin_host.wire_error_families.family_for
        # The same codes through the path the compat surface actually uses: the
        # resolver the composition INJECTED into its handler (T014-S2c), which
        # replaces the helper that re-derived families from compat's own
        # payload.
        injected = runtime.plugin_host.provided_port("compat.handlers")._family_for
        for code in ("CATALOG_INVALID", "CATALOG_SOURCE_MISSING",
                     "CATALOG_ORIGIN_MISSING", "CATALOG_ENTRY_UNKNOWN"):
            assert composed(code) == "INVALID_REQUEST", code
            assert composed(code) == injected(code), code
        assert composed("SOMETHING_UNREGISTERED") == "UNAVAILABLE"
        assert injected("SOMETHING_UNREGISTERED") == "UNAVAILABLE"
    finally:
        runtime.stop()
    assert len(FAMILIES) == 12, "147 must not add a family to make its point"
    assert "INTERNAL" not in FAMILIES, (
        "the order's wording offered UNAVAILABLE/INTERNAL; the locked family set has "
        "no INTERNAL, so a Server fault answers UNAVAILABLE - recorded in the report")


def test_the_injected_resolver_covers_every_plugin_row(tmp_path):
    """T014-S2c closes S2a-R's registered residual.

    The compat surface used to resolve families out of its OWN contribution
    payload, which was legal but left it blind to the ten rows workspace
    contributes: a workspace code reaching a compat conversion site answered
    the static fall-through. That helper (`_compat_family`) is deleted, and
    compat now converts through a callable the composition injected.

    Predicates, all on a real composed product:
    - every plugin-owned code (compat's rows plus workspace's — the 44 the
      composition carries since T014-S2b moved the two SSH connector rows
      to the plugin that composes the connector) answers the composition's
      own family through the injected path, byte-identical to the aggregate
      it replaces;
    - the rows the old helper could NOT answer (workspace's) are named and
      asserted, so the closure is measured rather than declared;
    - the injected thing is a callable, not the aggregate: compat holds no
      table it could read or write.
    """
    from ordessa_server_compat.error_families import COMPAT_ERROR_FAMILIES
    from ordessa_workspace.error_families import WORKSPACE_ERROR_FAMILIES

    runtime = build_runtime(tmp_path / "data")
    try:
        aggregate = runtime.plugin_host.wire_error_families
        handlers = runtime.plugin_host.provided_port("compat.handlers")
        injected = handlers._family_for
        assert callable(handlers._family_resolver)
        assert not isinstance(handlers._family_resolver, type(aggregate)), (
            "compat was handed the aggregate object; it must receive a callable")

        plugin_owned = sorted(set(COMPAT_ERROR_FAMILIES) | set(WORKSPACE_ERROR_FAMILIES))
        assert len(plugin_owned) == 44, (
            f"the composition carries {len(aggregate.contributed_families())} "
            f"contributed rows; this gate expects the 44 compat+workspace codes")
        assert len(set(COMPAT_ERROR_FAMILIES)) == 32
        assert set(WORKSPACE_ERROR_FAMILIES) <= set(aggregate.contributed_families())
        for code in plugin_owned:
            assert injected(code) == aggregate.family_for(code), code

        # The rows the old payload-only helper answered UNAVAILABLE: they now
        # resolve to the family their owning plugin published.
        assert injected("LOCAL_PATH_MISSING") == "NOT_FOUND"
        assert injected("ENVIRONMENT_INVALID") == "INVALID_REQUEST"
        assert injected("LOCAL_SANDBOX_UNAVAILABLE") == "UNAVAILABLE"
        # Compat's own rows and the host's static rows keep their answers.
        assert injected("CATALOG_INVALID") == "INVALID_REQUEST"
        assert injected("SESSION_NOT_FOUND") == "NOT_FOUND"
        assert injected("REQUEST_INVALID") == "INVALID_REQUEST"
        assert injected("SOMETHING_UNREGISTERED") == "UNAVAILABLE"
    finally:
        runtime.stop()


def test_an_uninjected_handler_falls_back_to_its_own_rows(tmp_path):
    """Counterexample for the gate above: the composition is what closes the gap.

    A handler stood up without the injected resolver is exactly what the S2a-R
    compromise was — it sees its own published rows and the static table, and
    nothing of workspace's. If this case ever answered `LOCAL_PATH_MISSING` as
    `NOT_FOUND`, the two paths would have collapsed into one and the injection
    would be doing nothing.
    """
    from ordessa_server_compat.core_wire import CoreWireHandlers

    bare = CoreWireHandlers(
        profiles=None, sessions=None, queue=None, approvals=None,
        harnesses=None, objects=None, execution=None, codec=None)
    assert bare._family_for("CATALOG_INVALID") == "INVALID_REQUEST"
    assert bare._family_for("REQUEST_INVALID") == "INVALID_REQUEST"
    assert bare._family_for("LOCAL_PATH_MISSING") == "UNAVAILABLE"
    assert bare._family_for("ENVIRONMENT_INVALID") == "UNAVAILABLE"


def test_the_five_copies_are_replaced_by_one_path():
    source = (REPO / "plugins/server-compat/src/ordessa_server_compat/core_wire.py").read_text(encoding="utf-8")
    assert source.count("getattr(refusal") == 0
    # The one path now takes the composition's resolver as an argument
    # (T014-S2c); the count is the same predicate with the same five sites.
    assert source.count(
        "raise _asset_refusal(refusal, family_lookup=self._family_for) from refusal") == 5


# -- G5b: the read path is bounded -----------------------------------------

class _CountingObjects:
    def __init__(self, inner):
        self.inner = inner
        self.reads = 0
        self.bytes = 0

    def read(self, digest):
        self.reads += 1
        payload = self.inner.read(digest)
        self.bytes += len(payload)
        return payload


def _forty_profiles(api, runtime, models=500):
    # AR-1/W-1：providerModels.create wire 面已退役，摆桌子改同链服务直调。
    created = _w1_seed.provider_models_create(
        runtime, "p147-provider", {
            "requestId": "p147-provider", "displayName": "One provider", "harness": "alpha",
            "provider": "opaque", "credentialId": None, "configuration": [],
            "models": [{"modelId": f"model-{index}", "displayName": f"M{index}",
                        "availability": "unknown", "unavailableReason": None}
                       for index in range(models)]})["providerModel"]
    # AR-1/W-1：造数是摆桌子，改仓库层 Python 直调（wire 面已退役）。
    repository = runtime.plugin_host.provided_port("product.repository")
    for index in range(40):
        status, body = repository.profiles.create(
            key=f"p147-profile-{index}", request_digest=f"p147-profile-{index}",
            name=f"role-{index}", harness_type="alpha",
            config_digest=f"p147-profile-{index}", credential_id=None)
        profile = {"id": body["profile_id"], "version": 1}
        _w1_seed.profiles_update_config(
            runtime, f"p147-config-{index}", profile_id=profile["id"],
            expected_version=profile["version"],
            values=[{"controlId": "model", "value": {
                "providerId": created["id"], "modelId": f"model-{index}"}}])
    return created["id"]


def _counted_list(server):
    runtime, api = server
    _forty_profiles(api, runtime)
    counter = _CountingObjects(runtime.plugin_host.provided_port('compat.handlers').objects)
    runtime.plugin_host.provided_port('compat.handlers').objects = counter
    try:
        listed = api.ok("profiles.list", {"includeArchived": False})
    finally:
        runtime.plugin_host.provided_port('compat.handlers').objects = counter.inner
    assert len(listed["items"]) == 40, len(listed["items"])
    return listed, counter


def test_forty_rows_read_the_directory_once_per_object_not_once_per_row(server):
    listed, counter = _counted_list(server)
    assert [item["sendability"]["state"] for item in listed["items"]] == ["ready"] * 40, \
        [item["sendability"] for item in listed["items"]][:2]
    assert counter.reads <= 41, (
        f"{counter.reads} object reads for 40 rows - the per-call memo is not holding")
    assert counter.reads >= 40, counter.reads


def test_counter_example_bypassing_the_memo_goes_back_to_eighty_reads(
        server, monkeypatch):
    """The bound is what is asserted, so deleting the memo must break it."""
    runtime, api = server
    _forty_profiles(api, runtime)
    def uncached_read(self, digest):
        return self._objects.read(digest)

    def uncached_parsed(self, digest):
        return json.loads(self.read(digest))

    def uncached_index(self, digest, *, section, field):
        return {str(item[field]): item
                for item in (self.parsed(digest).get(section) or []) if field in item}

    monkeypatch.setattr(handlers_module._CallReader, "read", uncached_read)
    monkeypatch.setattr(handlers_module._CallReader, "parsed", uncached_parsed)
    monkeypatch.setattr(handlers_module._CallReader, "index", uncached_index)
    counter = _CountingObjects(runtime.plugin_host.provided_port('compat.handlers').objects)
    runtime.plugin_host.provided_port('compat.handlers').objects = counter
    try:
        api.ok("profiles.list", {"includeArchived": False})
    finally:
        runtime.plugin_host.provided_port('compat.handlers').objects = counter.inner
    assert counter.reads >= 80, counter.reads


def test_a_memoised_object_is_the_bytes_a_cold_read_returns(server):
    """Caching may not weaken the integrity check: the digest *is* the argument."""
    runtime, _api = server
    digest = runtime.objects.publish(b'{"models": []}').digest
    reader = handlers_module._CallReader(runtime.objects)
    assert reader.read(digest) == runtime.objects.read(digest)
    assert reader.read(digest) == reader.read(digest)
    assert reader.parsed(digest) == {"models": []}
    assert reader.index(digest, section="models", field="modelId") == {}


def test_a_second_call_starts_empty(server):
    """The memo lives for one wire call; nothing is served from a previous one."""
    runtime, _api = server
    digest = runtime.objects.publish(b'{"models": []}').digest
    counter = _CountingObjects(runtime.objects)
    first = handlers_module._CallReader(counter)
    second = handlers_module._CallReader(counter)
    assert first.read(digest) == second.read(digest)
    assert counter.reads == 2, counter.reads


#: Every site `AUD-B-037` counted, with the store method each one wraps. The
#: five were *identical* text, so a gate that exercises one of them proves
#: nothing about the other four - this covers all five behaviourally.
FIVE_SITES = (
    ("assets.syncCatalog", "catalogs", "sync"),
    ("assets.installFromCatalog", "catalogs", "install_entry"),
    ("assets.publishSkill", "skill_assets", "install"),
    ("assets.publishMcp", "mcp_assets", "install"),
    ("assets.publishPlugin", "plugin_assets", "install"),
)

#: What a real `OSError` carries: `str(PermissionError(13, ..., filename))` is
#: "...: '/the/absolute/path'", which is the leak this order exists to stop.
HOST_PATH = "/home/operator/.agentbox/data-root/assets/index.json"


def _params_for(method, tmp_path, runtime):
    if method == "assets.syncCatalog":
        return {"requestId": "p147-five-sync", "sourceId": "community",
                "sourcePath": str(source_dir(tmp_path))}
    if method == "assets.installFromCatalog":
        return {"requestId": "p147-five-install", "sourceId": "community",
                "entryName": "my-skill", "revision": 1}
    if method == "assets.publishMcp":
        return {"requestId": "p147-five-mcp", "assetId": "calendar", "revision": 1,
                "definition": {"name": "calendar",
                               "transport": {"stdio": {"command": "/bin/calendar"}}}}
    return {"requestId": f"p147-five-{method.split('.')[-1]}", "assetId": "my-skill",
            "revision": 1, "sourcePath": str(tmp_path / "whatever")}


@pytest.mark.parametrize("method, attribute, function", FIVE_SITES)
def test_all_five_sites_answer_a_server_fault_the_same_way(
        server, tmp_path, monkeypatch, method, attribute, function):
    runtime, api = server
    owner = getattr(runtime.plugin_host.provided_port('compat.handlers'), attribute)
    assert owner is not None, (
        f"{attribute} is not composed in this tree; the gate would be vacuous")
    if method == "assets.installFromCatalog":
        api.ok("assets.syncCatalog", _params_for("assets.syncCatalog", tmp_path, runtime))

    def failing(*_args, **_kwargs):
        raise OSError(13, "Permission denied", HOST_PATH)

    monkeypatch.setattr(type(owner), function, failing)
    error = api.call(method, _params_for(method, tmp_path, runtime))["error"]
    assert error["code"] == "UNAVAILABLE", (method, error)
    # `OSError(13, ...)` is auto-promoted by CPython; the type name is the fact.
    assert error["details"]["internalCode"] == "PermissionError", (method, error)
    assert HOST_PATH not in error["message"], (method, error)
    assert not ABSOLUTE_PATH.search(error["message"]), (method, error)
    assert error["details"]["retryable"] is True, (method, error)
