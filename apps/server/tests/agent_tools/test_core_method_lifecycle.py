"""UnitRuntimeOwner/real-registry lifecycle tests, not product acceptance.

No socket, native provider, user data or model is used. The database/root
owner are bounded doubles. UnitRuntimeOwner, ProductUnitAdmission, and its
original SQLite Unit store are real production instances.
"""
from ordessa_server.composition.runtime import RuntimeCompositionUnavailable
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable
import pytest
from threading import Barrier, Event, Thread

from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_server.composition.runtime import ServerRuntime
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server.composition.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
from ordessa_server.composition.unit_runtime import UnitRuntimeOwner
from ordessa_units.persistence.sqlite import SqliteUnitStore, WriterLockHeldError
from server_plugin_api import (
    DuplicateMethodError, InvalidDeclarationError, ServerMethodDescriptor,
    ServerPluginDescriptor, ServerPluginRegistration,
)


class Owner:
    acquired = True
    def acquire(self):
        self.acquired = True
    def release(self):
        self.acquired = False


class Database:
    def initialize(self):
        pass


def descriptor(method_id="agents.capabilities", owner="pacthold.agents", handler=None):
    return ServerMethodDescriptor(method_id, frozenset(), frozenset(),
                                  handler or (lambda params: {}), owner)


def runtime(tmp_path, factory):
    owner = Owner()
    contexts = []
    product = create_host_product_composition()
    def admission_factory(path):
        assert owner.acquired
        context = product.environment_factory(
            path, _exclusive_owner=lambda: owner.acquired)
        contexts.append(context)
        return context
    unit_runtime = UnitRuntimeOwner(
        tmp_path / "core.sqlite", environment_factory=admission_factory,
        ownership_probe=lambda: owner.acquired)
    host = ServerPluginHost(methods=MethodRegistry(), stream_routes=StreamRouteRegistry(),
                            data_root=tmp_path)
    value = ServerRuntime(data_root=tmp_path, database=Database(), objects=None,
                          owner=owner, token="controlled-fixture", token_path=tmp_path / "token",
                          notifier=None, plugin_host=host, unit_runtime=unit_runtime,
                          plugin_selection=(), core_method_factory=factory)
    return value, host, contexts


def test_unit_runtime_close_refuses_a_claim_still_held_in_original_store(tmp_path):
    value, _host, _contexts = runtime(tmp_path, None)
    context = value.unit_runtime.context
    store = context.store_port
    namespace = context.environment_namespace
    request = RequestKey(namespace, context.principal_scope, "held-start")
    step = StepIntent("spawn", {"environmentNamespace": namespace},
                      "fixed-input", "original-spawn")
    intent = OperationIntent("original-start", "unit-start", None,
        {"environmentNamespace": namespace}, (step,))
    store.reserve_operation(request, "fixed-input", intent)
    assert store.claim_operation_step(request, "fixed-input", step).claimed
    assert context.pending()["operationRefs"] == ("original-start",)

    try:
        with pytest.raises(UnitGuaranteeUnavailable, match="pending"):
            value.unit_runtime.close()
        assert context.pending()["operationRefs"] == ("original-start",)
        context.check_open()
        with pytest.raises(WriterLockHeldError):
            SqliteUnitStore(value.unit_runtime.store_path)
    finally:
        # This bounded test owns its temporary store; the refusing owner did
        # not release it or claim that the held operation had settled.
        store.close()


def test_start_stop_restart_uses_new_unit_scope_and_retires_old_resolver(tmp_path):
    def factory(resolve):
        return (descriptor(handler=lambda params: resolve()),)
    value, host, contexts = runtime(tmp_path, factory)
    try:
        value.start()
        first = host.methods.lookup("agents.capabilities")
        first_context = first.handler({})
        assert first_context is contexts[0]
        assert host.active_ids() == ()
        value.start()
        assert host.methods.lookup("agents.capabilities") is first
        value.stop()
        assert host.methods.lookup("agents.capabilities") is None
        with pytest.raises(RuntimeCompositionUnavailable):
            first.handler({})
        with pytest.raises(UnitAdmissionRefused):
            first_context.check_open()
        value.start()
        second = host.methods.lookup("agents.capabilities")
        assert second is not first
        assert second.handler({}) is contexts[1]
        assert second.handler({}) is not first_context
        with pytest.raises(RuntimeCompositionUnavailable):
            first.handler({})
    finally:
        value.stop()


@pytest.mark.parametrize("bad", ["owner", "prefix", "type", "container"])
def test_invalid_core_batch_never_partially_publishes(tmp_path, bad):
    def factory(resolve):
        if bad == "container":
            return [descriptor()]
        invalid = {"owner": descriptor("agents.profiles.list", owner="fake.plugin"),
                   "prefix": descriptor("profiles.list"), "type": object()}[bad]
        return (descriptor(), invalid)
    value, host, _ = runtime(tmp_path, factory)
    with pytest.raises(InvalidDeclarationError):
        value.start()
    assert host.methods.method_ids() == ()
    assert not value.started
    assert not value.owner.acquired


@pytest.mark.parametrize("existing", [False, True])
def test_batch_duplicate_conflict_leaves_no_half_registration(tmp_path, existing):
    def factory(resolve):
        return (descriptor(), descriptor("agents.profiles.list"),
                descriptor("agents.profiles.list") if not existing else descriptor("agents.existing"))
    value, host, _ = runtime(tmp_path, factory)
    if existing:
        original = descriptor("agents.existing", owner="fixture.previous")
        host.methods.register(original)
    with pytest.raises(DuplicateMethodError):
        value.start()
    assert host.methods.lookup("agents.capabilities") is None
    assert host.methods.lookup("agents.profiles.list") is None
    if existing:
        assert host.methods.lookup("agents.existing") is original


def test_factory_failure_closes_unit_scope_and_fences_retained_resolver(tmp_path):
    retained = []
    def factory(resolve):
        retained.append(resolve)
        resolve()
        raise RuntimeError("controlled factory failure")
    value, host, contexts = runtime(tmp_path, factory)
    with pytest.raises(RuntimeError, match="controlled factory failure"):
        value.start()
    assert host.methods.method_ids() == ()
    with pytest.raises(UnitAdmissionRefused):
        contexts[0].check_open()
    with pytest.raises(RuntimeCompositionUnavailable):
        retained[0]()
    assert len(contexts) == 1
    assert not value.owner.acquired


def test_later_start_failure_withdraws_methods_before_core_close(tmp_path):
    value, host, contexts = runtime(tmp_path, lambda resolve: (descriptor(handler=lambda _: resolve()),))
    original_close = value.unit_runtime.close
    observed = []
    def close():
        observed.append(host.methods.method_ids())
        original_close()
    value.unit_runtime.close = close
    class FailingHost(ServerPluginHost):
        def active_ids(self):
            return ("failing.fixture",)
        def active(self, identifier):
            class Active:
                registration = ServerPluginRegistration(start_hooks=(lambda: (_ for _ in ()).throw(RuntimeError("hook failed")),))
            return Active()
        def shutdown(self):
            pass
    value.plugin_host = FailingHost(methods=host.methods, stream_routes=StreamRouteRegistry(), data_root=tmp_path)
    with pytest.raises(RuntimeError, match="hook failed"):
        value.start()
    assert observed == [()]
    assert not value.owner.acquired


def test_plugin_cannot_impersonate_core_owner(tmp_path):
    _, host, _ = runtime(tmp_path, None)
    class Impersonator:
        built = False
        def descriptor(self):
            return ServerPluginDescriptor(id="pacthold.agents", display_name="Impersonator", version="1")
        def build(self, context):
            self.built = True
            return ServerPluginRegistration()
    plugin = Impersonator()
    with pytest.raises(InvalidDeclarationError, match="reserved"):
        host.activate(plugin)
    assert not plugin.built
    assert host.active_ids() == ()


def test_missing_unit_runtime_fails_without_alternate_admission(tmp_path):
    value, host, contexts = runtime(tmp_path, lambda resolve: (descriptor(),))
    value.unit_runtime = None
    with pytest.raises(RuntimeCompositionUnavailable):
        value.start()
    assert host.methods.method_ids() == ()
    assert contexts == []


def test_missing_environment_factory_fails_before_core_publication(tmp_path):
    value, host, contexts = runtime(tmp_path, lambda resolve: (descriptor(),))
    value.unit_runtime = UnitRuntimeOwner(tmp_path / "unavailable.sqlite")
    with pytest.raises(UnitGuaranteeUnavailable):
        value.start()
    assert host.methods.method_ids() == ()
    assert contexts == []


def test_plugin_method_cannot_claim_core_owner(tmp_path):
    _, host, _ = runtime(tmp_path, None)
    class Impersonator:
        def descriptor(self):
            return ServerPluginDescriptor(id="fixture.plugin", display_name="Fixture", version="1")
        def build(self, context):
            return ServerPluginRegistration(methods=(descriptor(),))
    with pytest.raises(InvalidDeclarationError):
        host.activate(Impersonator())
    assert host.active_ids() == ()
    assert host.methods.method_ids() == ()


def test_stop_hook_failure_still_withdraws_core_methods(tmp_path):
    value, host, contexts = runtime(tmp_path, lambda resolve: (descriptor(handler=lambda _: resolve()),))
    value.start()
    retained = host.methods.lookup("agents.capabilities")
    def failing_stop():
        raise RuntimeError("stop hook failed")
    host.run_stop_hooks = failing_stop
    with pytest.raises(RuntimeError, match="stop hook failed"):
        value.stop()
    assert host.methods.method_ids() == ()
    with pytest.raises(RuntimeCompositionUnavailable):
        retained.handler({})
    # Original host stop-hook failure semantics are preserved; finish this
    # fixture's owned resources explicitly rather than claiming full stop.
    host.run_stop_hooks = lambda: None
    value.stop()


def test_bare_runtime_without_factory_remains_empty(tmp_path):
    value, host, contexts = runtime(tmp_path, None)
    value.start()
    assert host.methods.method_ids() == ()
    assert contexts == []
    value.stop()


def test_concurrent_registry_preflight_and_publication_are_one_atomic_cut():
    registry = MethodRegistry()
    checked = Barrier(2)
    release_first = Event()
    second_checked = Event()
    second_started = Event()
    original = registry.check_register
    outcomes = []

    def instrumented(descriptor, **kwargs):
        if descriptor.owner == "fixture.first":
            original(descriptor, **kwargs)
            checked.wait(timeout=5)
            assert release_first.wait(5)
        else:
            second_checked.set()
            original(descriptor, **kwargs)

    registry.check_register = instrumented

    def publish(owner):
        if owner == "fixture.second":
            second_started.set()
        try:
            registry.register_batch((descriptor("agents.race", owner=owner),))
            outcomes.append((owner, "written"))
        except DuplicateMethodError:
            outcomes.append((owner, "conflict"))

    first = Thread(target=publish, args=("fixture.first",))
    second = Thread(target=publish, args=("fixture.second",))
    try:
        first.start()
        checked.wait(timeout=5)
        second.start()
        assert second_started.wait(5)
        # The first complete preflight still owns the registry publication
        # cut. A second claimant cannot validate against the absent old row.
        reached = second_checked.wait(0.1)
    finally:
        release_first.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)
    assert not reached
    assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == [("fixture.first", "written"), ("fixture.second", "conflict")]
    assert registry.lookup("agents.race").owner == "fixture.first"


def test_resolver_never_reopens_binding_after_round_factory(tmp_path, monkeypatch):
    captured = []
    def factory(resolve):
        captured.append(resolve)
        return (descriptor(handler=lambda params: resolve()),)
    value, host, contexts = runtime(tmp_path, factory)
    value.start()
    original = contexts[0]
    def reopen_forbidden():
        raise AssertionError('handler attempted to reopen binding')
    monkeypatch.setattr(value.unit_runtime, 'open', reopen_forbidden)
    assert captured[0]() is original
    value.stop()
    with pytest.raises(RuntimeCompositionUnavailable):
        captured[0]()
