"""Server plugin host: the hosting boundary of the Ordessa Server.

`host.py` is the one dispatch truth (method registry + stream routes) and the
plugin lifecycle. Domain plugins live beside it, one module per domain, and
must only program against `server_plugin_api`.
"""
from __future__ import annotations

from .contribution_points import (
    ContributionPoint,
    ContributionPointRegistry,
    PublishedRecord,
    ResolvedContribution,
)
from .host import ActivePlugin, MethodRegistry, ServerPluginHost, StreamRouteRegistry

__all__ = [
    "ActivePlugin", "MethodRegistry", "ServerPluginHost", "StreamRouteRegistry",
    "ContributionPoint", "ContributionPointRegistry", "PublishedRecord",
    "ResolvedContribution",
]
