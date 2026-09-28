"""T014-S1a: the server-stop phase, and the two domain stops it moved.

FR-006 forbids a specialised stop in the composition root. The host keeps a
*generic* phase — run the active round's `stop_hooks` in reverse activation
order, before any disposal — and the behaviour moves to the plugins that own
the objects:

- the managed ACP channel transport stop → `ordessa.harness.acp` (its own
  gate lives in `plugins/harness/tests/test_server_acp_stop_hook.py`, because
  that is where the registry lives);
- the execution port stop, `SERVER_STOP_TIMEOUT` refusal included →
  `ordessa.server-compat` (tested here through the real composition, since
  `plugins/server-compat` has no test tree of its own).

The ordering rule the old code hardcoded ("channels stop first, so their run
records close with the honest server-stop reason while the ledger is still
up") is now carried by the activation DAG: the ACP facet declares
`requires=("ordessa.workspace", "ordessa.server-compat")`, so it activates
last and therefore stops first, while the compatibility core — the owner of
the records it writes through — is still active and not yet disposed. The
counterexample below is that dependency itself: drop `ordessa.server-compat`
from the tuple and the DAG no longer promises the order.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server_plugin_api import HostAdmissionClosedError, ServerPluginRegistration

from contribution_fakes import ContribPlugin, new_host

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition


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
    """Reverse activation order gives the frozen order, because of `requires`.

    The assertion is the dependency, not the resulting list: the ACP facet
    declares the compatibility core, so it sits on top of it and comes off
    first. Remove `ordessa.server-compat` from that tuple and the second
    assertion goes red — the guarantee goes with it, which is the honest way
    for a teardown order to depend on a declared edge.
    """
    from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin
    from ordessa_server_compat.plugin import ServerCompatPlugin

    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
            "ordessa.sandbox", "ordessa.sandbox-adapters",
            "ordessa.permissions-adapters")
    finally:
        runtime.stop()

    assert set(AcpChannelServerPlugin().descriptor().requires) == {
        "ordessa.workspace", "ordessa.server-compat"}
    assert ServerCompatPlugin().descriptor().requires == ("ordessa.workspace",)


def test_the_default_composition_declares_no_execution_stop_without_a_port(tmp_path):
    """Honest absence at the product surface: no execution port composed, so
    the compatibility plugin declares no stop hook and a stop is clean."""
    runtime = build_runtime(tmp_path / "data")
    try:
        compat = runtime.plugin_host.active("ordessa.server-compat")
        assert compat.registration.provided_ports["execution.port"] is None
        assert compat.registration.stop_hooks == ()
    finally:
        runtime.stop()


# -- destination: the execution stop, refusal included, is the compat plugin's --


class _SettlingPort:
    """An execution port whose `stop()` answers whether its runs settled."""

    def __init__(self, *, settles: bool = True) -> None:
        self.stops = 0
        self._settles = settles

    def stop(self) -> bool:
        self.stops += 1
        return self._settles


class _NoStopPort:
    """A port that never had a stop — the old `hasattr` guard's subject."""


def test_the_execution_port_is_stopped_once_by_the_plugin_that_owns_it(tmp_path):
    port = _SettlingPort()
    # T014-S1d: the execution injection reaches the owning plugin through
    # the product's compat funnel, not through the host's parameter bag.
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(execution=port))
    runtime.start()
    runtime.stop()
    assert port.stops == 1
    assert runtime.owner.acquired is False


def test_an_unsettled_execution_stop_refuses_the_shutdown_from_the_plugin(tmp_path):
    """`SERVER_STOP_TIMEOUT` survives the move, and stays a domain fact.

    The refusal now comes from `ordessa_server_compat.plugin`, not from the
    composition root, and it still aborts the teardown before the plugins are
    disposed and before the data root is released — a Server that could not
    settle its runs did not finish stopping, and says so out loud.
    """
    port = _SettlingPort(settles=False)
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(execution=port))
    runtime.start()
    with pytest.raises(RuntimeError, match="SERVER_STOP_TIMEOUT"):
        runtime.stop()
    assert port.stops == 1
    assert runtime.plugin_host.active_ids()
    assert runtime.owner.acquired is True
    try:
        runtime.plugin_host.shutdown()
    finally:
        runtime.owner.release()


def test_a_port_without_a_stop_is_left_alone(tmp_path):
    """The old `hasattr(self.execution, "stop")` guard moved with the stop."""
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
    import ordessa_server.bootstrap.runtime as runtime_module

    source = Path(runtime_module.__file__).read_text(encoding="utf-8")
    stop_body = source.split("    def stop(self) -> None:", 1)[1].split("\ndef ", 1)[0]
    for vocabulary in ("acp_channels", "execution", "SERVER_STOP_TIMEOUT", "stop_all"):
        assert vocabulary not in stop_body, f"stop() still names {vocabulary!r}"
    assert "run_stop_hooks" in stop_body
