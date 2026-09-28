"""Where the ACP channel teardown moved: the Harness plugin's own stop hook.

`ServerRuntime.stop()` used to reach `runtime.acp_channels` and call
`stop_all()` because the host happened to know what that attribute was.
FR-006 says it may not. The registry, its transports and its run records all
belong to `ordessa.harness.acp`, so the stop is declared there — and the
reason it stays the honest one is asserted here, at the object that writes
the record:

* a live channel's transport is terminated and its run ends carrying
  `server-stop`, not "released" and not a silent success;
* the hook is that same registry instance the plugin publishes as its
  `acp.channels` port — not a re-lookup through a host bag;
* a composition without a launch declares no hook at all (absence, not a
  no-op invention).

The ledger-still-up half of the old comment is a lifecycle-order fact, so it
is pinned where the order lives: `apps/server/tests/platform/
test_platform_stop_hooks.py`.
"""
from __future__ import annotations

from server_plugin_api import ServerPluginContext

from ordessa_harness.server_acp.plugin import PLUGIN_ID, AcpChannelServerPlugin


class _Ledger:
    """The product's own session-ledger face, reduced to what a run record needs."""

    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []

    def create_session(self, **_kwargs):
        return "accepted", {"session_id": "sess-1"}

    def create_turn(self, **_kwargs):
        return True, "accepted", {"turn_id": "turn-1"}

    def finish_cancelled(self, execution_id, *, terminal_reason):
        self.cancelled.append((str(execution_id), str(terminal_reason)))


class _Profiles:
    def get(self, profile_id):
        return {"config_revision": 0, "config_object_digest": "sha256:profile"}


class _Transport:
    """A started channel transport: it records being terminated, nothing else."""

    def __init__(self) -> None:
        self.terminated = 0

    def terminate(self) -> None:
        self.terminated += 1


def _build(plugin: AcpChannelServerPlugin, ledger: _Ledger):
    return plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=None,
        ports={
            "workspace.service": object(),
            "sessions.records": ledger,
            "profiles.records": _Profiles(),
        },
    ))


def test_the_plugin_stops_its_channel_with_the_server_stop_reason(tmp_path):
    """The moved stop, asserted through the behaviour it must not lose.

    Run the hook the plugin declared (not the registry helper directly) and
    the live channel still ends as a server-stop with its transport
    terminated and its ownership released. Re-point the hook at a no-op, or
    let it claim a plain "released", and both assertions go red.
    """
    transport = _Transport()
    ledger = _Ledger()
    plugin = AcpChannelServerPlugin(
        launch=lambda **_kwargs: transport,
        native_identity=lambda: {"mode": "native", "harness": "pi", "profileId": "p1"},
    )
    registration = _build(plugin, ledger)
    registry = registration.provided_ports["acp.channels"]
    registry.acquire(harness_id="pi", workspace_id="ws-1",
                     profile_id="p1", cwd=str(tmp_path))

    assert len(registration.stop_hooks) == 1
    assert registration.stop_hooks[0] == registry.stop_all
    registration.stop_hooks[0]()

    assert transport.terminated == 1
    assert ledger.cancelled == [("turn-1", "server-stop")]
    assert registry.release("no-such-connection") is None  # ownership is gone


def test_a_relaunching_registry_is_stopped_through_its_own_instance(tmp_path):
    """A second `build` publishes a second registry; the hook stops that one.

    The old host read a facade field and could be handed the previous
    round's object — the reviewer's stop→start counterexample. A hook bound
    to the instance the same build published cannot be.
    """
    ledger = _Ledger()
    first = _Transport()
    plugin = AcpChannelServerPlugin(launch=lambda **_kwargs: first)
    first_registration = _build(plugin, ledger)
    second = _Transport()
    plugin._launch = lambda **_kwargs: second
    second_registration = _build(plugin, ledger)

    assert first_registration.stop_hooks[0] != second_registration.stop_hooks[0]
    second_registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="ws-2", profile_id="p2", cwd=str(tmp_path))
    second_registration.stop_hooks[0]()
    assert second.terminated == 1
    assert first.terminated == 0


def test_a_composition_without_a_launch_declares_no_stop_hook():
    plugin = AcpChannelServerPlugin()
    registration = plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=None,
        ports={"workspace.service": object(), "sessions.records": _Ledger(),
               "profiles.records": _Profiles()},
    ))
    assert registration.provided_ports["acp.channels"] is None
    assert registration.stop_hooks == ()
