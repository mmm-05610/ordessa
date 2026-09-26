"""The Server plugin host: registration, activation, lifecycle.

The registry here is the one dispatch truth for wire/1: every method's shape,
handler, availability predicate and owner travel as one atomic descriptor
(`server_plugin_api.ServerMethodDescriptor`). `WireService.dispatch` and
`WireService.hello` read only from this registry — there is no second method
table anywhere in the Server.

Lifecycle rules (each pinned by `apps/server/tests/test_plugin_host_gate.py`):

- Duplicate plugin ids, duplicate method ids, duplicate stream routes, and
  declarations that violate the contract refuse startup, not first request.
- `requires` forms a directed acyclic graph validated across the activation
  set; missing dependencies and cycles are startup refusals. It is also the
  access grant for dependency-provided ports, and unload refuses while a
  declared dependent is still active.
- An activation round is transactional at plugin granularity: if any
  activation fails, the plugins this round activated are disposed (reverse
  order) and the failure propagates; earlier-round plugins stay active. A
  disposal that raises during that rollback never stops the cleanups behind
  it: the round's own failure stays the primary exception and the disposal
  failures ride on its `cleanup_errors` attribute.
- A provided port that would shadow an existing binding (a host facade or
  another dependency's port) is a typed refusal, never a silent override.
- A plugin whose own activation fails rolls back its contributions and
  disposes what its build created; unrelated plugins stay active.
- Unload removes exactly the plugin's own methods/routes/ports and calls its
  disposal exactly once; shutdown disposes every active plugin exactly once,
  and one plugin's disposal raising never orphans the rest — the collected
  failures surface as one `CleanupError` after every plugin is released.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from server_plugin_api import (
    SERVER_PLUGIN_API_VERSION,
    CleanupError,
    CyclicDependencyError,
    DependencyError,
    DependentActiveError,
    DuplicateMethodError,
    DuplicatePluginError,
    DuplicateStreamRouteError,
    InvalidDeclarationError,
    PluginCleanupError,
    PortConflictError,
    ServerMethodDescriptor,
    ServerPlugin,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)

__all__ = ["MethodRegistry", "StreamRouteRegistry", "ServerPluginHost", "ActivePlugin"]


def _carry_cleanup_errors(errors: list[PluginCleanupError]) -> None:
    """Attach a rollback's disposal failures to the exception in flight.

    The plugin's own failure stays the primary exception; the cleanup facts
    ride on its `cleanup_errors` attribute so a caller can inspect what the
    rollback did on the way out. An exception object that refuses attributes
    still propagates unchanged."""
    import sys

    primary = sys.exc_info()[1]
    if primary is None:
        return
    try:
        primary.cleanup_errors = tuple(errors)
    except (AttributeError, TypeError):
        pass


class MethodRegistry:
    """The single wire/1 dispatch registry."""

    def __init__(self) -> None:
        self._methods: dict[str, ServerMethodDescriptor] = {}

    def register(self, descriptor: ServerMethodDescriptor) -> None:
        try:
            ServerMethodDescriptor(
                method_id=descriptor.method_id,
                required_params=frozenset(descriptor.required_params),
                optional_params=frozenset(descriptor.optional_params),
                handler=descriptor.handler,
                owner=descriptor.owner,
                availability=descriptor.availability,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidDeclarationError(f"{descriptor.method_id}: {exc}") from exc
        existing = self._methods.get(descriptor.method_id)
        if existing is not None:
            raise DuplicateMethodError(
                descriptor.method_id, existing.owner, descriptor.owner)
        self._methods[descriptor.method_id] = descriptor

    def unregister(self, method_id: str, *, owner: str) -> ServerMethodDescriptor | None:
        """Remove a row; absent rows are already gone (idempotent unload),
        but a row owned by someone else is never silently removed."""
        descriptor = self._methods.get(method_id)
        if descriptor is None:
            return None
        if descriptor.owner != owner:
            raise InvalidDeclarationError(
                f"method {method_id} is not owned by {owner!r}")
        del self._methods[method_id]
        return descriptor

    def lookup(self, method_id: str) -> ServerMethodDescriptor | None:
        return self._methods.get(method_id)

    def descriptors(self) -> tuple[ServerMethodDescriptor, ...]:
        return tuple(self._methods.values())

    def method_ids(self) -> tuple[str, ...]:
        return tuple(self._methods)

    def handler_view(self) -> dict[str, Any]:
        """`{method_id: handler}` in registration order (order-097's view)."""
        return {method_id: item.handler for method_id, item in self._methods.items()}

    def __len__(self) -> int:
        return len(self._methods)


class StreamRouteRegistry:
    """The stream surfaces admitted through host transport (ACP today)."""

    def __init__(self) -> None:
        self._routes: dict[str, StreamRouteDescriptor] = {}

    def register(self, descriptor: StreamRouteDescriptor) -> None:
        try:
            StreamRouteDescriptor(
                route_id=descriptor.route_id,
                resolver=descriptor.resolver,
                owner=descriptor.owner,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidDeclarationError(f"{descriptor.route_id}: {exc}") from exc
        existing = self._routes.get(descriptor.route_id)
        if existing is not None:
            raise DuplicateStreamRouteError(
                descriptor.route_id, existing.owner, descriptor.owner)
        self._routes[descriptor.route_id] = descriptor

    def unregister(self, route_id: str, *, owner: str) -> None:
        descriptor = self._routes.get(route_id)
        if descriptor is None:
            return
        if descriptor.owner != owner:
            raise InvalidDeclarationError(
                f"stream route {route_id} is not owned by {owner!r}")
        del self._routes[route_id]

    def resolve(self, route_id: str, connection_ref: str) -> Any | None:
        """Resolve one connection, or None: the host transport answers the
        typed close (`UNKNOWN_CONNECTION`) when nothing owns the reference."""
        descriptor = self._routes.get(route_id)
        if descriptor is None:
            return None
        return descriptor.resolver(connection_ref)


@dataclass
class ActivePlugin:
    descriptor: ServerPluginDescriptor
    registration: ServerPluginRegistration
    method_ids: tuple[str, ...] = ()
    stream_route_ids: tuple[str, ...] = ()


@dataclass
class ServerPluginHost:
    """Activates, tracks and disposes Server plugins over the registries."""

    methods: MethodRegistry = field(default_factory=MethodRegistry)
    stream_routes: StreamRouteRegistry = field(default_factory=StreamRouteRegistry)
    data_root: Any = None
    host_ports: Mapping[str, Any] = field(default_factory=dict)
    _active: dict[str, ActivePlugin] = field(default_factory=dict)
    _activation_order: list[str] = field(default_factory=list)

    # -- queries ------------------------------------------------------------

    def is_active(self, plugin_id: str) -> bool:
        return plugin_id in self._active

    def active_ids(self) -> tuple[str, ...]:
        return tuple(self._activation_order)

    def active(self, plugin_id: str) -> ActivePlugin:
        return self._active[plugin_id]

    def provided_port(self, name: str) -> Any | None:
        for plugin_id in reversed(self._activation_order):
            port = self._active[plugin_id].registration.provided_ports.get(name)
            if port is not None:
                return port
        return None

    def declared_shapes(self) -> dict[str, "tuple[frozenset[str], frozenset[str]]"]:
        """Every declared param shape behind the live table, by method id.

        Two sources, stated separately so a divergence between them stays
        visible: what each active plugin declared in its registration, and
        what the host registered itself (e.g. `server.hello`) — a registry
        row that is neither is a table entry with no declaration behind it.
        """
        shapes: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        plugin_rows: set[str] = set()
        for plugin_id in self._activation_order:
            for item in self._active[plugin_id].registration.methods:
                plugin_rows.add(item.method_id)
                shapes[item.method_id] = (item.required_params, item.optional_params)
        for item in self.methods.descriptors():
            if item.method_id not in plugin_rows:
                shapes[item.method_id] = (item.required_params, item.optional_params)
        return shapes

    # -- activation ---------------------------------------------------------

    def activate_all(self, plugins: Iterable[ServerPlugin]) -> tuple[ActivePlugin, ...]:
        """Activate a set of plugins in dependency order.

        The graph is validated across `requires` plus what is already active
        before anything is built: a missing dependency or a cycle refuses the
        whole round without touching any plugin. The round is transactional
        at plugin granularity: if any activation fails, the plugins *this
        round* activated are disposed (reverse order, exactly once each) and
        the failure propagates — a round that never became a runtime leaves
        nothing of itself behind. Plugins activated by earlier rounds are
        untouched.
        """
        requested = list(plugins)
        descriptors: dict[str, ServerPluginDescriptor] = {}
        by_id: dict[str, ServerPlugin] = {}
        for plugin in requested:
            descriptor = plugin.descriptor()
            if not isinstance(descriptor, ServerPluginDescriptor):
                raise InvalidDeclarationError(
                    f"descriptor() must return ServerPluginDescriptor, got {type(descriptor).__name__}")
            if descriptor.id in descriptors or descriptor.id in self._active:
                raise DuplicatePluginError(descriptor.id)
            if descriptor.api_version != SERVER_PLUGIN_API_VERSION:
                raise InvalidDeclarationError(
                    f"plugin {descriptor.id} declares api_version "
                    f"{descriptor.api_version}, host speaks {SERVER_PLUGIN_API_VERSION}")
            descriptors[descriptor.id] = descriptor
            by_id[descriptor.id] = plugin
        order = self._topological_order(descriptors)
        activated: list[ActivePlugin] = []
        try:
            for plugin_id in order:
                activated.append(self._activate_one(by_id[plugin_id], descriptors[plugin_id]))
        except BaseException:
            # Transactional at plugin granularity: every plugin this round
            # activated is disposed, reverse order. One plugin's disposal
            # raising never stops the cleanups behind it — the round's own
            # failure (the exception in flight) stays primary, and the
            # disposal failures ride on its `cleanup_errors` attribute.
            cleanup: list[PluginCleanupError] = []
            for active in reversed(activated):
                failure = self._dispose_active(active)
                if failure is not None:
                    cleanup.append(failure)
            if cleanup:
                _carry_cleanup_errors(cleanup)
            raise
        return tuple(activated)

    def activate(self, plugin: ServerPlugin) -> ActivePlugin:
        return self.activate_all([plugin])[0]

    def _topological_order(
        self, descriptors: Mapping[str, ServerPluginDescriptor],
    ) -> list[str]:
        """Dependency order over the requested set, with already-active ids
        counted as satisfied. Missing and cyclic requirements refuse startup."""
        for plugin_id, descriptor in descriptors.items():
            missing = tuple(
                dep for dep in descriptor.requires
                if dep not in descriptors and dep not in self._active
            )
            if missing:
                raise DependencyError(plugin_id, missing)
        order: list[str] = []
        state: dict[str, str] = {}

        def visit(plugin_id: str, stack: list[str]) -> None:
            mark = state.get(plugin_id)
            if mark == "done":
                return
            if mark == "visiting":
                cycle = stack[stack.index(plugin_id):] + [plugin_id]
                raise CyclicDependencyError(tuple(cycle))
            state[plugin_id] = "visiting"
            stack.append(plugin_id)
            for dep in descriptors[plugin_id].requires:
                if dep in descriptors:
                    visit(dep, stack)
            stack.pop()
            state[plugin_id] = "done"
            order.append(plugin_id)

        for plugin_id in descriptors:
            visit(plugin_id, [])
        return order

    def _activate_one(
        self, plugin: ServerPlugin, descriptor: ServerPluginDescriptor,
    ) -> ActivePlugin:
        # Ports are host facades plus what this plugin's *declared*
        # dependencies provide (they are active already — topological order
        # guaranteed it). A provided port that would shadow an existing
        # binding — a host facade or another dependency's port — is a typed
        # refusal, never a silent override. An undeclared plugin's ports are
        # not visible at all: `requires` is the access grant.
        ports = dict(self.host_ports)
        for dep in descriptor.requires:
            dep_active = self._active.get(dep)
            if dep_active is None:
                continue
            for port_name, port in dep_active.registration.provided_ports.items():
                if port_name in ports:
                    raise PortConflictError(descriptor.id, dep, port_name)
                ports[port_name] = port
        context = ServerPluginContext(
            plugin_id=descriptor.id, data_root=self.data_root, ports=ports,
        )
        registration = plugin.build(context)
        if not isinstance(registration, ServerPluginRegistration):
            raise InvalidDeclarationError(
                f"{descriptor.id}: build() must return ServerPluginRegistration")
        staged_methods: list[str] = []
        staged_routes: list[str] = []
        try:
            for item in registration.methods:
                if item.owner != descriptor.id:
                    raise InvalidDeclarationError(
                        f"{descriptor.id} declares method {item.method_id} "
                        f"owned by {item.owner!r}")
                self.methods.register(item)
                staged_methods.append(item.method_id)
            for item in registration.stream_routes:
                if item.owner != descriptor.id:
                    raise InvalidDeclarationError(
                        f"{descriptor.id} declares stream route {item.route_id} "
                        f"owned by {item.owner!r}")
                self.stream_routes.register(item)
                staged_routes.append(item.route_id)
        except BaseException:
            # Roll back only this plugin's staged contributions — and dispose
            # what build() already created: a plugin that never became active
            # must not leak the resources it built while failing.
            for method_id in staged_methods:
                self.methods.unregister(method_id, owner=descriptor.id)
            for route_id in staged_routes:
                self.stream_routes.unregister(route_id, owner=descriptor.id)
            if registration.disposal is not None:
                registration.disposal()
            raise
        active = ActivePlugin(
            descriptor=descriptor, registration=registration,
            method_ids=tuple(staged_methods), stream_route_ids=tuple(staged_routes),
        )
        self._active[descriptor.id] = active
        self._activation_order.append(descriptor.id)
        return active

    # -- unload / shutdown ----------------------------------------------------

    def _dispose_active(self, active: ActivePlugin) -> PluginCleanupError | None:
        """Tear one active plugin down; a raising disposal is captured and
        carried, never allowed to stop the cleanups behind it.

        The plugin's registrations were already revoked by `deactivate` before
        its disposal ran, so a captured failure is a hygiene fact, not a
        registry leak. A `DependentActiveError` here would mean the host tore
        down in the wrong order — that is a host bug and propagates."""
        try:
            self.deactivate(active.descriptor.id)
        except DependentActiveError:
            raise
        except Exception as err:  # noqa: BLE001 - captured, carried, never hidden
            return PluginCleanupError(active.descriptor.id, err)
        return None

    def deactivate(self, plugin_id: str) -> None:
        """Remove one plugin's contributions and dispose it exactly once.

        A plugin whose declared dependents are still active cannot be
        unloaded: that would orphan them mid-flight. Unload the dependent
        first (shutdown's reverse activation order does exactly that).
        """
        active = self._active.get(plugin_id)
        if active is None:
            raise InvalidDeclarationError(f"plugin {plugin_id!r} is not active")
        dependents = tuple(
            other_id for other_id in self._activation_order
            if other_id != plugin_id
            and plugin_id in self._active[other_id].descriptor.requires
        )
        if dependents:
            raise DependentActiveError(plugin_id, dependents)
        for method_id in active.method_ids:
            self.methods.unregister(method_id, owner=plugin_id)
        for route_id in active.stream_route_ids:
            self.stream_routes.unregister(route_id, owner=plugin_id)
        del self._active[plugin_id]
        self._activation_order.remove(plugin_id)
        if active.registration.disposal is not None:
            active.registration.disposal()

    def shutdown(self) -> None:
        """Dispose every active plugin exactly once, reverse activation order.

        One plugin's disposal raising never orphans the rest: every remaining
        plugin is still released, and the collected failures raise as one
        `CleanupError` after the loop — a shutdown that swallowed a disposal
        failure would be a silent lie."""
        cleanup: list[PluginCleanupError] = []
        for plugin_id in reversed(list(self._activation_order)):
            failure = self._dispose_active(self._active[plugin_id])
            if failure is not None:
                cleanup.append(failure)
        if cleanup:
            raise CleanupError(tuple(cleanup))
