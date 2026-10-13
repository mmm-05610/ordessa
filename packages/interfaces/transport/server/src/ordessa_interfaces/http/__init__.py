"""HTTP transport mechanisms: reusable admission, serialization and app factory.

The app factory is mechanism the composition injects a minimal host view into;
it never imports the Server application's concrete runtime.
"""
from ordessa_interfaces.http.ports import (
    AccessAuthorityPort,
    AcpAdmissionGatePort,
    AcpAdmissionRefused,
    HttpHostView,
    HttpRouteRegistryPort,
    PluginHttpHostPort,
    StreamRouteAddressing,
    WireServicePort,
)
from ordessa_interfaces.http.runtime import create_app

__all__ = [
    "AccessAuthorityPort",
    "AcpAdmissionGatePort",
    "AcpAdmissionRefused",
    "HttpHostView",
    "HttpRouteRegistryPort",
    "PluginHttpHostPort",
    "StreamRouteAddressing",
    "WireServicePort",
    "create_app",
]
