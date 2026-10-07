"""Product SDK API surface for Agent-Box flavored plugin packages.

specs/010 T009: the business slot types that used to live in
``pacthold.extensions.api`` (profile envelopes, provider host controls,
continuation routes, harness profile managers and the plugin protocol)
live here.  This package may import the kernel; the kernel never imports
it.  The mechanism types are re-exported so one import gives a plugin the
full SDK surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from pacthold.extensions.api import (
    PLUGIN_API_VERSION,
    FinalizationContribution,
    FinalizationContributor,
    HostControl,
    HostControlUnavailable,
    PluginContext,
    PluginDescriptor,
    PluginRegistration as CorePluginRegistration,
    RegistryBindable,
    ResourceSelection,
    ResourceSelector,
    SelectorCompatibility,
    SelectorField,
)
from pacthold.work_core.models import Ref, RefType


class HarnessProfileManager(Protocol):
    """Provider-owned, host-neutral Harness/Profile management surface."""
    harness_id: str
    def descriptor(self) -> Mapping[str, Any]: ...
    def list_profiles(self) -> tuple[Mapping[str, Any], ...]: ...
    def get_profile(self, profile_id: str, revision: int | None = None) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ProfileEnvelope:
    """Cross-harness profile metadata; ``native_payload`` stays plugin-owned.

    This is a Host/Extension value, not a Work Core resource contract.  The
    envelope deliberately carries only locators and immutable identity.
    """
    profile_id: str
    harness_type: str
    provider_id: str
    name: str
    schema_version: str
    revision: int
    digest: str
    disabled: bool = False
    credential_source_ref: Mapping[str, str] | None = None
    capability_refs: tuple[Mapping[str, str], ...] = ()
    session_overlay_policy: Mapping[str, str] = field(default_factory=dict)
    import_provenance: Mapping[str, str] | None = None
    native_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.revision < 1 or not self.digest or not self.profile_id or not self.harness_type or not self.provider_id:
            raise ValueError("invalid profile envelope identity")
        if self.credential_source_ref is not None and any(k in self.credential_source_ref for k in ("value", "secret", "token", "path")):
            raise ValueError("credential envelope must contain a locator only")

    def __getitem__(self, key: str) -> Any:
        # ``config`` is a read-only compatibility alias for native_payload.
        if key == "config":
            return self.native_payload
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except AttributeError:
            return default


class ProviderHostControl:
    """Small provider-neutral HostControl adapter used by Harness plugins."""
    def __init__(self, provider_id: str, provider: object):
        self.provider_id, self.provider = provider_id, provider
    def attach_command(self, facts: object) -> tuple[str, ...] | None:
        handle = self._handle(facts)
        descriptor = getattr(getattr(handle, "runtime", None), "attach_descriptor", None)
        if descriptor is None:
            descriptor = getattr(getattr(handle, "runtime_handle", None), "attach_descriptor", None)
        return tuple(descriptor.locator.split()) if descriptor else None
    def _handle(self, facts: object):
        dispatch = getattr(facts, "dispatch", None)
        dispatch_id = dispatch.get("id") if isinstance(dispatch, Mapping) else getattr(dispatch, "id", None)
        if dispatch_id is None: raise ValueError("HostControl requires dispatch identity")
        getter = getattr(self.provider, "get_handle", None)
        if not callable(getter):
            raise HostControlUnavailable("provider does not expose a typed runtime handle port")
        return getter(dispatch_id)
    def observe(self, facts: object, handle: object | None = None) -> object:
        return self.provider.observe(handle or self._handle(facts))
    def finish(self, facts: object, handle: object | None = None) -> object:
        return self.provider.finish(handle or self._handle(facts))


@dataclass(frozen=True)
class ContinuationRouteDescriptor:
    id: str
    source_native_providers: frozenset[str]
    target_execution_providers: frozenset[str]
    contract_id: str
    resource_provider_id: str
    selector_id: str
    continuation_kind: str
    compatibility: str


class ContinuationRoute(Protocol):
    def descriptor(self) -> ContinuationRouteDescriptor: ...
    def supports(self, source_execution: object, native_ref: Ref, target_provider_id: str) -> bool: ...
    def prepare(self, source_execution: object, native_ref: Ref, target_provider_id: str) -> ResourceSelection: ...


class ProviderContinuationRoute:
    """SDK adapter for a plugin-owned exact continuation ResourceProvider."""
    def __init__(self, descriptor: ContinuationRouteDescriptor, ref_factory):
        self._descriptor, self._ref_factory = descriptor, ref_factory
    def descriptor(self): return self._descriptor
    def supports(self, source_execution, native_ref, target_provider_id):
        projection = getattr(source_execution, "projection", None)
        phase = getattr(getattr(projection, "phase", None), "value", getattr(projection, "phase", None))
        return (phase == "terminal" and native_ref.type is RefType.SESSION
                and native_ref.provider in self._descriptor.source_native_providers
                and target_provider_id in self._descriptor.target_execution_providers)
    def prepare(self, source_execution, native_ref, target_provider_id):
        if not self.supports(source_execution, native_ref, target_provider_id):
            raise ValueError("continuation route is not compatible")
        ref = self._ref_factory(native_ref)
        return ResourceSelection(self._descriptor.contract_id, ref, self._descriptor.id, self._descriptor.compatibility)


@dataclass(frozen=True)
class PluginRegistration(CorePluginRegistration):
    """Product registration: the kernel slots plus the four business slots.

    It extends ``pacthold.extensions.api.PluginRegistration`` (a subclass of
    the frozen kernel dataclass with the original field order), so the
    kernel loader accepts it unchanged while only this assembly knows the
    business slots exist.
    """

    harness_managers: tuple[object, ...] = ()
    continuation_routes: tuple[object, ...] = ()
    credential_materializers: tuple[object, ...] = ()
    transport_operations: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        for name in ("contracts", "resource_providers", "execution_providers", "finalization_contributors", "resource_selectors", "host_controls", "harness_managers", "continuation_routes", "credential_materializers", "transport_operations"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"PluginRegistration.{name} must be a tuple")


class AgentBoxPlugin(Protocol):
    """Object returned by an ``agent_box.plugins`` Python entry point."""

    def descriptor(self) -> PluginDescriptor: ...

    def build(self, context: PluginContext) -> PluginRegistration: ...


__all__ = [
    "PLUGIN_API_VERSION",
    "AgentBoxPlugin",
    "ContinuationRoute",
    "ContinuationRouteDescriptor",
    "FinalizationContribution",
    "FinalizationContributor",
    "HarnessProfileManager",
    "HostControl",
    "HostControlUnavailable",
    "PluginContext",
    "PluginDescriptor",
    "PluginRegistration",
    "ProfileEnvelope",
    "ProviderContinuationRoute",
    "ProviderHostControl",
    "RegistryBindable",
    "ResourceSelection",
    "ResourceSelector",
    "SelectorCompatibility",
    "SelectorField",
]
