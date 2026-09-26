"""Stable, deliberately small API imported by third-party plugin packages."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, runtime_checkable

from ..work_core.models import Ref, RefType
from ..work_core.registry import ExecutionProvider, ExtensionRegistry, ResourceProvider
from ..work_core.resource_observations import ResourceObservation


PLUGIN_API_VERSION = 1
_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DOCS_URL = re.compile(r"^https?://\S+$")
_MAX_DESCRIPTION_LENGTH = 512
_MAX_DOCS_URL_LENGTH = 512
_MAX_CONFIG_NAMESPACE_LENGTH = 64


class HostControlUnavailable(RuntimeError):
    """A typed absence of a provider-owned runtime control port."""


@dataclass(frozen=True)
class PluginDescriptor:
    """Static, install-time facts about one plugin distribution.

    All P0 fields carry defaults so descriptors written before they existed
    keep loading unchanged.  They describe the plugin only — never config
    values, credentials, or the components it registers (a build()'s
    ``PluginRegistration`` remains the only source of component truth).
    """

    id: str
    display_name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    description: str = ""
    docs_url: str | None = None
    config_namespace: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _PLUGIN_ID.fullmatch(self.id):
            raise ValueError(f"invalid plugin id: {self.id!r}")
        for name, value in (
            ("display_name", self.display_name),
            ("version", self.version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"plugin descriptor {name} is required")
        if not isinstance(self.api_version, int) or self.api_version < 1:
            raise ValueError("plugin api_version must be a positive integer")
        if not isinstance(self.description, str):
            raise ValueError("plugin descriptor description must be a string")
        if len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"plugin description exceeds {_MAX_DESCRIPTION_LENGTH} characters"
            )
        if self.docs_url is not None:
            if not isinstance(self.docs_url, str) or not _DOCS_URL.fullmatch(
                self.docs_url
            ):
                raise ValueError("plugin docs_url must be an http(s) URL when given")
            if len(self.docs_url) > _MAX_DOCS_URL_LENGTH:
                raise ValueError(
                    f"plugin docs_url exceeds {_MAX_DOCS_URL_LENGTH} characters"
                )
        if self.config_namespace is not None:
            if not isinstance(self.config_namespace, str) or not _PLUGIN_ID.fullmatch(
                self.config_namespace
            ):
                raise ValueError(
                    "plugin config_namespace must look like a plugin id when given"
                )
            if len(self.config_namespace) > _MAX_CONFIG_NAMESPACE_LENGTH:
                raise ValueError(
                    "plugin config_namespace exceeds "
                    f"{_MAX_CONFIG_NAMESPACE_LENGTH} characters"
                )


@dataclass(frozen=True)
class PluginContext:
    """Host facts available while constructing stateless adapters.

    Merely receiving a path does not authorize a plugin to write during
    discovery. Runtime data should be created only when the plugin is used.
    """

    agent_box_version: str
    agent_box_home: Path
    plugin_data_dir: Path


@dataclass(frozen=True)
class PluginRegistration:
    """Components contributed to one process-local extension registry."""

    contracts: tuple[type, ...] = ()
    resource_providers: tuple[ResourceProvider, ...] = ()
    execution_providers: tuple[ExecutionProvider, ...] = ()
    finalization_contributors: tuple[object, ...] = ()
    resource_selectors: tuple[object, ...] = ()
    host_controls: tuple[object, ...] = ()
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


@dataclass(frozen=True)
class FinalizationContribution:
    output_refs: tuple[Ref, ...] = ()
    resource_observations: tuple[ResourceObservation, ...] = ()


class FinalizationContributor(Protocol):
    id: str
    supported_contract_ids: frozenset[str]

    def prepare_finalization(self, *, execution_id: str, dispatch_id: str | None,
                             frozen_input_ref: Ref, resolved_resource: object | None,
                             contract_id: str | None = None) -> FinalizationContribution: ...


@dataclass(frozen=True)
class ResourceSelection:
    """Bounded selector result consumable by any Host, including Web."""
    contract_id: str
    ref: Ref
    requested_summary: str = ""
    exact_summary: str = ""


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


class ResourceSelector(Protocol):
    id: str
    contract_id: str
    title: str
    fields: tuple["SelectorField", ...]
    def prepare(self, parameters: Mapping[str, str], *, execution_id: str) -> ResourceSelection: ...


@dataclass(frozen=True)
class SelectorCompatibility:
    """Typed Host discovery metadata; never a contract requirement."""
    execution_provider_ids: frozenset[str] = frozenset()
    harness_types: frozenset[str] = frozenset()
    supports_multi_slot: bool = False
    supports_exact_revision: bool = False
    requires_external_config: bool = False
    available_without_web: bool = True
    recommended: bool = False


class HarnessProfileManager(Protocol):
    """Provider-owned, host-neutral Harness/Profile management surface."""
    harness_id: str
    def descriptor(self) -> Mapping[str, Any]: ...
    def list_profiles(self) -> tuple[Mapping[str, Any], ...]: ...
    def get_profile(self, profile_id: str, revision: int | None = None) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SelectorField:
    key: str
    label: str
    kind: str = "text"
    default: str = ""
    required: bool = True
    help: str = ""


class HostControl(Protocol):
    provider_id: str
    def attach_command(self, facts: object) -> tuple[str, ...] | None: ...
    def observe(self, facts: object, handle: object | None = None) -> object: ...
    def finish(self, facts: object, handle: object | None = None) -> object: ...


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


@runtime_checkable
class RegistryBindable(Protocol):
    """Explicit opt-in for Host contributions that need Registry lookups.

    Implementing this named protocol — not any generic ``bind`` attribute —
    is the only way a contribution receives the ExtensionRegistry.  Binding
    happens once per contribution during canonical environment activation;
    implementations must be side-effect free (no processes, no runtime
    leases, no credential materialization) and idempotent for the same
    registry.
    """

    def bind_registry(self, registry: ExtensionRegistry) -> None: ...
