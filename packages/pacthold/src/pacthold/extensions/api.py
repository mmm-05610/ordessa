"""Stable, deliberately small API imported by third-party plugin packages.

 specs/010 T009: this module keeps only the plugin-loading mechanism
(descriptors, context, the neutral registration slots, the finalization and
selector protocols, and registry binding).  Business slot types — profile
envelopes, provider host controls, continuation routes, harness profile
managers and the credential materialization protocol — live in the
compatibility assembly (``pacthold_runtime_compat``), which may import the
kernel but is never imported by it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, runtime_checkable

from ..work_core.models import Ref
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
    """Components contributed to one process-local extension registry.

     specs/010 T009: only kernel-neutral slots live here.  The product SDK
    (``pacthold_runtime_compat.api.PluginRegistration``) extends this class
    with the business slots (harness managers, continuation routes,
    credential materializers, transport operations); the loader and the
    neutral catalog accept both shapes because the extension is a subclass.
    """

    contracts: tuple[type, ...] = ()
    resource_providers: tuple[ResourceProvider, ...] = ()
    execution_providers: tuple[ExecutionProvider, ...] = ()
    finalization_contributors: tuple[object, ...] = ()
    resource_selectors: tuple[object, ...] = ()
    host_controls: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        for name in ("contracts", "resource_providers", "execution_providers", "finalization_contributors", "resource_selectors", "host_controls"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"PluginRegistration.{name} must be a tuple")


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
