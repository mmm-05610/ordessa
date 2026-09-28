"""Contract-only fakes for the platform contribution gates (T012).

Nothing here ships: these are the witness plugins and the point handler the
host-facing gates drive. A handler records every transaction call together
with the owner the host injected — so "the host, never the author, names
the owner" is checkable — and failures are injected as named exception
objects so a test can assert the exact fact stayed primary.
"""
from __future__ import annotations

from server_plugin_api import (
    SERVER_PLUGIN_API_VERSION,
    Contribution,
    ContributionBatch,
    ServerContributionHandler,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry


def new_host(**overrides):
    """A bare host: no point pre-registered, no core handler wired.

    The gates register their points explicitly — a host that pre-bound a
    handler for any point (least of all `pacthold.contributions`) would
    defeat the admission gates below and contradict the carrier contract.
    """
    kwargs = dict(methods=MethodRegistry(), stream_routes=StreamRouteRegistry())
    kwargs.update(overrides)
    return ServerPluginHost(**kwargs)


def method(method_id: str, owner: str) -> ServerMethodDescriptor:
    return ServerMethodDescriptor(
        method_id=method_id, required_params=frozenset({"requestId"}),
        optional_params=frozenset(), handler=lambda params: {"ok": method_id},
        owner=owner,
    )


class RecordingHandler(ServerContributionHandler):
    """A host-owned point handler that records every transaction call.

    Failures are injected per owner as the exact exception objects a test
    later identifies on the primary or in `cleanup_errors`. The recorder
    shows that every entry behind a raising rollback was still attempted.
    """

    def __init__(self, *, stage_raises=None, commit_raises=None, rollback_raises=None):
        self._stage_raises = dict(stage_raises or {})
        self._commit_raises = dict(commit_raises or {})
        self._rollback_raises = dict(rollback_raises or {})
        self.calls: list[tuple[str, str, str]] = []

    def stage(self, contribution: Contribution, owner: str):
        self.calls.append(("stage", contribution.point_id, owner))
        failure = self._stage_raises.get(owner)
        if failure is not None:
            raise failure
        return {"prepared": contribution.point_id, "owner": owner, "seq": len(self.calls)}

    def commit(self, contribution: Contribution, prepared, owner: str) -> None:
        self.calls.append(("commit", contribution.point_id, owner))
        failure = self._commit_raises.get(owner)
        if failure is not None:
            raise failure

    def rollback(self, contribution: Contribution, prepared, owner: str) -> None:
        self.calls.append(("rollback", contribution.point_id, owner))
        failure = self._rollback_raises.get(owner)
        if failure is not None:
            raise failure

    def names(self, call: str) -> list[tuple[str, str]]:
        return [(point, owner) for kind, point, owner in self.calls if kind == call]


class ContribPlugin:
    """A contract plugin whose registration may carry a contribution batch.

    `observe(context)` runs mid-build — the mid-round witness hook.
    `build_raises` is the plain activation-failure lever; `dispose_records`
    counts disposals owed to this plugin. `events` additionally records this
    plugin's own lifecycle phases (`("start"|"stop"|"dispose", id)`) so a
    gate can read the order the host ran them in.
    """

    def __init__(self, plugin_id: str, *, requires=(), methods=(), contributions=(),
                 ports=None, dispose_records=None, observe=None, build_raises=None,
                 events=None):
        self._descriptor = ServerPluginDescriptor(
            id=plugin_id, display_name=f"contrib {plugin_id}", version="1",
            api_version=SERVER_PLUGIN_API_VERSION, requires=tuple(requires))
        self._methods = tuple(methods)
        self._contributions = tuple(contributions)
        self._ports = dict(ports or {})
        self._dispose_records = dispose_records
        self._observe = observe
        self._build_raises = build_raises
        self._events = events
        self.builds = 0
        self.seen_ports: dict[str, object] = {}

    def descriptor(self) -> ServerPluginDescriptor:
        return self._descriptor

    def _recorder(self, kind: str):
        def _hook() -> None:
            self._events.append((kind, self._descriptor.id))
        return _hook

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        self.builds += 1
        plugin_id = self._descriptor.id
        self.seen_ports = dict(context.ports)
        if self._build_raises is not None:
            raise self._build_raises
        if self._observe is not None:
            self._observe(context)
        disposal = None
        if self._dispose_records is not None or self._events is not None:
            def _disposal():
                if self._dispose_records is not None:
                    self._dispose_records.append(plugin_id)
                if self._events is not None:
                    self._events.append(("dispose", plugin_id))
            disposal = _disposal
        start_hooks = () if self._events is None else (self._recorder("start"),)
        stop_hooks = () if self._events is None else (self._recorder("stop"),)
        return ServerPluginRegistration(
            methods=tuple(method(mid, plugin_id) for mid in self._methods),
            provided_ports=dict(self._ports),
            start_hooks=start_hooks,
            stop_hooks=stop_hooks,
            disposal=disposal,
            contributions=ContributionBatch(self._contributions),
        )


def contribution(point_id: str, api_version: str = "v1", payload=..., **flags) -> Contribution:
    """Shorthand: `payload=...` (the default) carries a distinct dict."""
    if payload is ...:
        payload = {"point": point_id, "version": api_version}
    return Contribution(point_id=point_id, api_version=api_version, payload=payload, **flags)
