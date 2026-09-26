"""Plugin-host boundary gates (batch 1).

The counterexamples the host boundary must survive, per
`docs/server-plugin-host-plan.md` §acceptance: bare host, one-plugin presence,
honest plugin absence, unload, duplicate registration, missing and cyclic
dependencies, activation rollback, disposal exactly once, host-owned auth and
error isolation, stream-route admission, and hello-vs-dispatch consistency.

Unit gates run against `ServerPluginHost` with contract-only fake plugins;
composition gates run through `build_runtime` + the real transport. A missing
fixture or zero collected tests would fail this file's own gate, so the
counterexample ids are enumerated below and each has a test.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from server_plugin_api import (
    SERVER_PLUGIN_API_VERSION,
    CyclicDependencyError,
    DependencyError,
    DuplicateMethodError,
    DuplicatePluginError,
    DuplicateStreamRouteError,
    InvalidDeclarationError,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)

from ordessa_server.bootstrap import build_runtime
from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
from ordessa_server.plugin_host.workspace_plugin import PLUGIN_ID as WORKSPACE_ID
from ordessa_server.plugin_host.workspace_plugin import WorkspaceServerPlugin
from ordessa_server.transport.http import create_app

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

WORKSPACE_METHODS = {
    "workspaces.browse", "workspaces.open", "workspaces.list",
    "workspaces.archive", "workspaces.gitStatus",
}


def _hello_caps(runtime) -> dict[str, dict]:
    result = runtime.wire.hello(HELLO)
    return {item["id"]: item for item in result["capabilities"]}


# -- contract-only fakes (test plugins; never shipped in the product) --------


class FakePlugin:
    """A configurable contract plugin for host-level counterexamples."""

    def __init__(self, plugin_id="fake.a", *, methods=(), routes=(), ports=None,
                 requires=(), raises=None, api_version=SERVER_PLUGIN_API_VERSION,
                 dispose_records=None, bad_owner=False, handler_overrides=None):
        self._descriptor = ServerPluginDescriptor(
            id=plugin_id, display_name=f"Fake {plugin_id}", version="1",
            api_version=api_version, requires=tuple(requires))
        self._methods = methods
        self._routes = routes
        self._ports = ports or {}
        self._raises = raises
        self._dispose_records = dispose_records
        self._bad_owner = bad_owner
        self._handler_overrides = handler_overrides or {}

    def descriptor(self) -> ServerPluginDescriptor:
        return self._descriptor

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        if self._raises is not None:
            raise self._raises
        built = []
        for method_id, required in self._methods:
            built.append(ServerMethodDescriptor(
                method_id=method_id, required_params=frozenset(required),
                optional_params=frozenset(),
                handler=self._handler_overrides.get(method_id)
                or (lambda params, _name=method_id: {"ok": _name}),
                owner=self._descriptor.id if not self._bad_owner else "someone.else",
            ))
        routes = tuple(StreamRouteDescriptor(
            route_id=route_id, resolver=lambda ref: None,
            owner=self._descriptor.id) for route_id in self._routes)
        return ServerPluginRegistration(
            methods=tuple(built), stream_routes=routes,
            provided_ports=dict(self._ports),
            disposal=(lambda: self._dispose_records.append(self._descriptor.id))
            if self._dispose_records is not None else None,
        )


class _Started:
    """Start a runtime for direct wire calls; always stop it once."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def __enter__(self):
        self.runtime.start()
        return self.runtime

    def __exit__(self, *exc):
        self.runtime.stop()
        return False


def _new_host() -> ServerPluginHost:
    return ServerPluginHost(methods=MethodRegistry(),
                            stream_routes=StreamRouteRegistry())


# -- bare host and one-plugin presence (composition level) -------------------


def test_bare_host_starts_serves_hello_and_shuts_down_cleanly(tmp_path):
    runtime = build_runtime(tmp_path / "data", server_plugins=[])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            live = client.get("/live")
            assert live.status_code == 200 and live.json() == {"status": "alive"}
            caps = _hello_caps(runtime)
            assert list(caps) == ["server.hello"], caps
            assert caps["server.hello"]["supported"] is True
            assert runtime.wire.dispatch("server.hello", HELLO)["capabilities"]
    finally:
        runtime.stop()
    assert runtime.started is False


def test_bare_host_refuses_business_methods_typed_and_stays_authenticated(tmp_path):
    runtime = build_runtime(tmp_path / "data", server_plugins=[])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            headers = {"Authorization": f"Bearer {runtime.token}"}
            for method in ("workspaces.open", "sessions.list", "profiles.list"):
                response = client.post(f"/wire/v1/{method}", headers=headers, json={
                    "jsonrpc": "2.0", "id": "1", "method": method, "params": {}})
                error = response.json()["error"]
                assert error["code"] == "INVALID_REQUEST", (method, error)
                assert "is not a wire/1 method" in error["message"]
            # Host auth is not a plugin: an unauthenticated call to the one
            # advertised method is refused before any dispatch.
            naked = client.post("/wire/v1/server.hello", json={
                "jsonrpc": "2.0", "id": "1", "method": "server.hello", "params": HELLO})
            assert naked.status_code == 401
            assert naked.json()["error"]["code"] == "UNAUTHENTICATED"
    finally:
        runtime.stop()


def test_workspace_plugin_presence_and_honest_absence(tmp_path):
    """The absent/present pair on one real domain: the five methods exist only
    when the plugin is composed, and their support state follows readiness
    exactly as wire/1 always reported it."""
    from ordessa_server.workspaces.local_environment import LocalEnvironmentProvider

    bare = build_runtime(tmp_path / "bare", server_plugins=[])
    try:
        with _Started(bare):
            caps = _hello_caps(bare)
            assert not (WORKSPACE_METHODS & set(caps))
            with pytest.raises(Exception) as refused:
                bare.wire.dispatch("workspaces.list", {"includeArchived": False})
            assert "not a wire/1 method" in str(refused.value)
    except BaseException:
        bare.stop()
        raise

    # Sandbox unavailable on this host: declared, honestly not supported.
    closed = build_runtime(tmp_path / "ws-closed", server_plugins=[WorkspaceServerPlugin()])
    try:
        with _Started(closed):
            caps = _hello_caps(closed)
            assert WORKSPACE_METHODS <= set(caps), "declared while the plugin is active"
            assert all(caps[m] == {"id": m, "supported": False,
                                   "reason": "LOCAL_SANDBOX_UNAVAILABLE"}
                       for m in WORKSPACE_METHODS), caps
    except BaseException:
        closed.stop()
        raise

    workspace_only = build_runtime(
        tmp_path / "ws-open", server_plugins=[WorkspaceServerPlugin()],
        local_workspace_provider=LocalEnvironmentProvider(
            sandbox_probe=lambda: {"status": "available", "code": "binary_missing"}))
    try:
        with _Started(workspace_only):
            caps = _hello_caps(workspace_only)
            assert all(caps[m] == {"id": m, "supported": True} for m in WORKSPACE_METHODS)
            # The transitional adapter is not composed here: its methods are gone.
            assert "profiles.list" not in caps and "sessions.list" not in caps
            # The provided port is the live service; the read-only list answers.
            assert workspace_only.wire.workspaces is not None
            result = workspace_only.wire.dispatch("workspaces.list", {"includeArchived": False})
            assert result == {"items": [], "nextCursor": None}
    except BaseException:
        workspace_only.stop()
        raise


def test_default_composition_advertises_the_full_baseline_table(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    try:
        with _Started(runtime):
            caps = _hello_caps(runtime)
            assert WORKSPACE_METHODS <= set(caps)
            assert len(caps) == 67
            assert runtime.plugin_host.active_ids() == (WORKSPACE_ID, "ordessa.transition-core")
    except BaseException:
        runtime.stop()
        raise


# -- unload, disposal exactly once, isolation --------------------------------


def test_unload_removes_only_that_plugins_methods_and_disposes_exactly_once(tmp_path):
    records: list[str] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        WorkspaceServerPlugin(),
        "ordessa.transition-core",
        FakePlugin("fake.extra", methods=(("fake.ping", {"x"}),),
                   dispose_records=records),
    ])
    try:
        with _Started(runtime):
            assert "fake.ping" in _hello_caps(runtime)
            assert WORKSPACE_METHODS <= set(_hello_caps(runtime))
            runtime.plugin_host.deactivate("fake.extra")

            caps = _hello_caps(runtime)
            assert "fake.ping" not in caps
            assert WORKSPACE_METHODS <= set(caps), (
                "unrelated plugin methods must survive an unload")
            assert records == ["fake.extra"]
            runtime.plugin_host.deactivate(WORKSPACE_ID)
            assert not (WORKSPACE_METHODS & set(_hello_caps(runtime)))
            # The adapter (still active) keeps its own methods.
            assert "profiles.list" in _hello_caps(runtime)
            assert records == ["fake.extra"], "deactivate must dispose its own plugin only"
            # The workspace resolution port is gone with its plugin: the remaining
            # adapter answers the workspace-dependent paths with a typed refusal.
            with pytest.raises(Exception) as refused:
                runtime.wire.dispatch("sessions.createAndSend", {
                    "requestId": "unloaded-1", "workspaceId": "ws_x", "profileId": "p_x",
                    "message": {"text": "hi", "attachments": []}, "overrides": []})
            assert "workspace resolution is not composed" in str(refused.value)
    finally:
        runtime.stop()


def test_shutdown_disposes_each_activated_plugin_exactly_once(tmp_path):
    records: list[str] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        FakePlugin("fake.one", dispose_records=records),
        FakePlugin("fake.two", dispose_records=records),
    ])
    runtime.stop()
    assert sorted(records) == ["fake.one", "fake.two"]
    runtime.stop()  # a second stop must not dispose anyone again
    assert sorted(records) == ["fake.one", "fake.two"]


# -- startup refusals: duplicates, dependencies, illegal declarations ---------


def test_duplicate_method_registration_refuses_startup():
    host = _new_host()
    host.activate(FakePlugin("fake.one", methods=(("fake.dup", set()),)))
    with pytest.raises(DuplicateMethodError):
        host.activate(FakePlugin("fake.two", methods=(("fake.dup", set()),)))


def test_duplicate_plugin_id_refuses_startup():
    host = _new_host()
    host.activate(FakePlugin("fake.same"))
    with pytest.raises(DuplicatePluginError):
        host.activate(FakePlugin("fake.same"))


def test_duplicate_stream_route_refuses_startup():
    host = _new_host()
    host.activate(FakePlugin("fake.one", routes=("acp-channel",)))
    with pytest.raises(DuplicateStreamRouteError):
        host.activate(FakePlugin("fake.two", routes=("acp-channel",)))


def test_missing_dependency_refuses_startup():
    host = _new_host()
    with pytest.raises(DependencyError):
        host.activate(FakePlugin("fake.child", requires=("fake.absent",)))


def test_cyclic_dependency_refuses_startup():
    host = _new_host()
    with pytest.raises(CyclicDependencyError):
        host.activate_all([
            FakePlugin("fake.a", requires=("fake.b",), methods=(("fake.a.method", set()),)),
            FakePlugin("fake.b", requires=("fake.a",), methods=(("fake.b.method", set()),)),
        ])
    assert host.active_ids() == (), "a refused round must not leave partial activation"


def test_dependency_order_activates_the_dependency_first():
    host = _new_host()
    host.activate_all([
        FakePlugin("fake.child", requires=("fake.parent",),
                   methods=(("fake.child.method", set()),)),
        FakePlugin("fake.parent", methods=(("fake.parent.method", set()),)),
    ])
    assert host.active_ids() == ("fake.parent", "fake.child")
    assert "fake.child.method" in host.declared_shapes()


def test_illegal_declarations_are_startup_refusals():
    """Nothing illegal reaches the live table: the contract's descriptor
    constructor refuses a bad shape, the host refuses a mis-owned or
    version-mismatched declaration; in every case the activation is refused
    and nothing is staged."""
    host = _new_host()
    # A bad method id is refused by the contract's own constructor.
    with pytest.raises(ValueError):
        host.activate(FakePlugin("fake.bad", methods=(("Bad.Id", set()),)))
    # Params declared both required and optional are refused by the contract.
    from server_plugin_api import ServerMethodDescriptor as _SMD

    with pytest.raises(ValueError):
        _SMD(method_id="bad.overlap", required_params=frozenset({"x"}),
             optional_params=frozenset({"x"}), handler=lambda params: None,
             owner="fake.bad")
    # A descriptor claiming another owner is rejected by the host.
    with pytest.raises(InvalidDeclarationError):
        host.activate(FakePlugin("fake.bad", methods=(("bad.method", set()),), bad_owner=True))
    # An API version the host does not speak is refused, not loaded.
    with pytest.raises(InvalidDeclarationError):
        host.activate(FakePlugin("fake.bad", api_version=SERVER_PLUGIN_API_VERSION + 1))
    assert host.active_ids() == ()


def test_activation_failure_rolls_back_only_the_failing_plugin():
    class Boom(RuntimeError):
        pass

    host = _new_host()
    host.activate(FakePlugin("fake.stable", methods=(("fake.stable.method", set()),)))
    with pytest.raises(Boom):
        host.activate_all([
            FakePlugin("fake.boom", raises=Boom(), methods=(("fake.boom.method", set()),)),
        ])
    assert host.active_ids() == ("fake.stable",)
    assert host.methods.lookup("fake.boom.method") is None
    # A plugin that stages some methods and then fails rolls its own back.
    with pytest.raises(DuplicateMethodError):
        host.activate_all([
            FakePlugin("fake.clash", methods=(("fake.stable.method", set()),)),
        ])
    assert "fake.stable.method" in host.methods.handler_view()
    assert host.methods.lookup("fake.clash") is None


# -- dispatch, hello truth and error isolation -------------------------------


def test_hello_claims_match_reachable_handlers_exactly(tmp_path):
    for name, composition in (("bare", []), ("ws-only", [WorkspaceServerPlugin()]),
                              ("default", None)):
        runtime = build_runtime(tmp_path / f"hello-{name}", server_plugins=composition)
        try:
            with _Started(runtime):
                caps = _hello_caps(runtime)
                handlers = runtime.wire._handlers
                assert list(caps) == list(handlers)
                for method_id, handler in handlers.items():
                    assert callable(handler)
                # support state without a blocker rule is exactly "declared"
                no_rule = [m for m, entry in caps.items()
                           if entry.get("supported") is True and "reason" not in entry]
                assert "server.hello" in no_rule
        except BaseException:
            runtime.stop()
            raise


def test_error_isolation_one_plugins_crash_needs_nothing_from_another(tmp_path):
    class Exploding:
        """A handler that raises a bare exception - the wall must hold."""

        def __call__(self, params):
            raise ZeroDivisionError("plugin bug")

    runtime = build_runtime(tmp_path / "data", server_plugins=[
        WorkspaceServerPlugin(),
        FakePlugin("fake.bug", methods=(("fake.explode", set()),),
                   handler_overrides={"fake.explode": Exploding()}),
    ])
    try:
        with _Started(runtime):
            from ordessa_server.wire.errors import WireError

            with pytest.raises(WireError) as captured:
                runtime.wire.dispatch("fake.explode", {})
            assert captured.value.family == "UNAVAILABLE"
            assert captured.value.details["internalCode"] == "ZeroDivisionError"
            # An unrelated method still answers through the same registry.
            assert runtime.wire.dispatch("workspaces.list", {"includeArchived": False}) == {
                "items": [], "nextCursor": None}
    finally:
        runtime.stop()


def test_transition_adapter_declaration_covers_exactly_its_registered_rows():
    """The adapter's module-level declaration literal and its registry rows
    must agree: a row added to one and not the other is the order-097 hole."""
    from ordessa_server.plugin_host.transition_core import undeclared_adapter_methods

    assert undeclared_adapter_methods() == ()


def test_a_restart_re_activates_the_same_selection(tmp_path):
    """stop() disposes every plugin; the next start() must bring the whole
    wire surface back — a restart that silently shrinks to `server.hello` is
    a broken restart (the in-process restart cycle is product behaviour)."""
    runtime = build_runtime(tmp_path / "data")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        assert len(_hello_caps(runtime)) == 67
    assert runtime.plugin_host.active_ids() == (), "stop must have disposed everyone"
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        caps = _hello_caps(runtime)
        assert len(caps) == 67
        assert WORKSPACE_METHODS <= set(caps)
        assert "profiles.list" in caps


# -- review round 1: lifecycle holes the first batch missed ------------------


def test_activation_failure_releases_the_data_root_lock(tmp_path):
    """A plugin that fails to build must not keep the data-root lock: the same
    process composing the same root again is the retry path, and it must not
    die of DATA_ROOT_IN_USE."""
    class Boom(RuntimeError):
        pass

    root = tmp_path / "data"
    with pytest.raises(Boom):
        build_runtime(root, server_plugins=[FakePlugin("fake.boom", raises=Boom())])
    runtime = build_runtime(root)
    try:
        with _Started(runtime):
            assert len(_hello_caps(runtime)) == 67
    except BaseException:
        runtime.stop()
        raise


def test_reactivation_failure_in_start_releases_the_lock(tmp_path):
    """start()'s re-activation is inside its cleanup: if the second build of a
    flaky plugin fails, the lock is released, the runtime stays stopped, and
    the data root stays usable."""
    calls = {"n": 0}

    class FlakyPlugin:
        def descriptor(self):
            return ServerPluginDescriptor(id="fake.flaky", display_name="flaky", version="1")

        def build(self, context):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("SECOND_BUILD_BOOM")
            return ServerPluginRegistration()

    root = tmp_path / "data"
    runtime = build_runtime(root, server_plugins=[FlakyPlugin()])
    runtime.stop()
    with pytest.raises(RuntimeError, match="SECOND_BUILD_BOOM"):
        runtime.start()
    assert runtime.started is False
    fresh = build_runtime(root)
    try:
        with _Started(fresh):
            assert "server.hello" in _hello_caps(fresh)
    except BaseException:
        fresh.stop()
        raise


def test_a_declared_dependency_provides_ports_to_its_dependent():
    """`requires` is the access grant: the dependency's provided ports reach
    the dependent's context; a plugin that never declared the dependency
    cannot see them."""
    sentinel = object()
    captured: dict[str, object] = {}

    class _Consumer(FakePlugin):
        def build(self, context):
            captured[self.descriptor().id] = context.ports.get("fake.port")
            return super().build(context)

    host = _new_host()
    host.activate_all([
        FakePlugin("fake.provider", methods=(("fake.provide", set()),),
                   ports={"fake.port": sentinel}),
        _Consumer("fake.child", requires=("fake.provider",),
                  methods=(("fake.child.method", set()),)),
        _Consumer("fake.outsider", methods=(("fake.outsider.method", set()),)),
    ])
    assert captured["fake.child"] is sentinel, (
        "a declared dependency's port must reach its dependent's context")
    assert captured["fake.outsider"] is None, (
        "an undeclared plugin must not see another plugin's port")
    assert host.methods.lookup("fake.child.method") is not None


def test_method_conflict_disposes_the_plugin_that_already_built():
    """A plugin whose registration fails mid-staging has already built its
    resources: rollback removes its rows and its disposal runs exactly once."""
    records: list[str] = []
    host = _new_host()
    host.activate(FakePlugin("fake.stable", methods=(("fake.dup", set()),)))
    with pytest.raises(DuplicateMethodError):
        host.activate(FakePlugin("fake.clash", methods=(("fake.dup", set()),),
                                 dispose_records=records))
    assert records == ["fake.clash"]
    assert host.active_ids() == ("fake.stable",)
    assert host.methods.lookup("fake.dup").owner == "fake.stable"


def test_unload_refuses_while_a_declared_dependent_is_active():
    """Unloading a dependency under its dependent would orphan the dependent:
    the host refuses, names the dependents, and changes nothing; reverse
    order (dependent first) unloads cleanly, and shutdown's reverse order
    never trips the guard."""
    host = _new_host()
    host.activate_all([
        FakePlugin("fake.dep", methods=(("fake.dep.method", set()),)),
        FakePlugin("fake.child", requires=("fake.dep",),
                   methods=(("fake.child.method", set()),)),
    ])
    with pytest.raises(Exception) as refused:
        host.deactivate("fake.dep")
    assert "fake.child" in str(refused.value)
    assert host.is_active("fake.dep") and host.is_active("fake.child")
    host.deactivate("fake.child")
    host.deactivate("fake.dep")
    assert host.active_ids() == ()
    # shutdown's reverse activation order disposes dependents first.
    records: list[str] = []
    host2 = _new_host()
    host2.activate_all([
        FakePlugin("fake.dep2", dispose_records=records),
        FakePlugin("fake.child2", requires=("fake.dep2",), dispose_records=records),
    ])
    host2.shutdown()
    assert records == ["fake.child2", "fake.dep2"]


# -- stream routes: host-owned admission, plugin-owned resolution -------------


def test_stream_route_resolution_and_honest_absence():
    host = _new_host()
    assert host.stream_routes.resolve("acp-channel", "conn-1") is None

    class Owned:
        pass

    endpoint = Owned()
    host.activate(_RoutePlugin("fake.route", {"conn-1": endpoint}))
    assert host.stream_routes.resolve("acp-channel", "conn-1") is endpoint
    assert host.stream_routes.resolve("acp-channel", "conn-404") is None
    host.deactivate("fake.route")
    assert host.stream_routes.resolve("acp-channel", "conn-1") is None


class _RoutePlugin:
    """A contract plugin that owns one stream route with real resolution."""

    def __init__(self, plugin_id, table):
        self._id = plugin_id
        self._table = table

    def descriptor(self):
        return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

    def build(self, context):
        return ServerPluginRegistration(stream_routes=(StreamRouteDescriptor(
            route_id="acp-channel",
            resolver=lambda ref: self._table.get(ref),
            owner=self._id,
        ),))
