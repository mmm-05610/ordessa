"""Provider-facing protocol declarations for C1 (signatures are load-bearing).

These are pure ``Protocol`` shapes: declaring them does not implement any
dispatch behaviour, and the method bodies below are the required ``...``
stubs of the protocol, not fake-success stubs.  ``pacthold.public`` re-exports
them so plugins can type against the frozen C1 vocabulary.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .dtos import (
    AcquireRequest,
    AcquireResult,
    Observation,
    ReleaseRequest,
    ReleaseResult,
    ReconcileRequest,
    ReconcileResult,
    RunHandle,
    StartRequest,
    StartResult,
    StopRequest,
    StopResult,
)
from .descriptors import ResourceProviderDescriptor


@runtime_checkable
class ResourceProvider(Protocol):
    """Acquire/release/reconcile one declared contract; no registry access."""

    def describe(self) -> ResourceProviderDescriptor: ...

    def acquire(self, request: AcquireRequest) -> AcquireResult: ...

    def release(self, request: ReleaseRequest) -> ReleaseResult: ...

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult: ...


@runtime_checkable
class ExecutionProvider(Protocol):
    """Start/observe/stop one execution declared by an ExecutionPlan."""

    def start(self, request: StartRequest) -> StartResult: ...

    def observe(self, handle: RunHandle) -> Observation: ...

    def stop(self, request: StopRequest) -> StopResult: ...
