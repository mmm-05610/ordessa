"""Contract types. Deliberately small; every field is load-bearing."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

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


@dataclass(frozen=True)
class ServerPluginContext:
    """What a plugin may touch while building.

    `ports` are typed objects under documented names. Two sources, stated
    separately by the host: the host's own scoped facades (storage, record
    facades, connectors — no raw database, no credentials, no mutable host
    registry, no transport app object), and the `provided_ports` of every
    plugin this one **declared** in `requires`. A plugin that did not declare
    a dependency cannot see that plugin's ports — declaring the dependency is
    the access grant.
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
    provided_ports: Mapping[str, Any] = field(default_factory=dict)
    disposal: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        for name in ("methods", "stream_routes"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise ValueError(f"ServerPluginRegistration.{name} must be a tuple")
        if not isinstance(self.provided_ports, Mapping):
            raise ValueError("provided_ports must be a mapping")


@runtime_checkable
class ServerPlugin(Protocol):
    """Object a composition hands to the host to activate."""

    def descriptor(self) -> ServerPluginDescriptor: ...

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration: ...
