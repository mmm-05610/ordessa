"""Generic capability registry: validate, publish and resolve F1 capabilities.

The registry knows no domain. It accepts built ``Capability`` objects, validates
the frozen contract (unique owned ids, canonical descriptor digest, schema
shape, handler equality), and resolves operation ids to their handler. It never
imports an owner or a concrete provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping

from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, ContractError, OperationDescriptor,
    OperationHandler, validate_capability,
)


class RegistryError(ContractError):
    """A capability cannot be published under this registry's rules."""


@dataclass(frozen=True)
class RegisteredOperation:
    capability_id: str
    descriptor: OperationDescriptor
    handler: OperationHandler


class CapabilityRegistry:
    """Published capabilities and their operation handlers."""

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityDescriptor] = {}
        self._operations: dict[str, RegisteredOperation] = {}
        self._frozen = False

    @property
    def capabilities(self) -> Mapping[str, CapabilityDescriptor]:
        return MappingProxyType(dict(self._capabilities))

    @property
    def operations(self) -> Mapping[str, RegisteredOperation]:
        return MappingProxyType(dict(self._operations))

    def register(self, capability: Capability) -> CapabilityDescriptor:
        """Validate and publish one capability; refuse any ambiguous identity."""
        if self._frozen:
            raise RegistryError('CONFLICT', 'registry is frozen for publication')
        try:
            descriptor = validate_capability(capability)
        except ContractError as error:
            raise RegistryError(error.code, error.message) from error
        if descriptor.id in self._capabilities:
            raise RegistryError('CONFLICT', f'capability id already registered: {descriptor.id}')
        for operation in descriptor.operations:
            if operation.id in self._operations:
                raise RegistryError('CONFLICT', f'operation id already registered: {operation.id}')
        self._capabilities[descriptor.id] = descriptor
        for operation in descriptor.operations:
            self._operations[operation.id] = RegisteredOperation(
                capability_id=descriptor.id, descriptor=operation,
                handler=capability.handlers[operation.id])
        return descriptor

    def freeze(self) -> None:
        """Close publication; later registrations are refused."""
        self._frozen = True

    def resolve(self, operation_id: str) -> RegisteredOperation:
        try:
            return self._operations[operation_id]
        except KeyError:
            raise RegistryError('CAPABILITY_UNSUPPORTED',
                                f'operation is not registered: {operation_id}') from None

    def descriptor(self, operation_id: str) -> OperationDescriptor:
        return self.resolve(operation_id).descriptor

    def registration_order(self) -> tuple[str, ...]:
        return tuple(self._capabilities)


def build_registry(capabilities) -> CapabilityRegistry:
    """Publish an explicit sequence of built capabilities in order."""
    registry = CapabilityRegistry()
    for capability in capabilities:
        registry.register(capability)
    registry.freeze()
    return registry


__all__ = ['RegistryError', 'RegisteredOperation', 'CapabilityRegistry', 'build_registry']
