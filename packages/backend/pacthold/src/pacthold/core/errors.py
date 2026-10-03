"""Typed contract errors for the C1 Pacthold public entry (specs/010 T004).

Every failure surfaced by the neutral core contract layer is one of these
types (or a subclass). Construction-time DTO failures carry
``CoreDTOError`` and are also ``ValueError`` so existing callers that catch
``ValueError`` keep working; registration/dispatch refusals are dedicated
typed errors (the dispatch refusals were added with the T008 wiring;
``ContractWiringPending`` is its deprecated placeholder marker and is never
raised any more).
"""
from __future__ import annotations


class CoreError(RuntimeError):
    """Base class for every typed Pacthold core-contract failure."""


class CoreDTOError(CoreError, ValueError):
    """A C1 DTO was constructed with values that violate its contract.

    Also a ``ValueError``: the work_core registry precedent validated ids at
    construction with plain ``ValueError``; the C1 layer keeps that catch
    surface while adding an importable typed class.
    """


class InvalidProviderIdError(CoreDTOError):
    """A provider id failed the component-id rule (work_core.registry parity)."""


class InvalidContractIdError(CoreDTOError):
    """A contract id failed the versioned-contract rule (registry parity)."""


class RegistrationConflictError(CoreError):
    """A contract/provider id is already claimed by another owner's batch."""


class MissingContractReferenceError(CoreError):
    """A staged provider declared a contract neither in its batch nor active."""


class BatchAlreadyUsedError(CoreError):
    """A committed (consumable) batch must be removed via ``unregister``,
    never rolled back; rollback is only for unused staged batches."""


class OwnerBusyError(CoreError):
    """``unregister`` refused: the owner still has active or unknown leases."""


class OwnerNotRegisteredError(CoreError):
    """No committed batch exists for this owner."""


class ReconcileUnsupportedError(CoreError):
    """A provider whose descriptor declares ``reconcile_support=UNSUPPORTED``
    was asked to reconcile. Callers must read the descriptor first; this is
    the typed unsupported refusal required by C1."""


class ContractWiringPending(CoreError):
    """DEPRECATED (specs/010 T008): the honest placeholder the T004 contract
    checkpoint raised from ``submit``/``query``/``request_stop`` while the
    dispatch state machine was unwired.  T008 delivered the machine and no
    code path raises this any more; the class stays exported (and test-
    importable) purely so the "refusal is not still a placeholder" negative
    guards in the US1 suite can keep naming what they rule out."""


class RuntimeClosedError(CoreError):
    """The ``CoreRuntime`` was already closed."""


# ---------------------------------------------------------------------------
# dispatch refusals (specs/010 T008; data-model.md Operation/Lease/Execution)
# ---------------------------------------------------------------------------


class DispatchError(CoreError):
    """Base class for every typed refusal of the dispatch surface."""


class PlanDigestConflictError(DispatchError):
    """The same ``request_key`` was replayed with a different content digest.
    data-model.md ExecutionPlan: "同键不同摘要拒绝" — refused before any
    side effect and never dispatched a second time."""


class ProviderNotRegisteredError(DispatchError):
    """The plan names a provider that is not registered.  The core never
    implicitly selects a same-contract candidate (FR-002)."""


class ContractNotRegisteredError(DispatchError):
    """A requirement's contract is not registered, or its named provider
    does not declare support for it."""


class ProviderVersionMismatchError(DispatchError):
    """The plan's ``provider_version`` differs from the registered
    provider's declared descriptor version."""


class UnknownExecutionError(DispatchError):
    """No Execution row exists for this execution_id in this instance's store."""


class UnknownOperationError(DispatchError):
    """No Operation row exists for this (execution_id, operation_key)."""


class TerminalExecutionError(DispatchError):
    """A write path was asked to change an Execution that already reached an
    irreversible terminal state (data-model: 终态不可逆)."""
