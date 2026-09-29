"""pacthold SDK entry point (contracts/host-integration.md).

v2 (specs/011-z1-profile, PV-05): the plugin contributes real components to
the host extension registry — the ``agent-box.profile@1`` resource contract
and a provider resolving it from the plugin's own store.  The bare host is
never modified: composition and wire binding stay host-owned.

The store is opened lazily on first *use*, never during discovery/build:
``PluginContext`` merely carries the data dir, and building the registration
performs no filesystem writes (pacthold extensions/api.py PluginContext).
"""
from __future__ import annotations

from typing import Any

from pacthold.extensions import PluginContext, PluginDescriptor, PluginRegistration
from pacthold.work_core.models import Ref, RefType
from pacthold.work_core.registry import ProviderDescriptor, ResourceResolutionContext
# Foundation (8844c475bc) moved the platform resource contracts into the
# runtime-compat package; the contract id stays the compatibility surface.
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1

_PLUGIN_ID = "profile"
_PLUGIN_VERSION = "2.0.0a1"
_PROVIDER_ID = "ordessa-profile"


class ProfilePluginServices:
    """Composition-owned facade over one ProfileCore.

    The host composes this object where it needs the Profile domain API
    (contracts.md §3 names the operations; the wire binding is the host's,
    not ours).  Everything here is typed through ``ordessa_profile.contracts``.
    """

    def __init__(self, core) -> None:
        self.core = core

    # -- facet providers (owner injected by the host scope) -------------
    def register_v2_facet(self, provider: Any, owner_plugin_id: str):
        return self.core.register_v2_provider(provider, owner_plugin_id)

    def unregister_facet(self, provider: Any) -> None:
        self.core.unregister_provider(provider)

    def describe_facets(self, harness_id: str | None = None):
        return self.core.describe_facets(harness_id)

    def resolve_preview(self, profile_id: str, session_id: str | None = None):
        return self.core.resolve_preview(profile_id, session_id)

    # -- mechanism policy (US1) -----------------------------------------
    def get_mechanism_policy(self, realm: str):
        return self.core.policy.get_public(realm)

    def update_mechanism_policy(self, key: str, *, realm: str,
                                expected_revision: int, patch: dict,
                                caller: str, preview: bool = False):
        return self.core.policy.update(
            key, realm=realm, expected_revision=expected_revision,
            patch=patch, caller=caller, preview=preview)


class ProfileResourceProvider:
    """Resolves ``agent-box.profile@1`` from the plugin store (read-only,
    non-secret identity projection — no facet values, no credentials)."""

    provider_id = _PROVIDER_ID
    supported_contract_ids = frozenset({AgentBoxProfileV1.contract_id})

    def __init__(self, data_dir: Any, *, harnesses: Any | None = None) -> None:
        self._data_dir = data_dir
        self._harnesses = harnesses
        self._core: Any | None = None

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(_PROVIDER_ID, "Ordessa Profile Store", _PLUGIN_VERSION)

    def core(self):
        """Lazy composition root; the store is opened on first use only."""
        if self._core is None:
            from .core import ProfileCore, StaticHarnessCatalog
            catalog = self._harnesses or StaticHarnessCatalog()
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._core = ProfileCore(
                self._data_dir / "profile-store.sqlite",
                harnesses=catalog,
            )
        return self._core

    def resolve(self, contract_id: str, ref: Ref, *,
                context: ResourceResolutionContext | None = None) -> AgentBoxProfileV1:
        del context
        if contract_id != AgentBoxProfileV1.contract_id \
                or ref.provider != _PROVIDER_ID \
                or ref.type is not RefType.ARTIFACT:
            raise ValueError("PROFILE_REF_MISMATCH")
        core = self.core()
        profile = core.profiles.get(ref.native_id)
        if profile is None:
            raise KeyError("PROFILE_NOT_FOUND")
        revision = int(ref.metadata.get("revision", profile["current_revision"]))
        from .sensitive import digest as canonical_digest
        digest_source = f"{profile['profile_id']}@{revision}:{profile['harness_id']}"
        return AgentBoxProfileV1(
            name=profile["display_name"],
            agent_type=profile["harness_id"],
            digest=canonical_digest(digest_source),
            revision=revision,
            provider=_PROVIDER_ID,
        )


class ProfilePlugin:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            id=_PLUGIN_ID,
            display_name="Ordessa Profile",
            version=_PLUGIN_VERSION,
            description=(
                "Per-Harness profiles, contributed configuration facets, "
                "session overlays and same-session switching"
            ),
            config_namespace=_PLUGIN_ID,
        )

    def build(self, context: PluginContext) -> PluginRegistration:
        provider = ProfileResourceProvider(context.plugin_data_dir)
        # Foundation (8844c475bc) emptied the built-in contract table: the
        # loader derives known contracts from registration.contracts, so the
        # declaration travels with the provider.  If another plugin declares
        # the same id first, its load order wins — an integration arbitration
        # point recorded in specs/011-z1-profile/integration-request.md.
        return PluginRegistration(
            contracts=(AgentBoxProfileV1,),
            resource_providers=(provider,),
        )

    def services(self, context: PluginContext) -> ProfilePluginServices:
        """Composition entry for the host: the domain facade over the
        lazily-opened core backing the registration's provider."""
        provider = ProfileResourceProvider(context.plugin_data_dir)
        return ProfilePluginServices(provider.core())


def create_plugin() -> ProfilePlugin:
    return ProfilePlugin()
