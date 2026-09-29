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
from ordessa_server_compat.plugin import ServerCompatPlugin
from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
from ordessa_workspace.plugin import PLUGIN_ID as WORKSPACE_ID
from ordessa_workspace.plugin import WorkspaceServerPlugin
from ordessa_server.transport.http import create_app

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

WORKSPACE_METHODS = {
    "workspaces.browse", "workspaces.open", "workspaces.list",
    "workspaces.archive", "workspaces.gitStatus",
}
#: AR-1/W-1 后的方法面基数：67 − providerModels.* 六方法 − profile 写面八方法 = 53。
#: 断言公式是 T002 + 2(admission) + 1(hello) = 56（总数）。随 W-1 同批落地。
T002_METHOD_COUNT = 70  # S-03 装配：53 + PermissionsBackendPlugin 17 方法（权限后端进默认链）
ACP_ADMISSION_METHODS = frozenset({
    "acp.submission.authorize", "acp.permission.authorize",
})
SANDBOX_DESCRIBE_METHOD = "sandbox.describe"


def _hello_caps(runtime) -> dict[str, dict]:
    result = runtime.wire.hello(HELLO)
    return {item["id"]: item for item in result["capabilities"]}


def _assert_default_composition_caps(runtime, caps=None) -> None:
    """The post-AR-1 face, two ACP rows and Q5's read-only query coexist."""
    caps = _hello_caps(runtime) if caps is None else caps
    assert len(caps) == T002_METHOD_COUNT + len(ACP_ADMISSION_METHODS) + 1
    sandbox = runtime.wire._registry.lookup(SANDBOX_DESCRIBE_METHOD)
    assert sandbox is not None and sandbox.owner == "ordessa.sandbox"
    assert caps[SANDBOX_DESCRIBE_METHOD] == {
        "id": SANDBOX_DESCRIBE_METHOD, "supported": True}
    for method in ACP_ADMISSION_METHODS:
        descriptor = runtime.wire._registry.lookup(method)
        assert descriptor is not None and descriptor.owner == "ordessa.harness.acp"
        assert caps[method] == {"id": method, "supported": False,
                                "reason": "ACP admission authority is unavailable"}


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
    from ordessa_workspace.local_environment import LocalEnvironmentProvider

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
            _assert_default_composition_caps(runtime, caps)
            assert runtime.plugin_host.active_ids() == (
                    WORKSPACE_ID, "ordessa.server-compat", "ordessa.harness.acp",
                    "ordessa.model-provider", "ordessa.sandbox",
                    "ordessa.sandbox-adapters", "permissions-backend",
                    "ordessa.permissions-adapters")
    except BaseException:
        runtime.stop()
        raise


# -- unload, disposal exactly once, isolation --------------------------------


def test_unload_removes_only_that_plugins_methods_and_disposes_exactly_once(tmp_path):
    records: list[str] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        WorkspaceServerPlugin(),
        ServerCompatPlugin(),
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
            # The compatibility core declares its dependency on the Workspace
            # plugin, so it must be unloaded FIRST — the round-1 guard names
            # the dependent instead of orphaning it.
            from server_plugin_api import DependentActiveError

            with pytest.raises(DependentActiveError):
                runtime.plugin_host.deactivate(WORKSPACE_ID)
            assert WORKSPACE_METHODS <= set(_hello_caps(runtime)), (
                "the refused unload must not have removed the dependency's rows")
            runtime.plugin_host.deactivate("ordessa.server-compat")
            # The dependency is now the only provider left of the workspace
            # facts the compat handlers consume: with the consumer gone, its
            # methods are gone and the workspace rows survive it.
            assert "profiles.list" not in _hello_caps(runtime)
            assert WORKSPACE_METHODS <= set(_hello_caps(runtime)), (
                "unloading the dependent must not touch the dependency's rows")
            assert records == ["fake.extra"], "deactivate must dispose its own plugin only"
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


def test_compat_core_declaration_covers_exactly_its_registered_rows():
    """The compatibility core's declaration literals and its registry rows
    must agree: a row added to one and not the other is the order-097 hole.
    (Successor of the transition-adapter gate: the declarations moved with
    the domains into `ordessa_server_compat.core_wire`.)"""
    from ordessa_server_compat.core_wire import (
        _COMPAT_METHODS, _PARAM_SHAPES, _require_declared,
    )

    assert _require_declared() == ()


def test_a_restart_re_activates_the_same_selection(tmp_path):
    """stop() disposes every plugin; the next start() must bring the whole
    wire surface back — a restart that silently shrinks to `server.hello` is
    a broken restart (the in-process restart cycle is product behaviour)."""
    runtime = build_runtime(tmp_path / "data")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        _assert_default_composition_caps(runtime)
    assert runtime.plugin_host.active_ids() == (), "stop must have disposed everyone"
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        caps = _hello_caps(runtime)
        _assert_default_composition_caps(runtime, caps)
        assert WORKSPACE_METHODS <= set(caps)
        assert "profiles.list" in caps


# -- core-cleanup stage 1: a throwing disposal never stops the cleanup --------


class _LifecyclePlugin:
    """A contract plugin with independently observable build/disposal facts."""

    def __init__(self, plugin_id, *, records, method="fake.method",
                build_raises=None, dispose_raises=None):
        self._id = plugin_id
        self._records = records
        self._method = method
        self._build_raises = build_raises
        self._dispose_raises = dispose_raises

    def descriptor(self):
        return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

    def build(self, context):
        self._records.append(("build", self._id))
        if self._build_raises is not None:
            raise self._build_raises
        def _disposal():
            self._records.append(("dispose", self._id))
            if self._dispose_raises is not None:
                raise self._dispose_raises
        return ServerPluginRegistration(
            methods=(ServerMethodDescriptor(
                method_id=self._method, required_params=frozenset({"requestId"}),
                optional_params=frozenset(), handler=lambda params: {"ok": self._id},
                owner=self._id,
            ),),
            disposal=_disposal,
        )


def test_a_throwing_disposal_does_not_stop_the_rollback_of_the_rest():
    """A activated, B activated, C's build fails, and B's disposal throws on
    the way down: A must still be cleaned, every registration of the round
    revoked, and C's original error must stay the primary failure with B's
    cleanup error inspectable on it."""
    from server_plugin_api import PluginCleanupError

    records: list[tuple[str, str]] = []
    a = _LifecyclePlugin("fake.a", records=records)
    boom = RuntimeError("B cleanup boom")
    b = _LifecyclePlugin("fake.b", records=records, method="fake.other",
                         dispose_raises=boom)
    c_failure = RuntimeError("C original failure")
    c = _LifecyclePlugin("fake.c", records=records, build_raises=c_failure)
    host = _new_host()
    with pytest.raises(RuntimeError) as captured:
        host.activate_all([a, b, c])
    assert captured.value is c_failure, "the plugin's own failure must stay primary"
    assert records == [
        ("build", "fake.a"), ("build", "fake.b"), ("build", "fake.c"),
        ("dispose", "fake.b"), ("dispose", "fake.a"),
    ], records
    carried = getattr(captured.value, "cleanup_errors", None)
    assert carried is not None, "the disposal failure must be inspectable"
    assert len(carried) == 1
    assert isinstance(carried[0], PluginCleanupError)
    assert carried[0].plugin_id == "fake.b"
    assert carried[0].error is boom
    assert host.active_ids() == ()
    assert len(host.methods) == 0, "every registration of the round must be revoked"
    assert host.stream_routes.resolve("fake.a", "ref") is None


def test_a_failed_composition_with_a_throwing_disposal_releases_the_root(tmp_path):
    """The same shape through build_runtime: the round returns no runtime, the
    data-root lock is released for the retry path, and every disposal of the
    round ran — including the one that threw."""
    class Boom(RuntimeError):
        pass

    records: list[tuple[str, str]] = []
    root = tmp_path / "data"
    with pytest.raises(Boom) as captured:
        build_runtime(root, server_plugins=[
            _LifecyclePlugin("fake.ok", records=records, method="fake.first"),
            _LifecyclePlugin("fake.messy", records=records, method="fake.second",
                             dispose_raises=RuntimeError("messy cleanup")),
            _LifecyclePlugin("fake.boom", records=records, method="fake.third",
                             build_raises=Boom()),
        ])
    assert ("dispose", "fake.messy") in records
    assert ("dispose", "fake.ok") in records
    carried = getattr(captured.value, "cleanup_errors", None)
    assert carried is not None and [e.plugin_id for e in carried] == ["fake.messy"]
    runtime = build_runtime(root)
    try:
        with _Started(runtime):
            _assert_default_composition_caps(runtime)
    except BaseException:
        runtime.stop()
        raise


def test_shutdown_disposes_every_plugin_even_when_one_disposal_throws():
    """Normal shutdown is the same promise: one plugin's disposal raising must
    not orphan the others — every plugin is disposed exactly once, reverse
    order, and the collected failures surface as one typed error."""
    from server_plugin_api import CleanupError, PluginCleanupError

    records: list[tuple[str, str]] = []
    mess = RuntimeError("B cleanup boom")
    host = _new_host()
    host.activate_all([
        _LifecyclePlugin("fake.a", records=records),
        _LifecyclePlugin("fake.b", records=records, method="fake.other",
                         dispose_raises=mess),
        _LifecyclePlugin("fake.c", records=records, method="fake.third"),
    ])
    with pytest.raises(CleanupError) as captured:
        host.shutdown()
    assert records == [
        ("build", "fake.a"), ("build", "fake.b"), ("build", "fake.c"),
        ("dispose", "fake.c"), ("dispose", "fake.b"), ("dispose", "fake.a"),
    ], records
    errors = captured.value.errors
    assert len(errors) == 1
    assert isinstance(errors[0], PluginCleanupError)
    assert errors[0].plugin_id == "fake.b" and errors[0].error is mess
    assert host.active_ids() == ()
    assert len(host.methods) == 0


def test_runtime_stop_releases_the_root_even_when_a_disposal_throws(tmp_path):
    """stop() must not leave the data-root lock behind because a plugin's
    disposal raised: the root stays usable for the next composition."""
    from server_plugin_api import CleanupError

    records: list[tuple[str, str]] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        _LifecyclePlugin("fake.messy", records=records,
                         dispose_raises=RuntimeError("messy cleanup")),
    ])
    runtime.start()
    with pytest.raises(CleanupError):
        runtime.stop()
    assert ("dispose", "fake.messy") in records
    assert runtime.owner.acquired is False, "the lock must be released"
    retry = build_runtime(tmp_path / "data")
    try:
        with _Started(retry):
            _assert_default_composition_caps(retry)
    except BaseException:
        retry.stop()
        raise


# -- core-cleanup stage 2: the plugin HTTP route seam -------------------------

_ROUTE_PATH = "/api/v1/plugin-fake/echo"


def _echo_endpoint(body: dict):
    """A plugin-owned endpoint shape a FastAPI app can admit as-is."""
    return {"echo": body}


class _HttpRoutePlugin:
    """Contract plugin contributing one HTTP route through the host seam."""

    def __init__(self, plugin_id="fake.route", *, path=_ROUTE_PATH,
                 methods=("POST",), endpoint=_echo_endpoint):
        self._id = plugin_id
        self._path = path
        self._methods = frozenset(methods)
        self._endpoint = endpoint

    def descriptor(self):
        return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

    def build(self, context):
        from server_plugin_api import HttpRouteDescriptor

        return ServerPluginRegistration(stream_routes=(), http_routes=(
            HttpRouteDescriptor(path=self._path, methods=self._methods,
                                endpoint=self._endpoint, owner=self._id),
        ))


def test_a_plugin_http_route_passes_host_auth_and_answers(tmp_path):
    """The route is the plugin's, the wall is the host's: without a bearer
    token the answer is 401, with it the plugin endpoint answers, and the
    loopback policy covers it like every host route."""
    runtime = build_runtime(tmp_path / "data", server_plugins=[_HttpRoutePlugin()])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            unauthenticated = client.post(_ROUTE_PATH, json={"ping": 1})
            assert unauthenticated.status_code == 401, unauthenticated.text
            answer = client.post(_ROUTE_PATH, json={"ping": 1}, headers={
                "Authorization": f"Bearer {runtime.token}"})
            assert answer.status_code == 200, answer.text
            assert answer.json() == {"echo": {"ping": 1}}
    finally:
        runtime.stop()


def test_a_plugin_http_route_error_never_leaks_its_text(tmp_path):
    """A plugin endpoint that raises answers the transport's last wall: the
    status stays 500 and the exception's text (paths, credentials) never
    leaves — only its type, as internalCode."""
    def _leaky(body: dict):
        raise RuntimeError("leak: /secret/data-root/credentials.token")

    runtime = build_runtime(tmp_path / "data", server_plugins=[
        _HttpRoutePlugin(endpoint=_leaky)])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                        raise_server_exceptions=False) as client:
            answer = client.post(_ROUTE_PATH, json={}, headers={
                "Authorization": f"Bearer {runtime.token}"})
            assert answer.status_code == 500
            assert answer.json()["error"]["details"]["internalCode"] == "RuntimeError"
            assert "secret" not in answer.text
    finally:
        runtime.stop()


def test_two_plugins_claiming_the_same_http_route_refuse_activation():
    """One path+method, one owner: the second claim is a typed refusal and the
    round stays transactional."""
    from server_plugin_api import DuplicateHttpRouteError

    host = _new_host()
    with pytest.raises(DuplicateHttpRouteError):
        host.activate_all([_HttpRoutePlugin("fake.route.a"), _HttpRoutePlugin("fake.route.b")])
    assert host.active_ids() == ()


def test_a_plugin_route_on_a_host_path_refuses_at_the_transport(tmp_path):
    """A plugin route that would shadow a host route (health, wire dispatch)
    is a startup refusal, never a silent second handler."""
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        _HttpRoutePlugin(path="/live", methods=("GET",))])
    try:
        with pytest.raises(RuntimeError) as captured:
            create_app(runtime)
        assert "PLUGIN_HTTP_ROUTE_CONFLICT" in str(captured.value)
    finally:
        runtime.stop()


def test_unloading_the_plugin_removes_its_http_route(tmp_path):
    """Uninstalling the capability removes exactly that capability: a fresh
    transport after unload answers 404 where the route used to be. (Clients
    run without a lifespan here: start, the unload and the stop are driven by
    hand — a TestClient context would stop the runtime mid-test.)"""
    runtime = build_runtime(tmp_path / "data", server_plugins=[_HttpRoutePlugin()])
    try:
        runtime.start()
        headers = {"Authorization": f"Bearer {runtime.token}"}
        live = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert live.post(_ROUTE_PATH, json={}, headers=headers).status_code == 200
        runtime.plugin_host.deactivate("fake.route")
        fresh = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert fresh.post(_ROUTE_PATH, json={}, headers=headers).status_code == 404
    finally:
        runtime.stop()


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
            _assert_default_composition_caps(runtime)
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


# -- review round 2: the composition itself must clean up --------------------


def test_a_failed_composition_disposes_activated_plugins_and_releases_the_root(tmp_path):
    """A succeeded, B failed to build: the round never returns a runtime, so
    the host must dispose A exactly once and release the lock — the same-root
    retry then starts clean, with none of A's methods still advertised."""
    class Boom(RuntimeError):
        pass

    records: list[str] = []
    root = tmp_path / "data"
    with pytest.raises(Boom):
        build_runtime(root, server_plugins=[
            FakePlugin("fake.first", methods=(("fake.first.method", set()),),
                       dispose_records=records),
            FakePlugin("fake.boom", raises=Boom()),
        ])
    assert records == ["fake.first"], (
        f"the activated plugin must be disposed exactly once, saw {records}")
    runtime = build_runtime(root)
    try:
        with _Started(runtime):
            assert "fake.first.method" not in _hello_caps(runtime)
            _assert_default_composition_caps(runtime)
    except BaseException:
        runtime.stop()
        raise


def test_a_failed_start_round_disposes_activated_plugins_and_releases_the_lock(tmp_path):
    """The start() re-activation round is transactional too: A re-activates,
    the flaky plugin fails on its second build, A is disposed once more, and
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

    records: list[str] = []
    root = tmp_path / "data"
    runtime = build_runtime(root, server_plugins=[
        FakePlugin("fake.first", dispose_records=records), FlakyPlugin()])
    runtime.stop()
    assert records == ["fake.first"]
    with pytest.raises(RuntimeError, match="SECOND_BUILD_BOOM"):
        runtime.start()
    assert records == ["fake.first", "fake.first"], (
        f"the failed start round must dispose its activated plugin once more: {records}")
    assert runtime.started is False
    fresh = build_runtime(root)
    try:
        with _Started(fresh):
            assert "server.hello" in _hello_caps(fresh)
    except BaseException:
        fresh.stop()
        raise


def test_a_failed_activation_round_is_transactional_for_this_round():
    """Rolling back a failed round removes exactly what the round activated:
    earlier-round plugins stay active, this round's are disposed."""
    class Boom(RuntimeError):
        pass

    host = _new_host()
    host.activate(FakePlugin("fake.earlier", methods=(("fake.earlier.method", set()),)))
    records: list[str] = []
    with pytest.raises(Boom):
        host.activate_all([
            FakePlugin("fake.a", methods=(("fake.a.method", set()),),
                       dispose_records=records),
            FakePlugin("fake.b", raises=Boom()),
        ])
    assert records == ["fake.a"]
    assert host.active_ids() == ("fake.earlier",)
    assert host.methods.lookup("fake.a.method") is None
    assert host.methods.lookup("fake.earlier.method") is not None


def test_a_dependency_port_shadowing_an_existing_binding_refuses_the_composition(tmp_path):
    """A provided port must never silently override an existing binding: a
    name colliding with a host port refuses the consumer's activation as a
    typed conflict; the round stays transactional and the root reusable."""
    from server_plugin_api import PortConflictError

    root = tmp_path / "data"
    with pytest.raises(PortConflictError) as refused:
        build_runtime(root, server_plugins=[
            FakePlugin("fake.shadow", ports={"idempotency": object()}),
            FakePlugin("fake.child", requires=("fake.shadow",),
                       methods=(("fake.child.method", set()),)),
        ])
    assert refused.value.port_name == "idempotency"
    runtime = build_runtime(root)
    runtime.stop()


def test_port_conflicts_are_refused_between_dependencies_too():
    """The same refusal guards dependency-to-dependency collisions: two
    dependencies providing the same name leave the consumer with an
    ambiguous binding, so its activation is refused and the providers stay
    active untouched."""
    from server_plugin_api import PortConflictError

    host = ServerPluginHost(
        methods=MethodRegistry(), stream_routes=StreamRouteRegistry(),
        host_ports={"idempotency": object()},
    )
    host.activate_all([
        FakePlugin("fake.p1", methods=(("fake.p1.method", set()),),
                   ports={"fake.same": object()}),
        FakePlugin("fake.p2", methods=(("fake.p2.method", set()),),
                   ports={"fake.same": object()}),
    ])
    with pytest.raises(PortConflictError):
        host.activate(FakePlugin("fake.child", requires=("fake.p1", "fake.p2"),
                                 methods=(("fake.child.method", set()),)))
    assert host.active_ids() == ("fake.p1", "fake.p2")
    # A host-port shadow is the same refusal: a dependency providing a port
    # named like a host facade ("idempotency") is refused at the consumer.
    host.activate(FakePlugin("fake.shadow", methods=(("fake.shadow.method", set()),),
                             ports={"idempotency": object()}))
    with pytest.raises(PortConflictError) as refused:
        host.activate(FakePlugin("fake.child2", requires=("fake.shadow",),
                                 methods=(("fake.child2.method", set()),)))
    assert refused.value.port_name == "idempotency"
    assert host.active_ids() == ("fake.p1", "fake.p2", "fake.shadow")


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


# -- review round 3 (core cleanup): runtime-lifecycle counterexamples ---------


class _ServedPlugin:
    """A contract plugin with an HTTP route and a per-build port object.

    Build counting and start recording are separate facts: `builds[n]` is the
    n-th build's port object (its `round`), `starts` only records that a
    start hook ran — a hook must never shift the round numbering."""

    def __init__(self, plugin_id="fake.served", *, path="/api/v1/plugin-fake/echo",
                 authenticated=True):
        self._id = plugin_id
        self._path = path
        self.authenticated = authenticated
        self.builds: list[dict] = []
        self.starts: list[bool] = []

    def descriptor(self):
        return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

    def endpoint_for(self, obj):
        def echo(body: dict):
            return {"echo": body, "round": obj["round"]}
        return echo

    def build(self, context):
        from server_plugin_api import HttpRouteDescriptor

        obj = {"round": len(self.builds)}
        self.builds.append(obj)

        return ServerPluginRegistration(
            http_routes=(HttpRouteDescriptor(
                path=self._path, methods=frozenset({"POST"}),
                endpoint=self.endpoint_for(obj), owner=self._id,
                authenticated=self.authenticated,
            ),),
            provided_ports={"fake.obj": obj},
            start_hooks=(lambda: self.starts.append(True),),
        )


def test_a_mounted_route_stops_serving_when_its_owner_unloads_on_the_same_app(tmp_path):
    """The counterexample the fresh-app test missed: the SAME App, the SAME
    client — unload must take the route away from the running transport, not
    just from the registry."""
    runtime = build_runtime(tmp_path / "data", server_plugins=[_ServedPlugin()])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        runtime.start()
        app = create_app(runtime)
        client = TestClient(app, base_url="http://127.0.0.1")
        assert client.post("/api/v1/plugin-fake/echo", json={}, headers=headers).status_code == 200
        runtime.plugin_host.deactivate("fake.served")
        answer = client.post("/api/v1/plugin-fake/echo", json={}, headers=headers)
        assert answer.status_code == 404, (
            f"unloaded capability still served by the running app: {answer.text}")
    finally:
        runtime.stop()


def test_a_route_mounted_at_creation_resumes_with_its_owner(tmp_path):
    """The app is a route snapshot mounted at creation; each mounted route
    serves exactly while its owner is active. Re-activating the same plugin
    resumes the mounted route; a plugin activated AFTER creation gets no
    routes on that app (documented snapshot semantics)."""
    plugin = _ServedPlugin()
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert client.post("/api/v1/plugin-fake/echo", json={}, headers=headers).status_code == 200
        runtime.plugin_host.deactivate("fake.served")
        assert client.post("/api/v1/plugin-fake/echo", json={}, headers=headers).status_code == 404
        runtime.plugin_host.activate(plugin)
        answer = client.post("/api/v1/plugin-fake/echo", json={}, headers=headers)
        assert answer.status_code == 200, answer.text
        assert answer.json()["round"] == 1, "the re-activated build serves again"
    finally:
        runtime.stop()


class _PortPlugin:
    """Provides one mapped runtime facade port with a fresh object per build."""

    def __init__(self, plugin_id="fake.ports"):
        self._id = plugin_id
        self.builds: list[dict] = []

    def descriptor(self):
        return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

    def build(self, context):
        obj = {"build": len(self.builds)}
        self.builds.append(obj)
        return ServerPluginRegistration(provided_ports={"approvals.records": obj})


def test_runtime_facades_follow_the_live_activation_round(tmp_path):
    """stop→start re-activates plugins: the mapped runtime facades must
    re-bind to the ports of the round that is actually active — and fall to
    None once the plugins are disposed. A stale facade makes the runtime
    operate on a disposed round's objects (the reviewer's stop→start
    counterexample)."""
    plugin = _PortPlugin()
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    try:
        runtime.start()
        first = runtime.plugin_host.provided_port('approvals.records')
        assert first is not None and first is plugin.builds[0], (
            "the facade binds to the active round's port at composition")
        runtime.stop()
        assert runtime.plugin_host.active_ids() == ()
        assert runtime.plugin_host.provided_port('approvals.records') is None, (
            "after stop the round's ports are gone; a facade must not keep one")
        runtime.start()
        second = runtime.plugin_host.provided_port('approvals.records')
        assert second is not None and second is plugin.builds[1], (
            "the re-activated round's facade must be the new port object, "
            "not the disposed first round's")
        assert second is not first
    finally:
        runtime.stop()


def test_a_failed_start_hook_disposes_the_round_and_releases_the_root(tmp_path):
    """A start hook that raises must not leave the round active with the lock
    released: the plugins are disposed (reverse order), the start error stays
    primary with any cleanup errors attached, and the same root retries."""

    class HookBoom(RuntimeError):
        pass

    records: list[tuple[str, str]] = []

    class _HookedPlugin:
        def descriptor(self):
            return ServerPluginDescriptor(id="fake.start", display_name="s", version="1")

        def build(self, context):
            def _disposal():
                records.append(("dispose", "fake.start"))
            def _hook():
                raise HookBoom("start hook refused this round")
            return ServerPluginRegistration(
                methods=(ServerMethodDescriptor(
                    method_id="fake.start.ping", required_params=frozenset({"requestId"}),
                    optional_params=frozenset(), handler=lambda params: {"ok": True},
                    owner="fake.start",
                ),),
                start_hooks=(_hook,), disposal=_disposal,
            )

    root = tmp_path / "data"
    runtime = build_runtime(root, server_plugins=[_HookedPlugin()])
    with pytest.raises(HookBoom) as captured:
        runtime.start()
    assert runtime.plugin_host.active_ids() == (), (
        "a failed start must not leave the round active")
    assert records == [("dispose", "fake.start")], records
    assert runtime.owner.acquired is False, "the lock must be released"
    retry = build_runtime(root)
    try:
        with _Started(retry):
            _assert_default_composition_caps(retry)
    except BaseException:
        retry.stop()
        raise


def test_a_staging_rollback_keeps_the_conflict_primary(tmp_path):
    """The duplicate-method conflict is the failure under test. BOTH owed
    disposals raise — the already-activated plugin's (transactional rollback)
    and the staging-failed plugin's own (its build succeeded, so its
    resources exist) — and both must stay inspectable on the primary error's
    `cleanup_errors`. A cleanup failure may never replace the typed
    conflict, and a fix that captures only one of the two is incomplete."""

    class Boom(RuntimeError):
        pass

    class _MessyPlugin:
        def __init__(self, plugin_id):
            self._id = plugin_id

        def descriptor(self):
            return ServerPluginDescriptor(id=self._id, display_name=self._id, version="1")

        def build(self, context):
            def _disposal():
                self.disposed = True
                raise Boom(f"cleanup failed: {self._id}")
            self.disposed = False
            return ServerPluginRegistration(
                methods=(ServerMethodDescriptor(
                    method_id="fake.dup", required_params=frozenset({"requestId"}),
                    optional_params=frozenset(), handler=lambda params: {"ok": self._id},
                    owner=self._id,
                ),),
                disposal=_disposal,
            )

    host = _new_host()
    first = _MessyPlugin("fake.messy")
    second = _MessyPlugin("fake.second")
    with pytest.raises(DuplicateMethodError) as captured:
        host.activate_all([first, second])
    assert "fake.dup" in str(captured.value), captured.value
    assert first.disposed and second.disposed, (
        "both owed disposals must have been called exactly once")
    carried = getattr(captured.value, "cleanup_errors", None)
    assert carried is not None, (
        "both cleanup failures must be inspectable on the primary conflict")
    assert {e.plugin_id for e in carried} == {"fake.messy", "fake.second"}, carried
    assert all(isinstance(e.error, Boom) for e in carried)
    assert host.active_ids() == ()


def test_an_app_created_activation_with_unmounted_http_routes_refuses(tmp_path):
    """A live App serves a frozen route set. A plugin activated after the app
    was created that contributes HTTP routes which were never mounted on it
    must be refused type-wise, with the usual transactional rollback — the
    alternative (wire methods live, HTTP routes silently never served) is a
    half-effective plugin, and half-effective is dishonest either way. The
    late plugin carries a real wire method and a countable disposal, so
    "refused and not half-effective" is checkable: the method is not
    registered, the owed disposal ran exactly once, and the same App answers
    404 on the never-mounted route."""
    from server_plugin_api import ServerPluginError

    late_disposals: list[int] = []

    class _LatePlugin(_ServedPlugin):
        def build(self, context):
            registration = super().build(context)

            def _disposal():
                late_disposals.append(1)

            return ServerPluginRegistration(
                methods=registration.methods + (ServerMethodDescriptor(
                    method_id="fake.late.ping", required_params=frozenset({"requestId"}),
                    optional_params=frozenset(), handler=lambda params: {"ok": "late"},
                    owner=self._id,
                ),),
                stream_routes=registration.stream_routes,
                http_routes=registration.http_routes,
                provided_ports=registration.provided_ports,
                disposal=_disposal,
            )

    mounted = _ServedPlugin("fake.mounted")
    late = _LatePlugin("fake.late", path="/api/v1/plugin-fake/late")
    runtime = build_runtime(tmp_path / "data", server_plugins=[mounted])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            assert client.post("/api/v1/plugin-fake/echo", json={}, headers=headers).status_code == 200

            with pytest.raises(ServerPluginError) as captured:
                runtime.plugin_host.activate(late)
            assert "PLUGIN_HTTP_ROUTE_UNMOUNTED" in str(captured.value), captured.value
            # transactional: the refused plugin never became active, its owed
            # disposal ran exactly once, and the mounted plugin is untouched
            assert runtime.plugin_host.active_ids() == ("fake.mounted",)
            assert len(late.builds) == 1, "exactly one build attempt, rolled back"
            assert late_disposals == [1], late_disposals
            # no wire surface leakage: the method is not registered...
            assert runtime.wire._registry.lookup("fake.late.ping") is None
            assert client.post("/wire/v1/fake.late.ping", json={
                "jsonrpc": "2.0", "id": "1", "method": "fake.late.ping",
                "params": {"requestId": "late-1"}}, headers=headers,
            ).json()["error"]["code"] == "INVALID_REQUEST"
            # ...and the same App never serves the never-mounted route
            assert client.post("/api/v1/plugin-fake/late", json={}, headers=headers).status_code == 404
            # the mounted route still serves its owner
            assert client.post("/api/v1/plugin-fake/echo", json={}, headers=headers).status_code == 200
    finally:
        runtime.stop()


# -- review round 4: the mounted route's SHAPE is part of the freeze ----------


def test_a_reactivated_route_cannot_loosen_its_auth_wall(tmp_path):
    """The frozen route shape includes the auth flag. First mount
    unauthenticated, then unload and re-activate declaring bearer-required:
    the activation must refuse type-wise — otherwise the old app keeps
    serving the new registration behind the wall that was mounted first,
    and the wall silently moved without the transport knowing."""
    from server_plugin_api import ServerPluginError

    plugin = _ServedPlugin("fake.auth", authenticated=False)
    disposals: list[int] = []

    class _Counted(_ServedPlugin):
        def build(self, context):
            registration = super().build(context)
            def _disposal():
                disposals.append(1)
            return ServerPluginRegistration(
                methods=registration.methods, stream_routes=registration.stream_routes,
                http_routes=registration.http_routes,
                provided_ports=registration.provided_ports,
                start_hooks=registration.start_hooks, disposal=_disposal,
            )

    plugin = _Counted("fake.auth", authenticated=False)
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            # first mount: unauthenticated — no bearer, 200
            assert client.post("/api/v1/plugin-fake/echo", json={}).status_code == 200
            plugin.authenticated = True
            runtime.plugin_host.deactivate("fake.auth")
            with pytest.raises(ServerPluginError) as captured:
                runtime.plugin_host.activate(plugin)
            assert "PLUGIN_HTTP_ROUTE_SHAPE_CHANGED" in str(captured.value), captured.value
            # transactional: not active; the owed disposal ran exactly once
            # for the unload and exactly once for the refused activation
            assert runtime.plugin_host.active_ids() == ()
            assert disposals == [1, 1], disposals
            # the wall did not loosen: the route is gone (owner inactive)
            assert client.post("/api/v1/plugin-fake/echo", json={}).status_code == 404
    finally:
        runtime.stop()


def test_a_reactivated_route_cannot_change_its_endpoint_signature(tmp_path):
    """The frozen route shape includes the endpoint's FastAPI-visible
    signature. A re-activation whose endpoint takes different parameters
    must refuse type-wise — the old app's request machinery would otherwise
    call a new endpoint with the old call shape and answer 500."""
    from server_plugin_api import ServerPluginError

    class _Flipping(_ServedPlugin):
        def endpoint_for(self, obj):
            if obj["round"] == 0:
                def echo(body: dict):
                    return {"echo": body, "round": obj["round"]}
                return echo
            def echo(body: dict, extra: int):  # a new required parameter
                return {"echo": body, "extra": extra}
            return echo

    plugin = _Flipping("fake.sig")
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            assert client.post("/api/v1/plugin-fake/echo", json={},
                               headers={"Authorization": f"Bearer {runtime.token}"}).status_code == 200
            runtime.plugin_host.deactivate("fake.sig")
            with pytest.raises(ServerPluginError) as captured:
                runtime.plugin_host.activate(plugin)
            assert "PLUGIN_HTTP_ROUTE_SHAPE_CHANGED" in str(captured.value), captured.value
            assert runtime.plugin_host.active_ids() == ()
    finally:
        runtime.stop()


def test_a_failed_start_keeps_its_error_primary_with_cleanup_errors(tmp_path):
    """The reviewer's second round-4 gap: the cleanup failure must attach to
    the START error explicitly — reading sys.exc_info() inside the inner
    except captures the cleanup exception itself, so cleanup_errors ends up
    missing. The start error stays primary; the disposal failure is
    inspectable."""

    class HookBoom(ValueError):
        pass

    class CleanBoom(RuntimeError):
        pass

    records: list[tuple[str, str]] = []

    class _DoubleFault:
        def descriptor(self):
            return ServerPluginDescriptor(id="fake.double", display_name="d", version="1")

        def build(self, context):
            def _disposal():
                records.append(("dispose", "fake.double"))
                raise CleanBoom("disposal refused")
            def _hook():
                raise HookBoom("start refused")
            return ServerPluginRegistration(
                methods=(ServerMethodDescriptor(
                    method_id="fake.double.ping", required_params=frozenset({"requestId"}),
                    optional_params=frozenset(), handler=lambda params: {"ok": True},
                    owner="fake.double",
                ),),
                start_hooks=(_hook,), disposal=_disposal,
            )

    root = tmp_path / "data"
    runtime = build_runtime(root, server_plugins=[_DoubleFault()])
    with pytest.raises(HookBoom) as captured:
        runtime.start()
    assert isinstance(captured.value, HookBoom), "the start error stays primary"
    carried = getattr(captured.value, "cleanup_errors", None)
    assert carried is not None and len(carried) == 1, (
        "the disposal failure must be inspectable on the start error")
    assert carried[0].plugin_id == "fake.double"
    assert isinstance(carried[0].error, CleanBoom)
    assert records == [("dispose", "fake.double")]
    assert runtime.plugin_host.active_ids() == ()
    assert runtime.owner.acquired is False
    retry = build_runtime(root)
    try:
        with _Started(retry):
            _assert_default_composition_caps(retry)
    except BaseException:
        retry.stop()
        raise


# -- review round 5: the pre-startup mounting window --------------------------


def test_a_pre_startup_auth_swap_cannot_double_mount(tmp_path):
    """create_app mounts routes before the lifespan freezes the served set.
    In that window an unload + re-activation with a flipped auth shape must
    not survive startup: the mount stage sees the overlap (same path and
    methods, different shape) and refuses type-wise — the app never enters a
    state where the unauthenticated wall serves, and the failed startup
    cleans the round and the data root up."""
    plugin = _ServedPlugin("fake.window", authenticated=False)
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    app = create_app(runtime)  # mounts the unauthenticated shape; frozen not yet set
    runtime.plugin_host.deactivate("fake.window")
    plugin.authenticated = True
    runtime.plugin_host.activate(plugin)  # the window: no freeze to refuse yet
    from server_plugin_api import ServerPluginError

    with pytest.raises(ServerPluginError) as captured:
        with TestClient(app, base_url="http://127.0.0.1"):
            pass
    assert "PLUGIN_HTTP_ROUTE_SHAPE_CHANGED" in str(captured.value), captured.value
    # the covered cleanup: the failed startup disposed the round and the root
    assert runtime.plugin_host.active_ids() == ()
    assert runtime.owner.acquired is False
    retry = build_runtime(tmp_path / "data")
    try:
        with _Started(retry):
            _assert_default_composition_caps(retry)
    except BaseException:
        retry.stop()
        raise


def test_a_pre_startup_owner_takeover_cannot_double_mount(tmp_path):
    """The same window with a different owner: after the mounted plugin
    unloads, another plugin claiming the same path and methods must be
    refused at the mount stage — one route, one owner, also before the
    freeze exists."""
    first = _ServedPlugin("fake.first", path="/api/v1/plugin-fake/echo")
    runtime = build_runtime(tmp_path / "data", server_plugins=[first])
    app = create_app(runtime)  # mounts fake.first's shape
    runtime.plugin_host.deactivate("fake.first")
    second = _ServedPlugin("fake.second", path="/api/v1/plugin-fake/echo")
    runtime.plugin_host.activate(second)  # the window
    from server_plugin_api import ServerPluginError

    with pytest.raises(ServerPluginError) as captured:
        with TestClient(app, base_url="http://127.0.0.1"):
            pass
    assert "PLUGIN_HTTP_ROUTE_DUPLICATE" in str(captured.value), captured.value
    assert runtime.plugin_host.active_ids() == ()
    assert runtime.owner.acquired is False
