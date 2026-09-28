"""Contract types. Deliberately small; every field is load-bearing."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .contributions import ContributionBatch

SERVER_PLUGIN_API_VERSION = 1

#: A wire method id: a lowercase namespace word, then dot-separated wire/1
#: identifier words in their existing spelling, lowerCamelCase included
#: (`server.hello`, `workspaces.gitStatus`, `acp.channel.open`). The wire's
#: own vocabulary; anything else is an `InvalidDeclarationError` at
#: registration, not a bad request later.
PLUGIN_METHOD_ID = re.compile(r"[a-z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)*\Z")

_PLUGIN_ID = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_ROUTE_ID = re.compile(r"[a-z][a-z0-9-]*\Z")


@dataclass(frozen=True)
class ServerPluginDescriptor:
    """Static facts about one Server plugin.

    `requires` names other plugin ids that must be active before this one
    activates — a directed acyclic graph the host validates at startup.
    Optional cooperation between plugins does not belong here: it travels as
    ports on the registration, and absence is handled at call time.
    """

    id: str
    display_name: str
    version: str
    api_version: int = SERVER_PLUGIN_API_VERSION
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _PLUGIN_ID.fullmatch(self.id):
            raise ValueError(f"invalid plugin id: {self.id!r}")
        for name, value in (("display_name", self.display_name), ("version", self.version)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"plugin descriptor {name} is required")
        if not isinstance(self.api_version, int) or self.api_version < 1:
            raise ValueError("plugin api_version must be a positive integer")
        if not isinstance(self.requires, tuple) or any(
                not isinstance(item, str) or not item for item in self.requires):
            raise ValueError("requires must be a tuple of plugin id strings")


#: The availability predicate answers the hello question only: (supported,
#: reason). It must never gate dispatch — support state and existence are two
#: questions and stay in two places (order 097).
Availability = Callable[[], "tuple[bool, str | None]"]


@dataclass(frozen=True)
class ServerMethodDescriptor:
    """One wire method, declared atomically.

    The shape, the handler, the availability predicate and the owning plugin
    travel together: a method cannot be advertised unless its handler is
    installed, and a duplicate id is a startup failure, not a first-request
    surprise. `required_params`/`optional_params` are the exact wire/1 shape
    sets; a host rejects a request that misses a required or carries an extra
    unknown param.
    """

    method_id: str
    required_params: frozenset[str]
    optional_params: frozenset[str]
    handler: Callable[[Mapping[str, Any]], Any]
    owner: str
    availability: Availability | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.method_id, str) or not PLUGIN_METHOD_ID.fullmatch(self.method_id):
            raise ValueError(f"invalid wire method id: {self.method_id!r}")
        for name, value in (("required_params", self.required_params),
                            ("optional_params", self.optional_params)):
            if not isinstance(value, frozenset) or any(
                    not isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a frozenset of param names")
        overlap = self.required_params & self.optional_params
        if overlap:
            raise ValueError(f"params declared both required and optional: {sorted(overlap)}")
        if not callable(self.handler):
            raise ValueError("handler must be callable")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValueError("owner must name the registering plugin")
        if self.availability is not None and not callable(self.availability):
            raise ValueError("availability must be callable when given")


@dataclass(frozen=True)
class StreamRouteDescriptor:
    """One bidirectional stream surface, admitted through host transport.

    `resolver(connection_ref) -> object | None` turns an incoming connection
    reference (e.g. an ACP `connectionId`) into the owned endpoint, or None
    when nothing owns it. Origin/bearer checks and close semantics stay in the
    host transport — a plugin cannot bypass or widen them; it only supplies
    resolution of its own endpoints.
    """

    route_id: str
    resolver: Callable[[str], Any | None]
    owner: str

    def __post_init__(self) -> None:
        if not isinstance(self.route_id, str) or not _ROUTE_ID.fullmatch(self.route_id):
            raise ValueError(f"invalid stream route id: {self.route_id!r}")
        if not callable(self.resolver):
            raise ValueError("resolver must be callable")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValueError("owner must name the registering plugin")


_HTTP_METHODS = frozenset({
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS",
})


@dataclass(frozen=True)
class HttpRouteDescriptor:
    """One business HTTP route, admitted through the host's transport wall.

    The endpoint is the plugin's own callable, shaped for the host transport
    (path/query/body parameters and a response exactly as the transport's
    framework expects); the descriptor carries no transport types, so this
    contract stays dependency-free. Admission is host-owned: the route is
    mounted behind the host's bearer authentication, loopback policy and
    error sanitisation, and a route that would shadow a host route or another
    plugin's route is a typed refusal, never a silent second handler.
    """

    path: str
    methods: frozenset[str]
    endpoint: Callable[..., Any]
    owner: str
    #: Host bearer authentication is the default for every plugin route. A
    #: route that carries its own admission token (the delegation bridge's
    #: attempt-scoped token) may opt out explicitly — never implicitly.
    authenticated: bool = True

    def __post_init__(self) -> None:
        if (not isinstance(self.path, str) or not self.path.startswith("/")
                or len(self.path) > 1024 or "{" not in self.path and ".." in self.path):
            raise ValueError(f"invalid http route path: {self.path!r}")
        if type(self.authenticated) is not bool:
            raise ValueError("authenticated must be a boolean")
        if not isinstance(self.methods, frozenset) or not self.methods:
            raise ValueError("http route methods must be a non-empty frozenset")
        unknown = {m for m in self.methods
                   if not isinstance(m, str) or m.upper() not in _HTTP_METHODS}
        if unknown:
            raise ValueError(f"unknown http methods: {sorted(unknown)}")
        if not callable(self.endpoint):
            raise ValueError("endpoint must be callable")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValueError("owner must name the registering plugin")


#: The two converters the host CLI knows how to build for a contributed
#: flag (T014-S4). A spec naming any other `type` is a declaration error at
#: construction, not a broken parser at startup; `action` is restricted the
#: same way to the three argparse behaviours the wall has reviewed.
_FLAG_TYPES = frozenset({"path", "int"})
_FLAG_ACTIONS = frozenset({"store", "store_true", "append"})
_FLAG_ADD_KEYS = frozenset({"type", "choices", "action", "default", "help", "metavar"})


@dataclass(frozen=True)
class ServerFlagSpec:
    """One contributed business flag of the Server CLI grammar (`cli.server-flags`).

    The host keeps the transport-level grammar (`--data-root`, `--port`);
    everything else the Server's `main` accepts is declared through this
    spec by the installed product. `add` carries exactly the argparse
    keyword arguments needed to register the flag — `type` by NAME
    (`_FLAG_TYPES`), so this contract stays dependency-free and the host
    resolves `Path`/`int` itself — and the parsed value's meaning is
    declared, not executed here: `feeds` names the composition argument
    the value is handed to (empty: consumed only by the product's own
    route planning), `route` names the composition method the flag
    participates in (empty: shared). Validation of combinations and the
    choice between `default_runtime` / `native_runtime` / `sidecar_runtime`
    are the product's `plan_server_cli` answer, so the host names no
    business mode.
    """

    flags: tuple[str, ...]
    dest: str
    add: Mapping[str, Any] = field(default_factory=dict)
    feeds: str = ""
    route: str = ""

    def __post_init__(self) -> None:
        if (not isinstance(self.flags, tuple) or not self.flags
                or any(not isinstance(f, str) or not f.startswith("--") or len(f) < 3
                       for f in self.flags)):
            raise ValueError(f"invalid flag spellings: {self.flags!r}")
        if not isinstance(self.dest, str) or not self.dest.isidentifier():
            raise ValueError(f"invalid dest: {self.dest!r}")
        if not isinstance(self.add, Mapping):
            raise ValueError("add must be a mapping of argparse keywords")
        unknown = set(self.add) - _FLAG_ADD_KEYS
        if unknown:
            raise ValueError(f"unknown argparse keywords in flag spec: {sorted(unknown)}")
        type_name = self.add.get("type")
        if type_name is not None and type_name not in _FLAG_TYPES:
            raise ValueError(f"flag type must be one of {sorted(_FLAG_TYPES)}, got {type_name!r}")
        action = self.add.get("action")
        if action is not None and action not in _FLAG_ACTIONS:
            raise ValueError(f"flag action must be one of {sorted(_FLAG_ACTIONS)}, got {action!r}")
        if not isinstance(self.feeds, str) or (self.feeds and not self.feeds.isidentifier()):
            raise ValueError(f"invalid feeds argument name: {self.feeds!r}")
        if not isinstance(self.route, str) or (self.route and not self.route.isidentifier()):
            raise ValueError(f"invalid route method name: {self.route!r}")


@dataclass(frozen=True)
class ServerCliPlan:
    """The product's answer to what the parsed CLI values mean (T014-S4).

    `method` names the composition method the host must call with
    `(data_root, *args, **kwargs)` — the plan never carries the data root
    or the port, both host-owned; `error` is the exact refusal message the
    host's parser reports instead of running anything. Exactly one of the
    two is meaningful: an error plan carries no method the host may call.
    """

    method: str = ""
    args: tuple = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.error is not None:
            if self.method:
                raise ValueError("an error plan must not name a composition method")
            if not isinstance(self.error, str) or not self.error:
                raise ValueError("error must be a non-empty message or None")
            return
        if not isinstance(self.method, str) or not self.method.isidentifier():
            raise ValueError(f"invalid composition method: {self.method!r}")
        if not isinstance(self.args, tuple):
            raise ValueError("args must be a positional tuple")
        if not isinstance(self.kwargs, Mapping):
            raise ValueError("kwargs must be a mapping")


@dataclass(frozen=True)
class ServerPluginContext:
    """What a plugin may touch while building.

    `ports` are typed objects under documented names. Two sources, stated
    separately by the host: the host's own scoped facades (storage, record
    facades, connectors — no raw database, no credentials, no mutable host
    registry, no transport app object), and the `provided_ports` of every
    plugin this one **declared** in `requires`. A plugin that did not declare
    a dependency cannot see that plugin's ports — declaring the dependency is
    the access grant — and a port that would shadow an existing binding is a
    typed conflict (`PortConflictError`), never a silent override.
    """

    plugin_id: str
    data_root: Any
    ports: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.ports, Mapping):
            raise ValueError("ports must be a mapping of documented names to objects")


@dataclass(frozen=True)
class ServerPluginRegistration:
    """What one plugin contributes, validated as a whole before anything commits.

    `provided_ports` are the typed objects other plugins may consume (for
    example a workspace resolution service); the host owns the wiring, a
    plugin never reaches into another plugin directly. `disposal` is called
    exactly once if the plugin was activated, on unload or host shutdown.
    """

    methods: tuple[ServerMethodDescriptor, ...] = ()
    stream_routes: tuple[StreamRouteDescriptor, ...] = ()
    http_routes: tuple[HttpRouteDescriptor, ...] = ()
    provided_ports: Mapping[str, Any] = field(default_factory=dict)
    #: Called by the host after the database is initialized on every start,
    #: in activation order. Startup recovery that a plugin owns (marking its
    #: records unverified, sealing interrupted turns) belongs here, not in
    #: the host's own start sequence.
    start_hooks: "tuple[Callable[[], None], ...]" = ()
    disposal: Callable[[], None] | None = None
    #: The C2 contribution declarations of this plugin. An empty batch is
    #: the default, so a registration predating contributions keeps
    #: working unchanged; the host enforces the staging/publish semantics
    #: and injects the owner — a contribution never carries one.
    contributions: ContributionBatch = field(default_factory=ContributionBatch)
    #: The mirror of `start_hooks`: the teardown a plugin owns (closing its own
    #: transports, draining its own runs, ending its own records with the real
    #: reason) runs **before** any plugin is disposed, in reverse activation
    #: order, so the round whose ports this plugin resolved against is still
    #: alive while it stops. A hook that refuses — a stop that will not settle,
    #: a transport that will not die — propagates to the caller rather than
    #: being swallowed into the disposal pass.
    #: Declared last on purpose: the fields above it keep the positional order
    #: pre-contribution registrations were built with
    #: (`test_registration_gains_contributions_backwards_compatible`).
    stop_hooks: "tuple[Callable[[], None], ...]" = ()

    def __post_init__(self) -> None:
        for name in ("methods", "stream_routes", "http_routes", "start_hooks",
                     "stop_hooks"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise ValueError(f"ServerPluginRegistration.{name} must be a tuple")
        if not isinstance(self.provided_ports, Mapping):
            raise ValueError("provided_ports must be a mapping")
        if not isinstance(self.contributions, ContributionBatch):
            raise ValueError("contributions must be a ContributionBatch")


@runtime_checkable
class ServerPlugin(Protocol):
    """Object a composition hands to the host to activate."""

    def descriptor(self) -> ServerPluginDescriptor: ...

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration: ...
