"""T014-S1a: the server-stop phase, and the domain stop it keeps.

FR-006 forbids a specialised stop in the composition root. The host keeps a
*generic* phase — run the active round's `stop_hooks` in reverse activation
order, before any disposal — and the behaviour lives in the plugin that owns
the object:

- 032: the execution-port stop retired with `ordessa.server-compat` (the
  `execution.port` owner is gone; the product funnel still accepts the kwarg
  for call-site compatibility but no plugin owns it — asserted as absence
  below). The surviving domain stop in the default composition is the
  permissions backend's settled-world refusal (`permissions-backend`, whose
  `refuse_deactivation` aborts teardown while approvals are open);
- the managed ACP channel transport stop lives in `ordessa.harness.acp`
  (its own gate is in `packages/execution/kernel/tests/harness_kit/
  test_server_acp_stop_hook.py`, because that is where the registry lives —
  the default product composes no launch, so it declares no hook here).

The ordering rule the old code hardcoded ("channels stop first, so their run
records close with the honest server-stop reason while the ledger is still
up") is now carried by the activation DAG: a plugin that declared the
retired core in `requires` would activate last and stop first. With the
core retired the ACP facet requires only `ordessa.workspace`, and the
retired ordering edge is asserted as gone (re-adding the compat id to that
tuple must fail at activation, not silently re-order).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server_plugin_api import HostAdmissionClosedError, ServerPluginRegistration

from contribution_fakes import ContribPlugin, new_host

from ordessa_server.composition.runtime import build_runtime
from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


class Boom(RuntimeError):
    pass


class _RefusingStopPlugin:
    """A plugin whose stop hook refuses, and whose owner's hook records."""

    def __init__(self, plugin_id: str, *, requires: tuple[str, ...] = (),
                 events: list, refuse: bool) -> None:
        from server_plugin_api import SERVER_PLUGIN_API_VERSION, ServerPluginDescriptor

        self._descriptor = ServerPluginDescriptor(
            id=plugin_id, display_name=f"refusing {plugin_id}", version="1",
            api_version=SERVER_PLUGIN_API_VERSION, requires=tuple(requires))
        self._events = events
        self._refuse = refuse

    def descriptor(self):
        return self._descriptor

    def build(self, context):
        def hook() -> None:
            if self._refuse:
                raise Boom(f"{self._descriptor.id} refused to stop")
            self._events.append(("stop", self._descriptor.id))

        def dispose() -> None:
            self._events.append(("dispose", self._descriptor.id))

        return ServerPluginRegistration(stop_hooks=(hook,), disposal=dispose)


# -- the host's generic phase ------------------------------------------------


def test_stop_hooks_run_in_reverse_activation_order_before_any_disposal():
    """The whole rule the host is allowed to know: order, and phase placement.

    `fake.child` depends on `fake.owner`, so it activates last and stops
    first, and every stop precedes every disposal. Move the phase after the
    disposal pass, or run it in forward order, and this sequence is what fails.
    """
    events: list[tuple[str, str]] = []
    host = new_host()
    host.activate_all([
        ContribPlugin("fake.owner", methods=("fake.owner.method",), events=events),
        ContribPlugin("fake.child", methods=("fake.child.method",),
                      requires=("fake.owner",), events=events),
    ])
    assert host.active_ids() == ("fake.owner", "fake.child")
    host.run_stop_hooks()
    host.shutdown()
    assert events == [
        ("stop", "fake.child"), ("stop", "fake.owner"),
        ("dispose", "fake.child"), ("dispose", "fake.owner"),
    ]


def test_a_round_that_declared_no_stop_hooks_tears_down_without_inventing_one():
    """Honest absence: a plugin that declares nothing for the phase is not
    given a synthetic hook, and the phase still runs the ones that did."""
    events: list[tuple[str, str]] = []
    host = new_host()
    host.activate_all([
        ContribPlugin("quiet.plugin", methods=("quiet.method",)),
        ContribPlugin("loud.plugin", methods=("loud.method",), events=events),
    ])
    assert host.active("quiet.plugin").registration.stop_hooks == ()
    host.run_stop_hooks()
    assert events == [("stop", "loud.plugin")]


def test_a_raising_stop_hook_reaches_the_caller_and_ends_the_phase():
    """The refusal is the shutdown's answer, not a detail to tidy up.

    A stop that refuses aborts the phase — the hooks behind it and the
    disposal pass never run — because that is how the specialised stop
    behaved, and the caller (and the data-root lock) learns the Server did
    not settle. Turning this into carry-and-continue is a behaviour change;
    it is registered here, not smuggled in.
    """
    events: list[tuple[str, str]] = []
    host = new_host()
    host.activate_all([
        ContribPlugin("fake.owner", methods=("fake.owner.method",), events=events),
        _RefusingStopPlugin("fake.child", requires=("fake.owner",),
                            events=events, refuse=True),
    ])
    with pytest.raises(Boom):
        host.run_stop_hooks()
    assert events == []
    host.shutdown()
    assert events == [("dispose", "fake.child"), ("dispose", "fake.owner")]


def test_stop_hooks_refuse_while_an_activation_round_is_draining():
    """Every mid-round entry point refuses; the teardown phase is one of them.

    Running stop hooks against a round that is still staging would tear down
    a plugin whose ports a later plugin in the same round has not resolved
    yet — the half-round the draining window exists to hide.
    """
    host = new_host()
    seen: list[str] = []

    def observe(_context):
        with pytest.raises(HostAdmissionClosedError):
            host.run_stop_hooks()
        seen.append("refused")

    host.activate_all([ContribPlugin("fake.round", observe=observe)])
    assert seen == ["refused"]


def test_unloading_one_plugin_does_not_run_the_server_stop_phase():
    """The phase is the Server's own teardown, not a per-plugin unload hook.

    `deactivate` keeps revoking routes and disposing exactly as before: a
    stop hook belongs to shutting the whole round down. Pinning this keeps a
    later slice from "helpfully" firing teardown hooks on unload and calling
    it the same rule.
    """
    events: list[tuple[str, str]] = []
    host = new_host()
    host.activate_all([ContribPlugin("fake.single", methods=("fake.single.m",),
                                     events=events)])
    host.deactivate("fake.single")
    assert events == [("dispose", "fake.single")]


# -- the composition runs the phase, knowing no domain -----------------------


def test_the_runtime_stop_runs_the_active_rounds_phase(tmp_path):
    """`ServerRuntime.stop()` reaches the phase through the host only."""
    events: list[tuple[str, str]] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[
        ContribPlugin("fake.stopped", methods=("fake.stopped.method",), events=events),
    ])
    runtime.start()
    runtime.stop()
    assert events == [("start", "fake.stopped"), ("stop", "fake.stopped"),
                      ("dispose", "fake.stopped")]
    assert runtime.owner.acquired is False


def test_a_bare_runtime_stop_invents_no_hook_for_a_plugin_that_declared_none(tmp_path):
    events: list[tuple[str, str]] = []
    runtime = build_runtime(tmp_path / "data", server_plugins=[])
    runtime.start()
    runtime.stop()
    assert events == []
    assert runtime.owner.acquired is False


# -- the ordering the old code hardcoded is now the DAG's ---------------------


def test_the_default_product_composition_stops_the_channel_owner_before_the_ledger(tmp_path):
    """Reverse activation order gives the order, because of `requires`.

    032: the retired compatibility core is gone from both the activation
    list and the ACP facet's `requires`. The assertion is the surviving
    dependency — the ACP facet requires `ordessa.workspace`, so it sits on
    top of it and comes off first — plus the retirement itself: the compat
    id is absent from the round and cannot be re-required.
    """
    from ordessa_server.composition.native_channels.plugin import AcpChannelServerPlugin

    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.harness.acp",
            "ordessa.model-provider", "ordessa.sandbox",
            "ordessa.sandbox-adapters", "permissions-backend",
            "ordessa.permissions-adapters")
    finally:
        runtime.stop()

    assert AcpChannelServerPlugin().descriptor().requires == ("ordessa.workspace",)
    assert "ordessa.server-compat" not in runtime.plugin_host.active_ids()


def test_the_default_composition_declares_no_execution_stop_without_a_port(tmp_path):
    """Honest absence at the product surface, 032 form: the execution domain
    retired with the compat plugin, so no active plugin provides
    `execution.port` and no stop hook answers for it — a stop is clean."""
    runtime = build_runtime(tmp_path / "data")
    try:
        assert "ordessa.server-compat" not in runtime.plugin_host.active_ids()
        assert runtime.plugin_host.provided_port("execution.port") is None
        for plugin_id in runtime.plugin_host.active_ids():
            assert runtime.plugin_host.active(plugin_id).registration.stop_hooks == () or (
                plugin_id == "permissions-backend"), plugin_id
    finally:
        runtime.stop()


# -- destination, 032 form: the execution stop retired WITH its owner --------
#
# The three tests below previously proved the execution stop moved from the
# composition root to the compat plugin. That owner is deleted
# (docs/implementation/specifications/032-architecture-cleanup); the product funnel accepts the kwarg but
# routes it nowhere. The replacement coverage is:
# - the funnel-accepts-but-owns-nothing absence (S1d file pins the same fact
#   through the product seam);
# - the surviving domain-stop refusal, owned by permissions-backend (below).
# What is NOT kept: SERVER_STOP_TIMEOUT as a live refusal — its owner and
# its port are gone, and reviving them would be a hidden compat chain.


class _SettlingPort:
    """A retired-domain sentinel: its `stop()` must never be called, because
    no plugin owns the retired `execution.port` anymore."""

    def __init__(self) -> None:
        self.stops = 0

    def stop(self) -> bool:
        self.stops += 1
        return True


class _NoStopPort:
    """A port that never had a stop — the retired guard's subject."""


def test_the_retired_execution_funnel_routes_nowhere_and_stops_clean(tmp_path):
    """The compat funnel accepts the retired fact but owns nothing: the port
    is unprovided, no stop hook answers for it, and the stop is clean."""
    port = _SettlingPort()
    # T014-S1d: the execution injection reaches the owning plugin through
    # the product's compat funnel — 032: there is no owning plugin anymore,
    # so the injection is accepted and dropped, never touching the host.
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(execution=port))
    runtime.start()
    runtime.stop()
    assert port.stops == 0
    assert runtime.plugin_host.provided_port("execution.port") is None
    assert runtime.owner.acquired is False


def test_a_settled_permissions_stop_closes_the_round_from_the_owning_plugin(tmp_path):
    """The surviving domain stop: `permissions-backend` owns the settled-world
    refusal, and a settled world stops clean — the host phase reaches the
    owner's hook through reverse activation order, before any disposal.

    The refusal itself aborts the teardown while approvals are open (a busy
    stop raises `PermissionsBackendBusyError` and the round stays active);
    that half is pinned where the facts live (the permissions backend
    suite). Here the settled path proves the hook is wired: the stop runs
    the owner's hook and releases the data root.
    """
    from ordessa_permissions_backend.plugin import PLUGIN_ID as PERMISSIONS_PLUGIN_ID

    runtime = build_runtime(tmp_path / "data")
    runtime.start()
    provider = runtime.plugin_host.active(PERMISSIONS_PLUGIN_ID)
    assert len(provider.registration.stop_hooks) == 1
    runtime.stop()
    assert runtime.plugin_host.active_ids() == ()
    assert runtime.owner.acquired is False


def test_a_port_without_a_stop_is_left_alone(tmp_path):
    """The old `hasattr(self.execution, "stop")` guard retired with the port:
    injecting a stop-less sentinel through the retired funnel is accepted and
    dropped — the stop stays clean and the host gains no attribute."""
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(execution=_NoStopPort()))
    runtime.start()
    runtime.stop()
    assert runtime.owner.acquired is False


def test_the_host_composition_root_carries_no_domain_stop_vocabulary():
    """The removal, asserted at the source rather than argued.

    `ServerRuntime.stop()` may not name the channel registry, the execution
    port or the timeout code again. The facade table may still *bind* those
    fields — that is slice S1b's removal, and this slice leaves the bag
    working — but the lifecycle code no longer reads it.
    """
    import ordessa_server.composition.runtime as runtime_module

    source = Path(runtime_module.__file__).read_text(encoding="utf-8")
    stop_body = source.split("    def stop(self) -> None:", 1)[1].split("\ndef ", 1)[0]
    for vocabulary in ("acp_channels", "execution", "SERVER_STOP_TIMEOUT", "stop_all"):
        assert vocabulary not in stop_body, f"stop() still names {vocabulary!r}"
    assert "run_stop_hooks" in stop_body
