"""Provider registration without Core knowledge of individual providers."""
from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
import re
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .errors import CapabilityUnsupported, ProviderUnavailable
from .models import Ref
from ..resource_contracts import CONTRACT_TYPES


_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CONTRACT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*@[1-9][0-9]*$")


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    display_name: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _COMPONENT_ID.fullmatch(self.id):
            raise ValueError(f"invalid provider id: {self.id!r}")
        for name, value in (
            ("display_name", self.display_name),
            ("version", self.version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider descriptor {name} is required")


class ResourceProvider(Protocol):
    """Resolve a provider-owned Ref into a shared Resource Contract value."""

    supported_contract_ids: frozenset[str]

    def descriptor(self) -> ProviderDescriptor: ...
    def resolve(self, contract_id: str, ref: Ref, *, context: ResourceResolutionContext | None = None) -> object: ...


@dataclass(frozen=True)
class ResolvedExecutionInput:
    """One ephemeral exact Ref/value handoff to an ExecutionProvider."""

    contract_id: str
    ref: Ref
    value: object


@dataclass(frozen=True)
class ResourceResolutionContext:
    """Ephemeral scope for provider materialization; never persisted in a Ref."""
    execution_id: str
    dispatch_id: str | None = None


@dataclass(frozen=True)
class ExecutionStartRequest:
    """Non-persistent provider invocation DTO for one Dispatch attempt."""

    execution_id: str
    dispatch_id: str
    inputs_digest: str
    resolved_inputs: tuple[ResolvedExecutionInput, ...]

    @property
    def inputs(self) -> Mapping[str, tuple[object, ...]]:
        """Legacy read-only grouped view derived from ``resolved_inputs``."""
        grouped: dict[str, list[object]] = {}
        for item in self.resolved_inputs:
            grouped.setdefault(item.contract_id, []).append(item.value)
        return MappingProxyType({key: tuple(values) for key, values in grouped.items()})


class ResolutionEffect(str, Enum):
    PURE = "pure"
    IDEMPOTENT_MATERIALIZATION = "idempotent_materialization"


@dataclass(frozen=True)
class ExecutionPreflightRequest:
    execution_id: str
    dispatch_id: str
    inputs_digest: str
    exact_inputs: tuple[tuple[str, Ref], ...]
    resolved_inputs: tuple[ResolvedExecutionInput, ...]


class RecoverySupport(str, Enum):
    NONE = "none"
    OBSERVE = "observe"
    CONTROL = "control"


@dataclass(frozen=True)
class ExecutionStartReceipt:
    execution_id: str
    dispatch_id: str
    inputs_digest: str
    recovery_support: RecoverySupport = RecoverySupport.NONE
    correlation_ref: Ref | None = None
    # A provider may keep an in-process control handle for direct callers.  It
    # is explicitly ephemeral: Core persists only the bounded correlation Ref.
    runtime_handle: object | None = field(default=None, repr=False, compare=False)

    def __getattr__(self, name: str) -> object:
        if self.runtime_handle is None:
            raise AttributeError(name)
        return getattr(self.runtime_handle, name)


@dataclass(frozen=True)
class DispatchReceipt:
    execution_id: str
    dispatch_id: str
    state: str
    inputs_digest: str
    recovery_support: RecoverySupport | None = None
    correlation_ref: Ref | None = None
    legacy_correlation: str | None = None


class ExecutionProvider(Protocol):
    def descriptor(self) -> ProviderDescriptor: ...
    def capabilities(self) -> Mapping[str, str]: ...
    def input_limits(self) -> Mapping[str, tuple[int, int | None]]: ...
    def start(self, request: ExecutionStartRequest) -> ExecutionStartReceipt: ...
    def observe(self, native_ref: Any) -> Any: ...


class ExtensionRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ExecutionProvider] = {}
        self._resource_providers: dict[str, ResourceProvider] = {}
        self._resource_descriptors: dict[str, ProviderDescriptor] = {}
        # Built-ins use the same runtime registry as third-party Contracts.
        # CONTRACT_TYPES remains an immutable compatibility catalog, not the
        # dispatch-time source of truth.  Shared runtime contracts
        # (runtime-host/sandbox/terminal-session) are Root-owned and are
        # registered exactly once by the Root Extension bootstrap; this
        # module never imports the extension layer.
        self._contract_types: dict[str, type] = dict(CONTRACT_TYPES)
        self._root_shared_contract_ids: frozenset[str] = frozenset()

    @staticmethod
    def _validate_contract_type(contract: type) -> tuple[str, type]:
        if not isinstance(contract, type):
            raise ValueError("resource contract must be a Python type")
        contract_id = getattr(contract, "contract_id", None)
        if not isinstance(contract_id, str) or not _CONTRACT_ID.fullmatch(contract_id):
            raise ValueError(
                "resource contract must declare a versioned contract_id like "
                "vendor.name@1"
            )
        if not is_dataclass(contract) or not contract.__dataclass_params__.frozen:
            raise ValueError("resource contract must be a frozen dataclass")
        return contract_id, contract

    def register_root_shared_contract(self, contract: type) -> None:
        """Register one Root-owned shared runtime contract (bootstrap only).

        A Root-owned id accepts only the exact canonical Python type.  Plugin
        bundles re-declaring that identical canonical type are tolerated, so
        several providers of one kind can coexist; every other duplicate
        stays fail closed.
        """
        contract_id, contract_type = self._validate_contract_type(contract)
        existing = self._contract_types.get(contract_id)
        if existing is not None and existing is not contract_type:
            raise ValueError(f"Root shared contract id collision: {contract_id}")
        self._contract_types[contract_id] = contract_type
        self._root_shared_contract_ids = frozenset(
            {*self._root_shared_contract_ids, contract_id}
        )

    def root_shared_contract_ids(self) -> frozenset[str]:
        return self._root_shared_contract_ids

    def register_contract(self, contract: type) -> None:
        contract_id, contract_type = self._validate_contract_type(contract)
        if contract_id in self._root_shared_contract_ids:
            if self._contract_types[contract_id] is not contract_type:
                raise ValueError(
                    "contract id is Root-owned shared runtime authority: "
                    f"{contract_id}"
                )
            return
        if contract_id in self._contract_types:
            raise ValueError(f"resource contract already registered: {contract_id}")
        self._contract_types[contract_id] = contract_type

    def get_contract_type(self, contract_id: str) -> type:
        try:
            return self._contract_types[contract_id]
        except KeyError as exc:
            raise ValueError(f"unknown resource contract: {contract_id}") from exc

    def contract_types(self) -> Mapping[str, type]:
        return MappingProxyType(dict(self._contract_types))

    def register_components(
        self,
        *,
        contracts: tuple[type, ...] = (),
        resource_providers: tuple[ResourceProvider, ...] = (),
        execution_providers: tuple[ExecutionProvider, ...] = (),
    ) -> None:
        """Atomically add one extension bundle to this process registry."""
        staged = object.__new__(ExtensionRegistry)
        staged._providers = dict(self._providers)
        staged._resource_providers = dict(self._resource_providers)
        staged._resource_descriptors = dict(self._resource_descriptors)
        staged._contract_types = dict(self._contract_types)
        staged._root_shared_contract_ids = self._root_shared_contract_ids
        for contract in contracts:
            staged.register_contract(contract)
        for provider in resource_providers:
            staged.register_resource_provider(provider)
        for provider in execution_providers:
            staged.register_execution_provider(provider)
        self._providers = staged._providers
        self._resource_providers = staged._resource_providers
        self._resource_descriptors = staged._resource_descriptors
        self._contract_types = staged._contract_types

    def register_execution_provider(self, provider: ExecutionProvider) -> None:
        descriptor = provider.descriptor()
        if not descriptor.id:
            raise ValueError("provider descriptor id is required")
        if descriptor.id in self._providers:
            raise ValueError(f"provider already registered: {descriptor.id}")
        self._providers[descriptor.id] = provider

    def register_resource_provider(
        self,
        provider_or_id: ResourceProvider | str,
        provider: ResourceProvider | None = None,
    ) -> None:
        """Register a ResourceProvider.

        Third-party providers use ``register_resource_provider(provider)`` and
        must expose a descriptor.  The explicit-id form remains temporarily
        supported for existing in-tree callers and test doubles.
        """
        if provider is None:
            resource_provider = provider_or_id
            descriptor_method = getattr(resource_provider, "descriptor", None)
            if not callable(descriptor_method):
                raise ValueError("resource provider must expose descriptor()")
            descriptor = descriptor_method()
            if not isinstance(descriptor, ProviderDescriptor):
                raise ValueError("resource provider descriptor() returned invalid value")
            provider_id = descriptor.id
        else:
            if not isinstance(provider_or_id, str):
                raise ValueError("explicit resource provider id must be a string")
            provider_id = provider_or_id
            resource_provider = provider
            descriptor_method = getattr(resource_provider, "descriptor", None)
            if callable(descriptor_method):
                descriptor = descriptor_method()
                if descriptor.id != provider_id:
                    raise ValueError("resource provider id differs from descriptor id")
            else:
                descriptor = ProviderDescriptor(provider_id, provider_id, "legacy")
        if not provider_id:
            raise ValueError("resource provider id is required")
        supported = getattr(resource_provider, "supported_contract_ids", None)
        if not isinstance(supported, frozenset):
            raise ValueError("resource provider must declare supported_contract_ids")
        unknown = supported.difference(self._contract_types)
        if unknown:
            raise ValueError(
                "resource provider declares unknown contracts: "
                + ", ".join(sorted(unknown))
            )
        if provider_id in self._resource_providers:
            raise ValueError(f"resource provider already registered: {provider_id}")
        self._resource_providers[provider_id] = resource_provider
        self._resource_descriptors[provider_id] = descriptor

    def get_resource_provider(self, provider_id: str) -> ResourceProvider:
        try:
            return self._resource_providers[provider_id]
        except KeyError as exc:
            raise ProviderUnavailable(
                f"resource provider unavailable: {provider_id}"
            ) from exc

    def get(self, provider_id: str) -> ExecutionProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderUnavailable(f"provider unavailable: {provider_id}") from exc

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(self._providers[key].descriptor() for key in sorted(self._providers))

    def resource_descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(self._resource_descriptors[key] for key in sorted(self._resource_descriptors))

    def resource_providers(self) -> tuple[ResourceProvider, ...]:
        """Read-only snapshot of the registered ResourceProviders."""
        return tuple(self._resource_providers[key] for key in sorted(self._resource_providers))

    def execution_providers(self) -> tuple[ExecutionProvider, ...]:
        """Read-only snapshot of the registered ExecutionProviders."""
        return tuple(self._providers[key] for key in sorted(self._providers))

    def require_capability(self, provider_id: str, operation: str) -> ExecutionProvider:
        """Return a provider only when it declares the requested operation."""
        provider = self.get(provider_id)
        if provider.capabilities().get(operation) not in {"supported", "emulated"}:
            raise CapabilityUnsupported(f"{provider_id} does not support {operation}")
        return provider
