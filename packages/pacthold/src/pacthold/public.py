"""``pacthold.public`` — the stable C1 public entry of the Pacthold kernel.

This module only re-exports.  Its entire dependency chain is
``pacthold.core.*`` plus the standard library; it never imports
``pacthold.work_core``, ``pacthold.resource_contracts``,
``pacthold.extensions``, ``pacthold.storage.database`` or
``pacthold.cli`` (boundary-locked test:
``tests/platform/test_public_contract.py``).

Symbol → defining module landing table (resolves reports/A.md finding I2;
``pacthold.public`` is a facade only over these):

+--------------------------------+--------------------------------------------+
| symbol                         | defining module                            |
+--------------------------------+--------------------------------------------+
| CoreRuntime, ShutdownReport    | pacthold.core.runtime                      |
| CoreStore                      | pacthold.core.store                        |
| CoreContributionSet            | pacthold.core.registration                 |
| CoreRegistration               | pacthold.core.registration                 |
| CoreRegistrySnapshot           | pacthold.core.registration                 |
| ResourceProvider,              | pacthold.core.protocols                    |
| ExecutionProvider              |                                            |
| ResourceProviderDescriptor     | pacthold.core.descriptors                  |
| AcquireRequest / AcquireResult | pacthold.core.dtos                         |
| ReleaseRequest / ReleaseResult | pacthold.core.dtos                         |
| ReconcileRequest /             | pacthold.core.dtos                         |
|   ReconcileResult              |                                            |
| StartRequest / StartResult /   | pacthold.core.dtos                         |
|   StopRequest / StopResult /   |                                            |
|   RunHandle / Observation /    |                                            |
|   ResolvedInputDeclaration     |                                            |
| ExecutionPlan,                 | pacthold.core.plan                         |
|   ResourceRequirement          |                                            |
| SubmitResult, ExecutionView,   | pacthold.core.dispatch (T008; T010         |
|   LeaseView,                   |   reconcile + resume association)   |
|   StopDispatchResult           |                                            |
| OwnershipKind, LeaseState,     | pacthold.core.enums                        |
|   OperationState,              |                                            |
|   ExecutionState,              |                                            |
|   ReconcileSupport,            |                                            |
|   ObservationKind,             |                                            |
|   AcquireOutcome,              |                                            |
|   ReleaseOutcome,              |                                            |
|   ReconcileOutcome,            |                                            |
|   StartOutcome, StopOutcome    |                                            |
| CoreError and its typed        | pacthold.core.errors                       |
|   subclasses (CoreDTOError,    |                                            |
|   InvalidProviderIdError,      |                                            |
|   InvalidContractIdError,      |                                            |
|   RegistrationConflictError,   |                                            |
|   MissingContractReferenceError|                                            |
|   BatchAlreadyUsedError,       |                                            |
|   OwnerBusyError,              |                                            |
|   OwnerNotRegisteredError,     |                                            |
|   ReconcileUnsupportedError,   |                                            |
|   ContractWiringPending        |                                            |
|   (deprecated placeholder),    |                                            |
|   RuntimeClosedError,          |                                            |
|   DispatchError + typed        |                                            |
|   dispatch refusals            |                                            |
|   (PlanDigestConflictError,    |                                            |
|   ProviderNotRegisteredError,  |                                            |
|   ContractNotRegisteredError,  |                                            |
|   ProviderVersionMismatchError,|                                            |
|   UnknownExecutionError,       |                                            |
|   UnknownOperationError,       |                                            |
|   TerminalExecutionError)      |                                            |
+--------------------------------+--------------------------------------------+

Deliberate facade-scope decisions (specs/010 T004 contract checkpoint;
dispatch entries wired by T008):

* work_core value objects (``Ref``/``Work``/``ProviderDescriptor``) are NOT
  re-exported: importing any ``pacthold.work_core`` submodule executes the
  package ``__init__`` which imports ``registry.py`` and therefore
  ``resource_contracts`` — the reverse dependency the facade must avoid.
  ``ResourceProviderDescriptor`` re-declares the same id/display_name/
  version validation rules, and ``ExecutionPlan.work_id`` carries the Work
  association as an id string ("使用既有 Work 关联", no new Work table here).
* I1 naming mapping: ``CoreStore`` is the instance-level Store that replaces
  the process-global connection of ``work_core/db.py`` for the C1 surface.
  The T008 dispatch machine lives inside ``pacthold.core`` (pure stdlib +
  core modules) and writes only the neutral instance tables
  ``core_execution``/``core_operation``; it never imports work_core.
* ``submit`` / ``query`` / ``request_stop`` are wired since T008: real
  validation, intent-before-side-effect, idempotency and typed refusals
  (``ContractWiringPending`` is a deprecated placeholder that is never
  raised any more; the class stays exported for the negative guards).
* T010 (US1 lifecycle/recovery) added no new exported symbol name; it widened
  already-exported ones, all still defined under ``pacthold.core``:
  ``CoreRuntime.reconcile(execution_id, operation_key)`` — the evidence-only
  reconciliation entry of data-model.md "Recovery" (delegates to
  ``pacthold.core.dispatch``); ``ExecutionPlan.previous_execution_ref`` /
  ``ExecutionView.previous_execution_ref`` — the optional Session-resume
  association naming the terminal execution a new run continues (US1.3);
  ``LeaseView.reconcile_ref`` — the evidence reference a reconcile verdict
  persisted.  Those live in the neutral instance columns
  ``core_execution.previous_execution_ref`` /
  ``core_operation.reconcile_ref``.  ``CoreRuntime`` now derives its
  unresolved facts (``owner_busy`` / ``unregister`` / ``close``) from the
  store, so a restarted runtime reports what is durable rather than what one
  process happened to remember; reading those facts is pure SQL and can never
  contact a provider (FR-004 "reconcile, never spawn").
"""
from __future__ import annotations

from .core import (
    AcquireOutcome,
    AcquireRequest,
    AcquireResult,
    BatchAlreadyUsedError,
    ContractNotRegisteredError,
    ContractWiringPending,
    CoreContributionSet,
    CoreDTOError,
    CoreError,
    CoreRegistration,
    CoreRegistrySnapshot,
    CoreRuntime,
    CoreStore,
    DispatchError,
    ExecutionPlan,
    ExecutionProvider,
    ExecutionState,
    ExecutionView,
    InvalidContractIdError,
    InvalidProviderIdError,
    LeaseState,
    LeaseView,
    MissingContractReferenceError,
    Observation,
    ObservationKind,
    OperationState,
    OwnerBusyError,
    OwnerNotRegisteredError,
    OwnershipKind,
    PlanDigestConflictError,
    ProviderNotRegisteredError,
    ProviderVersionMismatchError,
    ReconcileOutcome,
    ReconcileRequest,
    ReconcileResult,
    ReconcileSupport,
    ReconcileUnsupportedError,
    RegistrationConflictError,
    ReleaseOutcome,
    ReleaseRequest,
    ReleaseResult,
    ResolvedInputDeclaration,
    ResourceProvider,
    ResourceProviderDescriptor,
    ResourceRequirement,
    RunHandle,
    RuntimeClosedError,
    ShutdownReport,
    StartOutcome,
    StartRequest,
    StartResult,
    StopDispatchResult,
    StopOutcome,
    StopRequest,
    StopResult,
    SubmitResult,
    TerminalExecutionError,
    UnknownExecutionError,
    UnknownOperationError,
)

__all__ = [
    "AcquireOutcome",
    "AcquireRequest",
    "AcquireResult",
    "BatchAlreadyUsedError",
    "ContractNotRegisteredError",
    "ContractWiringPending",
    "CoreContributionSet",
    "CoreDTOError",
    "CoreError",
    "CoreRegistration",
    "CoreRegistrySnapshot",
    "CoreRuntime",
    "CoreStore",
    "DispatchError",
    "ExecutionPlan",
    "ExecutionProvider",
    "ExecutionState",
    "ExecutionView",
    "InvalidContractIdError",
    "InvalidProviderIdError",
    "LeaseState",
    "LeaseView",
    "MissingContractReferenceError",
    "Observation",
    "ObservationKind",
    "OperationState",
    "OwnerBusyError",
    "OwnerNotRegisteredError",
    "OwnershipKind",
    "PlanDigestConflictError",
    "ProviderNotRegisteredError",
    "ProviderVersionMismatchError",
    "ReconcileOutcome",
    "ReconcileRequest",
    "ReconcileResult",
    "ReconcileSupport",
    "ReconcileUnsupportedError",
    "RegistrationConflictError",
    "ReleaseOutcome",
    "ReleaseRequest",
    "ReleaseResult",
    "ResolvedInputDeclaration",
    "ResourceProvider",
    "ResourceProviderDescriptor",
    "ResourceRequirement",
    "RunHandle",
    "RuntimeClosedError",
    "ShutdownReport",
    "StartOutcome",
    "StartRequest",
    "StartResult",
    "StopDispatchResult",
    "StopOutcome",
    "StopRequest",
    "StopResult",
    "SubmitResult",
    "TerminalExecutionError",
    "UnknownExecutionError",
    "UnknownOperationError",
]
