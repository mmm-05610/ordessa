"""The injected-port contracts behind the reusable HTTP app factory.

The factory in :mod:`ordessa_interfaces.http.runtime` is transport mechanism:
it owns the loopback wall, bearer admission, the wire/1 route, the OpenAPI
view, the two websocket channels and the plugin-route admission seam. It must
not import the Server application's concrete ``ServerRuntime``; instead the
composition hands it a *minimal view* declared here. These are the real
cross-layer contracts at the injection boundary, not an ``Any``-shaped catch
all: each protocol names exactly the members the factory reads.

``AcpAdmissionRefused`` is the one surface that crosses the boundary as an
*error*: the injected ACP gate raises it, the ACP channel route maps it to the
typed close ``4403 / ACP_ADMISSION_REFUSED``. It lives here, at the boundary
that maps it, so the transport never reaches back into the Server package for
it; the gate implementation imports it from here.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable, Protocol, runtime_checkable

from ordessa_server_plugin_api import HttpRouteDescriptor


@runtime_checkable
class AccessAuthorityPort(Protocol):
    """The transport's injected access needs; it constructs no authority."""

    def authenticate(self, authorization: str | None) -> object: ...
    def verify(self, principal: object) -> None: ...
    def guard_legacy(self, principal: object) -> AbstractContextManager: ...


class AcpAdmissionRefused(ValueError):
    """A managed-ACP frame was refused by the host-owned admission wall."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


@runtime_checkable
class StreamRouteAddressing(Protocol):
    """Resolution of an owner-registered stream endpoint by route id."""

    def resolve(self, name: str, route_id: str) -> Any: ...


@runtime_checkable
class AcpAdmissionGatePort(Protocol):
    """The generic ACP transport-safety wall injected through the host port."""

    def observe_agent_frame(self, connection_id: str, frame: str) -> None: ...
    def forget_channel(self, connection_id: str) -> None: ...
    def admit_client_frame(self, connection: Any, frame: str) -> None: ...


@runtime_checkable
class HttpRouteRegistryPort(Protocol):
    """The registered business-route descriptors the factory mounts."""

    def descriptors(self) -> "tuple[HttpRouteDescriptor, ...]": ...


@runtime_checkable
class PluginHttpHostPort(Protocol):
    """The plugin host's HTTP-relevant projection (never the whole host).

    Exactly four members: the registered-route registry, the activation check,
    the generic port lookup, and the one startup freeze. No runtime-wide
    surface is exposed through this type.
    """

    @property
    def http_routes(self) -> HttpRouteRegistryPort: ...
    def is_active(self, plugin_id: str) -> bool: ...
    def provided_port(self, name: str) -> "Callable[..., Any] | None": ...
    def freeze_http_routes(
        self, routes: "frozenset[tuple[str, frozenset[str], str, bool, str]]") -> None: ...


@runtime_checkable
class WireServicePort(Protocol):
    """The wire dispatch mechanism the transport route calls into."""

    identity_authority: "AccessAuthorityPort | None"
    acp_admission_gate: "AcpAdmissionGatePort | None"
    stream_routes: StreamRouteAddressing

    def dispatch(self, method: str, params: Any, *, caller: Any) -> Any: ...


@runtime_checkable
class HttpHostView(Protocol):
    """The minimal running view the HTTP factory needs from a composition.

    The Server's ``ServerRuntime`` satisfies this structurally; the factory
    reads only these members and never the concrete class.
    """

    wire: WireServicePort
    plugin_host: "PluginHttpHostPort | None"

    @property
    def started(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


__all__ = [
    "AccessAuthorityPort",
    "AcpAdmissionRefused",
    "AcpAdmissionGatePort",
    "HttpHostView",
    "HttpRouteRegistryPort",
    "PluginHttpHostPort",
    "StreamRouteAddressing",
    "WireServicePort",
]
