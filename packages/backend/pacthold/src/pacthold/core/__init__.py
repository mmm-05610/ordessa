"""``pacthold.core`` — neutral C1 contract implementation, zero globals.

Contains only standard-library machinery (sqlite3 store, dataclasses,
enums, protocols, in-process registry, instance-level dispatch).  It must
never import ``work_core``, ``resource_contracts``, ``extensions``,
``storage.database`` or ``cli`` — the boundary test in
``packages/pacthold/tests/platform/test_public_contract.py`` locks this.
"""
from __future__ import annotations

from .descriptors import ResourceProviderDescriptor
from .dispatch import (
    ExecutionView,
    LeaseView,
    StopDispatchResult,
    SubmitResult,
)
from .dtos import (
    AcquireRequest,
    AcquireResult,
    Observation,
    ReleaseRequest,
    ReleaseResult,
    ReconcileRequest,
    ReconcileResult,
    ResolvedInputDeclaration,
    RunHandle,
    StartRequest,
    StartResult,
    StopRequest,
    StopResult,
)
from .enums import (
    AcquireOutcome,
    ExecutionState,
    LeaseState,
    ObservationKind,
    OperationState,
    OwnershipKind,
    ReconcileOutcome,
    ReconcileSupport,
    ReleaseOutcome,
    StartOutcome,
    StopOutcome,
)
from .errors import (
    BatchAlreadyUsedError,
    ContractNotRegisteredError,
    ContractWiringPending,
    CoreDTOError,
    CoreError,
    DispatchError,
    InvalidContractIdError,
    InvalidProviderIdError,
    MissingContractReferenceError,
    OwnerBusyError,
    OwnerNotRegisteredError,
    PlanDigestConflictError,
    ProviderNotRegisteredError,
    ProviderVersionMismatchError,
    ReconcileUnsupportedError,
    RegistrationConflictError,
    RuntimeClosedError,
    TerminalExecutionError,
    UnknownExecutionError,
    UnknownOperationError,
)
from .plan import ExecutionPlan, ResourceRequirement
from .protocols import ExecutionProvider, ResourceProvider
from .registration import (
    CoreContributionSet,
    CoreRegistration,
    CoreRegistrySnapshot,
)
from .runtime import CoreRuntime, ShutdownReport
from .store import CoreStore

__all__ = [
    # runtime & registration
    "CoreRuntime",
    "CoreRegistration",
    "CoreContributionSet",
    "CoreRegistrySnapshot",
    "CoreStore",
    "ShutdownReport",
    # protocols & descriptor
    "ResourceProvider",
    "ExecutionProvider",
    "ResourceProviderDescriptor",
    # plan
    "ExecutionPlan",
    "ResourceRequirement",
    # request/result DTOs
    "ResolvedInputDeclaration",
    "AcquireRequest",
    "AcquireResult",
    "ReleaseRequest",
    "ReleaseResult",
    "ReconcileRequest",
    "ReconcileResult",
    "StartRequest",
    "StartResult",
    "RunHandle",
    "Observation",
    "StopRequest",
    "StopResult",
    # dispatch result views (T008)
    "SubmitResult",
    "ExecutionView",
    "LeaseView",
    "StopDispatchResult",
    # vocabularies
    "OwnershipKind",
    "LeaseState",
    "OperationState",
    "ExecutionState",
    "ReconcileSupport",
    "ObservationKind",
    "AcquireOutcome",
    "ReleaseOutcome",
    "ReconcileOutcome",
    "StartOutcome",
    "StopOutcome",
    # typed errors
    "CoreError",
    "CoreDTOError",
    "InvalidProviderIdError",
    "InvalidContractIdError",
    "RegistrationConflictError",
    "MissingContractReferenceError",
    "BatchAlreadyUsedError",
    "OwnerBusyError",
    "OwnerNotRegisteredError",
    "ReconcileUnsupportedError",
    "ContractWiringPending",
    "RuntimeClosedError",
    "DispatchError",
    "PlanDigestConflictError",
    "ProviderNotRegisteredError",
    "ContractNotRegisteredError",
    "ProviderVersionMismatchError",
    "UnknownExecutionError",
    "UnknownOperationError",
    "TerminalExecutionError",
]
