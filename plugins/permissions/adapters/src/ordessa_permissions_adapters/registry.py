"""The §C1 compile-time surface records - NOT a composition authority.

Since the foundation checkpoint the real admission authority is the
platform: contributions to `harness.configuration-adapters` are admitted
(duplicate/overlap refusal, field-claim conflicts, owner injection,
publish-on-commit) by the harness-side conflict registry driven through the
public `server_plugin_api` staging protocol. The package's former private
`PolicyAdapterRegistry` - which re-implemented exactly that refusal set as a
second authority - has been removed; what remains here is pure data:

* `PolicyAdapterDescriptor`: the identity record of one compile-surface
  adapter (`adapter_id`, `harness_id`, `version_range`), kept for the §C1
  `supports/compilePolicy/verifyPolicy` side; the configuration-point side
  is declared by `contribution.py` as public `ConfigurationAdapterDescriptor`
  payloads.
* `PolicyAdaptersPlugin`: the plugin surface. `build()` returns a
  registration whose contributions batch is the real-point declaration; the
  host injects owner/generation and admits or refuses. No provided port
  carries a self-registered adapter set anymore.
"""
from __future__ import annotations

from dataclasses import dataclass

from server_plugin_api import (
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .contribution import policy_adapter_contributions
from .ranges import NativeVersionRange

__all__ = [
    "ADAPTER_PLUGIN_ID",
    "CONTRACT_ID",
    "PolicyAdapterDescriptor",
    "PolicyAdaptersPlugin",
]

#: The §C1 contract name of the compile surface. On the real point it reads
#: as facet `permissions.policy-adapters` at API version `v1`.
CONTRACT_ID = "permissions.policy-adapters@1"
ADAPTER_PLUGIN_ID = "ordessa.permissions-adapters"


@dataclass(frozen=True)
class PolicyAdapterDescriptor:
    """The registration record of one adapter: `(harnessId, nativeVersionRange)`.

    A plain value. Uniqueness and overlap of these keys across a composition
    are the platform's refusal - this record validates only its own shape.
    """

    adapter_id: str
    harness_id: str
    version_range: NativeVersionRange
    contract_id: str = CONTRACT_ID
    #: owner and generation are the platform's to assign (stage/commit,
    #: §C4); a plugin-built record leaves them unset.
    owner: str | None = None
    generation: str | None = None

    def __post_init__(self) -> None:
        for name in ("adapter_id", "harness_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.version_range, NativeVersionRange):
            raise ValueError("version_range must be a NativeVersionRange")
        if self.contract_id != CONTRACT_ID:
            raise ValueError("this record serves only the policy-adapters "
                             "contract")

    @property
    def key(self) -> tuple[str, tuple]:
        return (self.harness_id, self.version_range.key())


class PolicyAdaptersPlugin:
    """The plugin surface: declares the brand adapters on the real point.

    `build()` carries no admission logic: the registration's contribution
    batch is validated, conflicted, staged and published by the host and the
    point's handler. No method routes, no storage, no host import.
    """

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=ADAPTER_PLUGIN_ID,
            display_name="Ordessa Permissions Policy Adapters",
            version="0.1.0",
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=policy_adapter_contributions())
