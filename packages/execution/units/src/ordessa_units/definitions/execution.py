"""Ephemeral exact-input handoff to a Unit-owned execution attempt.

These values neither create a Work nor authorize an invocation. Resource
locators must come from their actual owner; historical Work refs are rejected.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from ordessa_agents.harness.definitions import (
    NativeProfileRef, NativeCredentialRef, NativeContinuationRef,
)
from ordessa_units.bindings.materials import ResourceRef

ExecutionInputRef = ResourceRef | NativeProfileRef | NativeCredentialRef | NativeContinuationRef
_INPUT_TYPES = (ResourceRef, NativeProfileRef, NativeCredentialRef, NativeContinuationRef)

@dataclass(frozen=True)
class ResolvedExecutionInput:
    contract_id: str
    ref: ExecutionInputRef
    value: object

    def __post_init__(self) -> None:
        if not isinstance(self.contract_id, str) or not self.contract_id:
            raise ValueError("execution input contract_id is required")
        if type(self.ref) not in _INPUT_TYPES:
            raise TypeError("execution input requires an owner-issued resource or native locator")
        if type(self.ref) is ResourceRef and self.ref.contract_id != self.contract_id:
            raise ValueError("execution input resource contract mismatch")

@dataclass(frozen=True)
class ExecutionStartRequest:
    execution_id: str
    dispatch_id: str
    inputs_digest: str
    resolved_inputs: tuple[ResolvedExecutionInput, ...]

    def __post_init__(self) -> None:
        for name in ("execution_id", "dispatch_id", "inputs_digest"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"execution request {name} is required")
        if type(self.resolved_inputs) is not tuple or any(
                type(item) is not ResolvedExecutionInput for item in self.resolved_inputs):
            raise TypeError("resolved_inputs must contain exact ResolvedExecutionInput values")

    @property
    def inputs(self) -> Mapping[str, tuple[object, ...]]:
        grouped: dict[str, list[object]] = {}
        for item in self.resolved_inputs:
            grouped.setdefault(item.contract_id, []).append(item.value)
        return MappingProxyType({key: tuple(values) for key, values in grouped.items()})

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
    correlation_ref: NativeContinuationRef | None = None
    runtime_handle: object | None = field(default=None, repr=False, compare=False)

    def __getattr__(self, name: str) -> object:
        if self.runtime_handle is None:
            raise AttributeError(name)
        return getattr(self.runtime_handle, name)

class InvalidStartReceipt(ValueError):
    pass

def validate_start_receipt(provider_id: str, request: ExecutionStartRequest,
                           receipt: ExecutionStartReceipt) -> None:
    """Keep exact identity/recovery checks before accepting an attempt receipt."""
    if type(receipt) is not ExecutionStartReceipt:
        raise InvalidStartReceipt("provider.start() must return ExecutionStartReceipt")
    if (receipt.execution_id != request.execution_id or receipt.dispatch_id != request.dispatch_id
            or receipt.inputs_digest != request.inputs_digest):
        raise InvalidStartReceipt("start receipt identity does not match request")
    if type(receipt.recovery_support) is not RecoverySupport:
        raise InvalidStartReceipt("start receipt recovery_support is invalid")
    correlation = receipt.correlation_ref
    if receipt.recovery_support is not RecoverySupport.NONE and correlation is None:
        raise InvalidStartReceipt("recoverable receipt requires correlation_ref")
    if correlation is not None:
        if type(correlation) is not NativeContinuationRef:
            raise InvalidStartReceipt("receipt requires a native continuation locator")
        if correlation.provider != provider_id:
            raise InvalidStartReceipt("receipt correlation must belong to ExecutionProvider")
