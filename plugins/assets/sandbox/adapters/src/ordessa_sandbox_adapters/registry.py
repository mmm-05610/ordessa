"""The brand roster and the Server plugin surface (post-binding, demoted).

Since the foundation checkpoint the composition authority is the platform —
``HarnessContributionRegistry`` behind ``stage_contributions`` refuses
duplicate adapter ids, version/entry overlaps and cross-facet native-field
claim collisions with the typed ``HarnessContributionError``, and the host
owns publication, visibility and busy retirement. The package's private
``SandboxAdapterRegistry`` / ``stage_field_claims`` /
``NativeConfigContribution`` acted as a SECOND admission authority and are
therefore deleted (see README "who admits what"); what remains here is the
brand roster and the plugin that hands the platform a batch of real
``Contribution`` records.

``ADAPTER_PLUGIN_ID`` and ``SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID`` keep
their pre-binding strings (AGENTS rule 5, data compatibility).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from server_plugin_api import (
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .claude_code import ClaudeSandboxAdapter
from .codex import CodexSandboxAdapter
from .pi import PiSandboxAdapter
from .points import build_configuration_batch

__all__ = [
    "ADAPTER_PLUGIN_ID",
    "SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID",
    "SandboxAdaptersServerPlugin",
    "default_sandbox_adapters",
]

SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID = "sandbox.native-configuration@1"
ADAPTER_PLUGIN_ID = "ordessa.sandbox-adapters"


def default_sandbox_adapters() -> tuple[CodexSandboxAdapter, ClaudeSandboxAdapter,
                                        PiSandboxAdapter]:
    return (CodexSandboxAdapter(), ClaudeSandboxAdapter(), PiSandboxAdapter())


class SandboxAdaptersServerPlugin:
    """Contributes the three brand facet descriptors via the real point only.

    `pins` optionally injects the measured native versions (caller-supplied
    data keeps the package usable in environments where the harness dist is
    absent); by default they are located from `harnesses.toml` at build time.
    The registration carries NO provided_ports, NO owner and NO generation:
    those are host-assigned (§C4).
    """

    def __init__(self, *, adapters: Iterable[object] | None = None,
                 pins: Mapping[str, str] | None = None) -> None:
        self._adapters = None if adapters is None else tuple(adapters)
        self._pins = None if pins is None else dict(pins)

    def descriptor(self) -> ServerPluginDescriptor:
        # `requires` is empty: Sandbox installs without Permissions/Harness
        # CODE/server host.
        return ServerPluginDescriptor(
            id=ADAPTER_PLUGIN_ID,
            display_name="Ordessa native-sandbox configuration adapters",
            version="0.1.0",
            requires=())

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        adapters = (default_sandbox_adapters() if self._adapters is None
                    else self._adapters)
        return ServerPluginRegistration(
            contributions=build_configuration_batch(adapters, pins=self._pins))
