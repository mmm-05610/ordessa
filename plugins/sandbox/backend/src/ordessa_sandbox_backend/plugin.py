"""Plugin registration for the Sandbox backend (server_plugin_api public types only).

Contributes the two §C2 ports and exactly one read-only wire method:

- ``provided_ports['sandbox.native-configuration@1']`` — the composition-time
  field-claim / compile / verify facet service,
- ``provided_ports['sandbox.describe@1']`` — the option/version query port,
- one wire method ``sandbox.describe`` — a read-only menu query with an exact
  parameter shape.

The plugin imports neither `ordessa_server` nor `ordessa_server_compat` nor
`pacthold` nor `ordessa_harness` nor any `ordessa_permissions_*`: it declares
`requires=()`, so the Sandbox domain installs and answers without Permissions
(verification.md extra-gate 2). There is no apps/server branching and no
second registry.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .composition import SandboxNativeService
from .catalogue import SandboxOptionCatalogue

PLUGIN_ID = "ordessa.sandbox"

#: exact wire/1 shape for the one read-only method this plugin owns
_DESCRIBE_REQUIRED = frozenset({"harnessId"})
_DESCRIBE_OPTIONAL = frozenset({"nativeVersion", "osName", "osVersion",
                                "platformVersion"})


class SandboxDescribePort:
    """The `sandbox.describe@1` query surface other domains consume."""

    def __init__(self, service: SandboxNativeService) -> None:
        self._service = service

    @property
    def repository(self):
        return self._service.repository

    def get_intent(self, sandbox_id: str, revision: int):
        return self._service.repository.get_intent(sandbox_id, revision)

    def availability(self):
        return self._service.availability()

    def register_instance(self, instance_key: str) -> None:
        self._service.register_instance(instance_key)

    def uninstall_facet(self) -> None:
        self._service.uninstall_facet()

    def describe(self, harness_id: str, native_version, **kw):
        return self._service.describe(harness_id, native_version, **kw)


class SandboxBackendServerPlugin:
    """Native-sandbox backend: option/version management + pre-effect verify."""

    def __init__(self, service: SandboxNativeService) -> None:
        self._service = service
        self._describe_port = SandboxDescribePort(service)

    def descriptor(self) -> ServerPluginDescriptor:
        # `requires` is intentionally empty: Sandbox must install WITHOUT
        # Permissions (and without Harness/compat/server), the two optional
        # domains cooperate only through ports the host wires at call time.
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Ordessa native-sandbox backend",
            version="1", requires=())

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        service = self._service

        def sandbox_describe(params: Mapping[str, Any]) -> dict:
            """Read-only §C2 describe: the menu for a pinned pin, never a
            brand-name guess, and no configuration is ever applied here."""
            harness_id = params["harnessId"]
            native_version = params.get("nativeVersion")
            platform_os = params.get("osName", "linux")
            platform_version = params.get("osVersion",
                                          params.get("platformVersion", ""))
            facet = service.describe(harness_id, native_version,
                                     platform_os=platform_os,
                                     platform_version=platform_version)
            return facet.to_wire(harness_id, native_version)

        method = ServerMethodDescriptor(
            method_id="sandbox.describe",
            required_params=_DESCRIBE_REQUIRED,
            optional_params=_DESCRIBE_OPTIONAL,
            handler=sandbox_describe,
            owner=PLUGIN_ID,
            availability=service.availability,
        )
        return ServerPluginRegistration(
            methods=(method,),
            provided_ports={
                "sandbox.native-configuration@1": service,
                "sandbox.describe@1": self._describe_port,
            },
            disposal=self._dispose,
        )

    def _dispose(self) -> None:
        self._describe_port = SandboxDescribePort(self._service)


def build_sandbox_plugin(service: SandboxNativeService | None = None, *,
                         catalogue: SandboxOptionCatalogue | None = None
                         ) -> SandboxBackendServerPlugin:
    """Compose the plugin around a service (a fresh catalogue-backed one by
    default) — the entry the product assembly calls."""
    if service is None:
        service = SandboxNativeService(catalogue=catalogue)
    return SandboxBackendServerPlugin(service)
