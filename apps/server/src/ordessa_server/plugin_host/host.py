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
- `run_stop_hooks()` is the shutdown counterpart of a start round's
  `start_hooks`: every active plugin's stop hooks run in reverse activation
  order, before any disposal, so a plugin tears down while the round whose
  ports it consumed is still alive. The host names no hook target and knows
  nothing about what a hook stops — the phase is the seam, the behaviour
  belongs to the plugin that owns the object.

Contribution-round rules (each pinned by `apps/server/tests/platform/`):

- Extension points are host-declared (`register_contribution_point`): point
  id, accepted api_version, optional handler, exclusivity. Authors only
  declare contributions; a handler and an owner are the host's to inject,
  never the author's to pick. A contribution to an unregistered or
  handler-less point, one with the wrong api_version, or one claiming an
  exclusively-held point (retire first, always) is a typed admission
  refusal — never a silent last-wins and never a silently dropped entry.
- A registration's contribution batch is staged during the plugin's
  activation and committed only after every plugin in the round staged
  successfully; publication is one registry swap at the end of the commit
  pass. While the round is staging or committing, the host is `draining`:
  a reentrant activation, deactivation, shutdown or point registration is
  a typed refusal naming the state. A consumer resolving a contribution
  mid-round sees the previous committed view — a half batch is not a
  value it can ever receive.
- A commit failure (or any round failure before publication) rolls the
  round's staged batches back in reverse, undoing already-committed
  entries through their handlers; the carry-not-swallow rule applies:
  every entry is attempted and a raising rollback rides on the round's
  primary failure as a `cleanup_errors` fact. The affected plugins'
  methods, routes and ports retire with their batch.
- Consumers resolve through the host (`host.contribution(point_id)` /
  `host.use_contribution` for a versioned `payload+api_version+owner`
  view), never through a captured reference, and a named `consumer` is
  granted access only by `requires` on the owner — the carrier shares the
  port-visibility rule, it does not bypass it. A point carrying several
  published owners has no single view on either path: the argument-less
  one answers an observable absence naming the count, the granted one
  refuses with `ContributionAmbiguousError` naming every owner. Neither
  picks by registration order; `contributions(point_id)` is the multi-view
  answer.
- Retirement is the unregister path: deactivating an owner unpublishes
  exactly that owner's entries (observable immediately), attempted entry by
  entry in reverse even when a rollback raises. While a consumer holds a
  live resolution, `owner_busy` is true and deactivating that owner is a
  typed refusal naming it — no live reference is ever stolen.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping

from server_plugin_api import (
    SERVER_PLUGIN_API_VERSION,
    AbsentContribution,
    CleanupError,
    Contribution,
    ContributionAccessError,
    ContributionAmbiguousError,
    ContributionBatch,
    ContributionBatchCleanupError,
    ContributionCleanupError,
    ContributionOwnerBusyError,
    ContributionPointHeldError,
    ContributionPointUnboundError,
    ContributionVersionRefusedError,
    CyclicDependencyError,
    DependencyError,
    DependentActiveError,
    DuplicateHttpRouteError,
    DuplicateMethodError,
    DuplicatePluginError,
    DuplicateStreamRouteError,
    HostAdmissionClosedError,
    HttpRouteDescriptor,
    HttpRouteShapeChangedError,
    HttpRouteUnmountedError,
    InvalidDeclarationError,
    PluginCleanupError,
    PortConflictError,
    ServerMethodDescriptor,
    ServerPlugin,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginError,
    ServerPluginRegistration,
    StagedBatch,
    StreamRouteDescriptor,
    stage_contributions,
)

from .contribution_points import (
    ContributionPointRegistry,
    PublishedRecord,
    ResolvedContribution,
)

__all__ = [
    "MethodRegistry", "StreamRouteRegistry", "HttpRouteRegistry",
    "ServerPluginHost", "ActivePlugin",
    "ContributionPointRegistry", "ResolvedContribution",
]


def _route_signature(endpoint) -> str:
    """The endpoint's FastAPI-visible parameter shape, as a stable string:
    what the mounted route's request machinery was built against."""
    import inspect

    return str(inspect.signature(endpoint))


def _carry_cleanup_errors(errors: list[ServerPluginError]) -> None:
    """Attach a rollback's disposal failures to the exception in flight.

    The plugin's own failure stays the primary exception; the cleanup facts
    ride on its `cleanup_errors` attribute so a caller can inspect what the
    rollback did on the way out. Attachments ACCUMULATE: a staging rollback
    and the round-level rollback both contribute to the same failure. An
    exception object that refuses attributes still propagates unchanged."""
    import sys

    primary = sys.exc_info()[1]
    if primary is None:
        return
    try:
        existing = getattr(primary, "cleanup_errors", ())
        primary.cleanup_errors = tuple(existing) + tuple(errors)
    except (AttributeError, TypeError):
        pass


def _undo_records(records: Iterable[PublishedRecord]) -> list[ContributionCleanupError]:
    """Attempt every rollback in `records`, containing each failure.

    The round-rollback worker: one raising handler never stops the records
    behind it and never becomes the caller's primary — each failure comes
    back as a `ContributionCleanupError` fact to be carried."""
    cleanup: list[ContributionCleanupError] = []
    for record in records:
        try:
            record.handler.rollback(record.contribution, record.prepared, record.owner)
        except Exception as err:  # noqa: BLE001 - carried, never primary
            cleanup.append(ContributionCleanupError(record.owner,
                                                    record.contribution.point_id, err))
    return cleanup


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


class HttpRouteRegistry:
    """Business HTTP routes plugins contribute, admitted through the host's
    transport wall (bearer auth, loopback policy, error sanitisation).

    One path with overlapping methods has exactly one owner: a second claim
    is a typed refusal at activation, never a registration-order race."""

    def __init__(self) -> None:
        self._routes: list[HttpRouteDescriptor] = []

    def register(self, descriptor: HttpRouteDescriptor) -> None:
        try:
            HttpRouteDescriptor(
                path=descriptor.path, methods=descriptor.methods,
                endpoint=descriptor.endpoint, owner=descriptor.owner,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidDeclarationError(f"{descriptor.path}: {exc}") from exc
        for existing in self._routes:
            if existing.path == descriptor.path:
                overlap = existing.methods & descriptor.methods
                if overlap:
                    raise DuplicateHttpRouteError(
                        descriptor.path, tuple(overlap),
                        existing.owner, descriptor.owner)
        self._routes.append(descriptor)

    def unregister_owner(self, owner: str) -> None:
        self._routes = [item for item in self._routes if item.owner != owner]

    def descriptors(self) -> tuple[HttpRouteDescriptor, ...]:
        return tuple(self._routes)


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
    http_routes: HttpRouteRegistry = field(default_factory=HttpRouteRegistry)
    #: The host-owned contribution point registry: point declarations,
    #: the published view consumers resolve through, and the in-flight
    #: holds behind `owner_busy`. Composition registers points on the
    #: host; authors never touch this object.
    contribution_points: ContributionPointRegistry = field(
        default_factory=ContributionPointRegistry)
    # Selection+acquire and busy-check+retire share this lock. A lease never
    # holds it across consumer code, only across the lifecycle transitions.
    _contribution_lifecycle_lock: Any = field(
        default_factory=RLock, init=False, repr=False, compare=False)
    #: The per-composition wire/1 error-family aggregate (T014-S2a-R): the
    #: published/staged contributed rows are composition state owned by THIS
    #: host, built in `__post_init__` through the point declaration and
    #: written only through that point's handler. Consumers resolve through
    #: it (the composition root hands `wire_error_families.family_for` to
    #: the transport at construction); a second host in the same process
    #: sees none of these rows. None only if the declaration below ever
    #: moves out of `__post_init__`.
    wire_error_families: Any = None
    #: The per-composition `server.hello` discovery-facet aggregate
    #: (T014-S3): the published/staged projectors are composition state owned
    #: by THIS host, built in `__post_init__` through the point declaration
    #: and written only through that point's handler. The transport resolves
    #: them the same way it resolves the family table — one callable handed
    #: over at construction, never module state — so two live compositions in
    #: one process publish nothing into each other's hello. None only if the
    #: declaration below ever moves out of `__post_init__`.
    wire_discovery_facets: Any = None
    #: The route shapes the live transport mounted at its startup — None
    #: until a transport freezes them. Each entry is
    #: (path, methods, owner, authenticated, endpoint-signature). While
    #: frozen, a plugin activation declaring HTTP routes outside this set
    #: refuses type-wise (never mounted), and one re-declaring a mounted
    #: route with a changed auth flag or signature refuses too: the running
    #: app would otherwise serve the new registration behind the wall and
    ## call shape the first mount installed.
    frozen_http_routes: "frozenset[tuple[str, frozenset[str], str, bool, str]] | None" = None
    data_root: Any = None
    host_ports: Mapping[str, Any] = field(default_factory=dict)
    _active: dict[str, ActivePlugin] = field(default_factory=dict)
    _activation_order: list[str] = field(default_factory=list)
    # Retirement removes the publication before invoking an author's rollback
    # and disposal. Keep the owner reserved until both callbacks finish.
    _retiring_owners: set[str] = field(default_factory=set, init=False, repr=False)
    #: Round state, alive only while `activate_all` is in flight: a depth
    #: marker (the draining window), the batches staged this round, the
    #: batches whose commit already ran (undone through their handlers),
    #: and the exclusive point-ids claimed by staged work (a claim is
    #: round-local until published).
    _round_depth: int = field(default=0, repr=False)
    _round_staged: "list[tuple[str, StagedBatch, Any]]" = field(
        default_factory=list, repr=False)
    _round_committed: "list[tuple[str, StagedBatch, Any]]" = field(
        default_factory=list, repr=False)
    _round_claims: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Declare the host's own extension points at host construction.

        `wire.error-families` (T014-S2a) is the host's wire/1 seam: business
        error codes reach the family table as contributions from the
        components that raise them, and the host aggregates them with
        conflict validation (two owners, one code, two families = a refused
        round, never an activation-order pick). The point must exist before
        the first registration stages its batch, and `bootstrap` builds no
        separate composition step for it, so the host that owns the point
        declares it — the knowledge is the point id and the open/exclusive
        fact, never a business row (the handler lives in `wire.errors`).
        Imported lazily: `wire.errors` needs no host-side wiring of its own.

        `wire.discovery-facets` (T014-S3) is declared the same way for the
        same reason: `server.hello`'s domain members (which harnesses this
        Server can run, and whose native identity it runs as) arrive as
        projectors published by the domain that can answer them, and the host
        keeps only the envelope and the aggregation. Its handler names no
        facet either (the rules are in `wire.discovery`).
        """
        from ordessa_server.wire.discovery import (
            declare_wire_discovery_facets_point,
        )
        from ordessa_server.wire.errors import declare_wire_error_families_point

        declare_wire_error_families_point(self)
        declare_wire_discovery_facets_point(self)

    # -- queries ------------------------------------------------------------

    @property
    def state(self) -> str:
        """`open` when admission runs, `draining` while an activation round
        stages or commits (the half batch is not a value consumers may
        see)."""
        return "draining" if self._round_depth else "open"

    @property
    def admission_open(self) -> bool:
        return self._round_depth == 0

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

        Contribution batches ride the same transaction: each plugin's batch
        stages inside its own activation (no publish), the round commits only
        after every plugin staged, and publication is one swap at the end.
        A failure anywhere in staging or committing rolls the staged work
        back (reverse; committed entries undone through their handlers) and
        retires the affected plugins' methods/routes/ports with it. While
        the round is in flight the host is `draining`: a reentrant
        activation is a typed refusal, and a consumer resolution answers
        with the previous committed view, never a half batch.
        """
        self._require_admission_open("plugin activation")
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
        with self._contribution_lifecycle_lock:
            self._require_admission_open("plugin activation")
            retiring = set(descriptors) & self._retiring_owners
            if retiring:
                raise InvalidDeclarationError(
                    f"plugin owner {sorted(retiring)[0]!r} is retiring; activation waits for cleanup")
            if any(plugin_id in self._active for plugin_id in descriptors):
                raise DuplicatePluginError(next(plugin_id for plugin_id in descriptors
                                                if plugin_id in self._active))
            order = self._topological_order(descriptors)
            self._round_depth = 1
        activated: list[ActivePlugin] = []
        try:
            for plugin_id in order:
                activated.append(self._activate_one(by_id[plugin_id], descriptors[plugin_id]))
            self._commit_round_contributions()
        except BaseException:
            # Transactional at plugin granularity: every plugin this round
            # activated is disposed, reverse order. One plugin's disposal
            # raising never stops the cleanups behind it — the round's own
            # failure (the exception in flight) stays primary, and the
            # disposal failures ride on its `cleanup_errors` attribute.
            # The contribution rollback joins that ledger: staged batches
            # are undone and committed-but-unpublished entries go back
            # through their handlers, every entry attempted.
            cleanup: list[ServerPluginError] = self._rollback_round_contributions()
            for active in reversed(activated):
                failure = self._dispose_active(active)
                if failure is not None:
                    cleanup.append(failure)
            if cleanup:
                _carry_cleanup_errors(cleanup)
            raise
        finally:
            self._round_depth = 0
            self._round_staged = []
            self._round_committed = []
            self._round_claims = {}
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
            if self.frozen_http_routes is not None and registration.http_routes:
                unmounted: list[str] = []
                reshaped: list[str] = []
                for item in registration.http_routes:
                    mounted_shape = next(
                        (shape for shape in self.frozen_http_routes
                         if shape[:3] == (item.path, frozenset(item.methods), item.owner)),
                        None)
                    label = f"{item.path} ({', '.join(sorted(item.methods))})"
                    if mounted_shape is None:
                        unmounted.append(label)
                    elif (mounted_shape[3] != item.authenticated
                          or mounted_shape[4] != _route_signature(item.endpoint)):
                        reshaped.append(label)
                if unmounted:
                    raise HttpRouteUnmountedError(descriptor.id, tuple(unmounted))
                if reshaped:
                    raise HttpRouteShapeChangedError(descriptor.id, tuple(reshaped))
            for item in registration.http_routes:
                if item.owner != descriptor.id:
                    raise InvalidDeclarationError(
                        f"{descriptor.id} declares http route {item.path} "
                        f"owned by {item.owner!r}")
                self.http_routes.register(item)
            # The C2 carrier: the registration's contribution batch STAGES
            # here (validated against the host's point registry, handler
            # stage called, owner injected) and publishes only when the
            # whole round commits.
            self._stage_contributions(descriptor.id, registration.contributions)
        except BaseException:
            # Roll back only this plugin's staged contributions — and dispose
            # what build() already created: a plugin that never became active
            # must not leak the resources it built while failing. A disposal
            # that raises here is contained and carried on the in-flight
            # failure's `cleanup_errors` — it may never replace the typed
            # conflict (or whatever else) that caused the rollback.
            cleanup: list[PluginCleanupError] = []
            for method_id in staged_methods:
                self.methods.unregister(method_id, owner=descriptor.id)
            for route_id in staged_routes:
                self.stream_routes.unregister(route_id, owner=descriptor.id)
            self.http_routes.unregister_owner(descriptor.id)
            if registration.disposal is not None:
                try:
                    registration.disposal()
                except Exception as err:  # noqa: BLE001 - carried, never primary
                    cleanup.append(PluginCleanupError(descriptor.id, err))
            if cleanup:
                _carry_cleanup_errors(cleanup)
            raise
        active = ActivePlugin(
            descriptor=descriptor, registration=registration,
            method_ids=tuple(staged_methods), stream_route_ids=tuple(staged_routes),
        )
        self._active[descriptor.id] = active
        self._activation_order.append(descriptor.id)
        return active

    # -- contribution points: admission, staging, publication ------------------

    def _require_admission_open(self, action: str) -> None:
        """The draining-window guard: while an activation round stages or
        commits, no second registration/publish/teardown may interleave
        with it. The refusal names the state; it never queues."""
        if self._round_depth:
            raise HostAdmissionClosedError(action, self.state)

    def register_contribution_point(self, point_id: str, api_version: str, *,
                                    handler=None, exclusive: bool = True) -> None:
        """Declare one extension point (composition-time; the handler may
        arrive later — a declared-but-unbound point refuses admission for
        its contributions, it does not drop them)."""
        self._require_admission_open("contribution point registration")
        self.contribution_points.register(point_id, api_version,
                                          handler=handler, exclusive=exclusive)

    def _stage_contributions(self, owner: str, batch: ContributionBatch) -> None:
        """Admission-check and stage one registration's batch, no publish.

        Every entry passes the host's point registry first — bound
        handler, accepted api_version, and for exclusive points no
        published or round-claimed holder (a takeover always retires
        first, even by the same owner). Each contribution then stages
        through ITS point's handler with the host injecting the owner:
        author code names neither. The batch's `required` flags are
        checked against the whole batch before the first stage."""
        batch.check_required()
        for item in batch.contributions:
            point = self.contribution_points.point(item.point_id)
            if point is None or point.handler is None:
                raise ContributionPointUnboundError(item.point_id, owner)
            if item.api_version != point.api_version:
                raise ContributionVersionRefusedError(
                    item.point_id, owner, item.api_version, point.api_version)
            if point.exclusive:
                holder = (self.contribution_points.holder(item.point_id)
                          or self._round_claims.get(item.point_id))
                if holder is not None:
                    raise ContributionPointHeldError(item.point_id, holder, owner)
            staged = stage_contributions(point.handler, owner,
                                         ContributionBatch((item,)))
            if point.exclusive:
                self._round_claims[item.point_id] = owner
            self._round_staged.append((owner, staged, point.handler))

    def _commit_round_contributions(self) -> None:
        """The commit pass: only after the whole round staged. Each staged
        batch commits through its handler; the round's published view is
        swapped in ONCE, after the last commit — consumers can never see a
        half-committed round, and a commit failure leaves the registry
        exactly as the previous round committed it."""
        for owner, staged, handler in self._round_staged:
            staged.commit()
            self._round_committed.append((owner, staged, handler))
        records = [
            PublishedRecord(owner, contribution, prepared, handler)
            for owner, staged, handler in self._round_committed
            for contribution, prepared in staged.entries
        ]
        with self._contribution_lifecycle_lock:
            self.contribution_points.publish(records)

    def _rollback_round_contributions(self) -> list[ServerPluginError]:
        """Undo the round's contribution work, reverse order, every entry
        attempted: staged batches through their `StagedBatch` transaction
        (which carries its own failures onto the in-flight primary),
        committed-but-unpublished entries back through their handlers
        (their facts come back for the carry). Never raises; never
        swallows."""
        staged, committed = self._round_staged, self._round_committed
        self._round_staged = []
        self._round_committed = []
        self._round_claims = {}
        cleanup: list[ServerPluginError] = []
        # The committed ones are a prefix of the staged list (the commit
        # pass walked it in order): undo the still-staged tail first, then
        # the committed prefix, each in reverse — one global reverse sweep.
        for owner, batch, handler in reversed(staged):
            if batch.state == "committed":
                continue  # undone through the committed ledger below
            try:
                batch.rollback()
            except ContributionBatchCleanupError as err:
                # only raised when nothing was in flight to carry the facts
                cleanup.extend(err.errors)
        for owner, batch, handler in reversed(committed):
            cleanup.extend(_undo_records(
                PublishedRecord(owner, contribution, prepared, handler)
                for contribution, prepared in reversed(batch.entries)))
        return cleanup

    # -- contribution resolution (the consumer seam) -----------------------------

    def contribution(self, point_id: str, *,
                     consumer: str | None = None) -> "ResolvedContribution | AbsentContribution":
        """The committed view of one point — published records only. A
        named `consumer` is granted access only by `requires` on the
        owner (the same grant the ports enforce): an undeclared consumer
        of a published contribution is a typed refusal, and an ownerless
        absence stays an observable `AbsentContribution`.

        Neither path picks a winner when the point carries several owners:
        the argument-less path answers an observable absence naming the
        count, the granted path raises `ContributionAmbiguousError` naming
        every owner. Registration order is not a selection rule, and a
        scoped lookup that silently returned the first authorized record
        would hand one consumer an arbitrary owner while its neighbours
        stayed invisible."""
        if consumer is None:
            return self.contribution_points.resolve(point_id)
        authorized: "list[ResolvedContribution]" = []
        for record in self.contribution_points.published(point_id):
            if not self._contribution_granted(consumer, record.owner):
                raise ContributionAccessError(consumer, record.owner, point_id)
            authorized.append(self.contribution_points.record_view(record))
        if not authorized:
            return AbsentContribution(point_id, "no committed contribution is published")
        if len(authorized) > 1:
            raise ContributionAmbiguousError(
                consumer, point_id, tuple(view.owner for view in authorized))
        return authorized[0]

    def contributions(self, point_id: str) -> "tuple[ResolvedContribution, ...]":
        """Every committed view on one point, publish order."""
        with self._contribution_lifecycle_lock:
            return self.contribution_points.views(point_id)

    def contribution_exact(self, point_id: str, *, owner: str,
                           publication_token: str,
                           consumer: str | None = None) -> "ResolvedContribution | AbsentContribution":
        """Resolve one enumerated publication without choosing among owners.

        All three identity components must match one currently published
        record. A retired token never names its replacement. The optional
        consumer has the same declared-dependency grant as the single-view
        carrier; a missing publication is an observable absence.
        """
        with self._contribution_lifecycle_lock:
            if not all(type(value) is str and value for value in
                       (point_id, owner, publication_token)):
                return AbsentContribution(point_id, "complete publication identity is required")
            matches = tuple(record for record in self.contribution_points.published(point_id)
                            if record.owner == owner and
                            record.publication_token == publication_token)
            if len(matches) != 1:
                return AbsentContribution(point_id, "selected publication is absent or ambiguous")
            if consumer is not None and not self._contribution_granted(consumer, owner):
                raise ContributionAccessError(consumer, owner, point_id)
            return self.contribution_points.record_view(matches[0])

    def _contribution_granted(self, consumer: str, owner: str) -> bool:
        if consumer == owner:
            return True
        active = self._active.get(consumer)
        if active is None:
            raise InvalidDeclarationError(
                f"contribution consumer {consumer!r} is not active")
        return owner in active.descriptor.requires

    @contextmanager
    def use_contribution(self, point_id: str, *,
                         consumer: str | None = None) -> Iterator["ResolvedContribution | AbsentContribution"]:
        """Resolve-and-hold: the owner is busy for exactly this window, so
        no unload can steal the live reference from the body. An absence
        claims no hold, and a refusal (no grant, an ambiguous point) raises
        before the body runs — it never holds a half-chosen owner."""
        with self._contribution_lifecycle_lock:
            view = self.contribution(point_id, consumer=consumer)
            if isinstance(view, ResolvedContribution):
                self.contribution_points.acquire(view.owner)
        if isinstance(view, ResolvedContribution):
            try:
                yield view
            finally:
                with self._contribution_lifecycle_lock:
                    self.contribution_points.release(view.owner)
        else:
            yield view

    @contextmanager
    def use_contribution_exact(self, point_id: str, *, owner: str,
                               publication_token: str,
                               consumer: str | None = None) -> Iterator["ResolvedContribution | AbsentContribution"]:
        """Atomically resolve and hold a selected current publication."""
        with self._contribution_lifecycle_lock:
            view = self.contribution_exact(point_id, owner=owner,
                                           publication_token=publication_token,
                                           consumer=consumer)
            if isinstance(view, ResolvedContribution):
                self.contribution_points.acquire(view.owner)
        if isinstance(view, ResolvedContribution):
            try:
                yield view
            finally:
                with self._contribution_lifecycle_lock:
                    self.contribution_points.release(view.owner)
        else:
            yield view

    def owner_busy(self, owner: str) -> bool:
        """True while any consumer holds a live resolution of this owner's
        contribution (C1's `CoreRuntime.owner_busy` mirror)."""
        return self.contribution_points.busy(owner)

    # -- unload / shutdown ----------------------------------------------------

    def _dispose_active(self, active: ActivePlugin) -> PluginCleanupError | None:
        """Tear one active plugin down; a raising disposal is captured and
        carried, never allowed to stop the cleanups behind it.

        The plugin's registrations were already revoked by `deactivate` before
        its disposal ran, so a captured failure is a hygiene fact, not a
        registry leak. A `DependentActiveError` here would mean the host tore
        down in the wrong order — that is a host bug and propagates."""
        try:
            self._deactivate(active.descriptor.id)
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
        Neither can an owner whose contribution a consumer currently
        resolves in-flight — the refusal names the owner; a live
        reference is never stolen.
        """
        self._deactivate(plugin_id, require_idle=True)

    def _deactivate(self, plugin_id: str, *, require_idle: bool = False) -> None:
        with self._contribution_lifecycle_lock:
            if require_idle:
                self._require_admission_open("plugin deactivation")
            active = self._active.get(plugin_id)
            if active is None:
                raise InvalidDeclarationError(f"plugin {plugin_id!r} is not active")
            if require_idle and self.owner_busy(plugin_id):
                raise ContributionOwnerBusyError(
                    plugin_id, self.contribution_points.busy_points(plugin_id))
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
            self.http_routes.unregister_owner(plugin_id)
            # Publication and active-state retirement are one transition with
            # the busy check. Author callbacks must run after releasing this
            # lock: they may wait for a different thread to inspect the host.
            records = self.contribution_points.retire_owner(plugin_id)
            del self._active[plugin_id]
            self._activation_order.remove(plugin_id)
            self._retiring_owners.add(plugin_id)
        try:
            # Undo every record even if one handler fails. The owner's name is
            # reserved until all rollback/disposal work has finished.
            cleanup: list[ServerPluginError] = _undo_records(records)
            if active.registration.disposal is not None:
                try:
                    active.registration.disposal()
                except BaseException:
                    _carry_cleanup_errors(cleanup)
                    raise
            if cleanup:
                raise ContributionBatchCleanupError(tuple(
                    err for err in cleanup if isinstance(err, ContributionCleanupError)))
        finally:
            with self._contribution_lifecycle_lock:
                self._retiring_owners.discard(plugin_id)

    def run_stop_hooks(self) -> None:
        """Run every active plugin's `stop_hooks`, reverse activation order.

        The mirror of the start round's `start_hooks`, and the phase that
        replaced the composition root's specialised stop: the host does not
        know what any hook stops, it only guarantees the order. Reverse
        activation order is the whole rule — the most dependent plugin (the
        one that activated last, on top of the ports it declared) tears its
        own resources down first, while every plugin it consumes is still
        active and still serving the records those teardowns write.

        A raising hook propagates immediately and the hooks behind it do not
        run: a refusal to settle is the fact the operator has to see, and
        today's specialised stop aborted the same way. The carry-not-swallow
        rule that governs the *disposal* pass therefore does not apply here;
        widening that is a design change, not a mechanical one.
        """
        self._require_admission_open("stop hooks")
        for plugin_id in reversed(list(self._activation_order)):
            for hook in self._active[plugin_id].registration.stop_hooks:
                hook()

    def shutdown(self) -> None:
        """Dispose every active plugin exactly once, reverse activation order.

        One plugin's disposal raising never orphans the rest: every remaining
        plugin is still released, and the collected failures raise as one
        `CleanupError` after the loop — a shutdown that swallowed a disposal
        failure would be a silent lie."""
        self._require_admission_open("host shutdown")
        cleanup: list[PluginCleanupError] = []
        for plugin_id in reversed(list(self._activation_order)):
            failure = self._dispose_active(self._active[plugin_id])
            if failure is not None:
                cleanup.append(failure)
        if cleanup:
            raise CleanupError(tuple(cleanup))
