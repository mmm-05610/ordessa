"""Stable Server plugin contract (`server_plugin_api`).

This package is the boundary plugins program against: it must never import
`ordessa_server`, `pacthold` product code, or any plugin. It carries only the
types the contract needs — descriptors, the activation context, the
registration a plugin returns, and the typed errors a host rejects startup
with. Nothing here dispatches, stores, or composes; a host implements those.

Versioning: `SERVER_PLUGIN_API_VERSION` is the integer a plugin descriptor
declares compatibility with. A host refusing a descriptor it cannot honour is
the contract working, not a failure.
"""
from __future__ import annotations

from .contract import (
    PLUGIN_METHOD_ID,
    SERVER_PLUGIN_API_VERSION,
    ServerMethodDescriptor,
    ServerPlugin,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    StreamRouteDescriptor,
)
from .errors import (
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
    ServerPluginError,
)

__all__ = [
    "SERVER_PLUGIN_API_VERSION",
    "PLUGIN_METHOD_ID",
    "ServerMethodDescriptor",
    "ServerPlugin",
    "ServerPluginContext",
    "ServerPluginDescriptor",
    "ServerPluginRegistration",
    "StreamRouteDescriptor",
    "ServerPluginError",
    "DuplicateMethodError",
    "DuplicatePluginError",
    "DuplicateStreamRouteError",
    "DependencyError",
    "CyclicDependencyError",
    "DependentActiveError",
    "PortConflictError",
    "InvalidDeclarationError",
    "PluginCleanupError",
    "CleanupError",
]
