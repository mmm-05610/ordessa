"""C1 request/result DTOs: construction-time validation, typed failure.

All DTOs are frozen dataclasses over closed vocabularies from
``pacthold.core.enums``.  Rules that encode the specs/010 contract directly:

* every request carries ``operation_key``, ``execution_id`` and the declared
  resolved inputs (``declared_inputs``); inputs are digests, never plaintext
  credentials;
* every result is a three-way discriminant (success / refused / unknown) over
  its own closed enum — no bool guessing, and the value sets are never
  merged across facts (execution.contracts precedent);
* ``refused`` carries a stable ``error_code`` and promises zero side effect;
* ``unknown`` stays queryable by (execution_id, operation_key) and may never
  be fabricated into another verdict (no ``cancelled`` exists in any result
  enum; FR-004);
* ``borrowed`` releases only the reference, never the original object
  (semantic promise for T008 dispatch; the DTO records ownership honestly).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .descriptors import validate_component_id, validate_contract_id
from .enums import (
    AcquireOutcome,
    LeaseState,
    ObservationKind,
    OwnershipKind,
    ReleaseOutcome,
    ReconcileOutcome,
    StartOutcome,
    StopOutcome,
)
from .errors import CoreDTOError

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _non_blank(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoreDTOError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _validate_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CoreDTOError(f"{name} must be 64-char lowercase hex, got {value!r}")
    return value


def _validate_declared_inputs(value: object) -> tuple["ResolvedInputDeclaration", ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise CoreDTOError("declared_inputs must be a sequence of ResolvedInputDeclaration")
    items = tuple(value)
    for item in items:
        if not isinstance(item, ResolvedInputDeclaration):
            raise CoreDTOError(f"declared_inputs entry must be ResolvedInputDeclaration, got {item!r}")
    return items


def _owned_enum(value: object, enum_cls: type, name: str):
    if not isinstance(value, enum_cls):
        raise CoreDTOError(
            f"{name} must be a {enum_cls.__name__} member (closed vocabulary), got {value!r}"
        )
    return value


@dataclass(frozen=True)
class ResolvedInputDeclaration:
    """One declared, already-resolved input: contract id + content digest."""

    contract_id: str
    input_digest: str

    def __post_init__(self) -> None:
        validate_contract_id(self.contract_id)
        _validate_digest(self.input_digest, "input_digest")


@dataclass(frozen=True)
class AcquireRequest:
    operation_key: str
    execution_id: str
    contract_id: str
    provider_id: str
    ownership: OwnershipKind
    declared_inputs: tuple[ResolvedInputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        validate_contract_id(self.contract_id)
        validate_component_id(self.provider_id, kind="provider")
        _owned_enum(self.ownership, OwnershipKind, "ownership")
        object.__setattr__(self, "declared_inputs", _validate_declared_inputs(self.declared_inputs))


@dataclass(frozen=True)
class AcquireResult:
    outcome: AcquireOutcome
    operation_key: str
    execution_id: str
    lease_id: str | None = None
    safe_handle: str | None = None
    lease_state: LeaseState | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.outcome, AcquireOutcome, "outcome")
        if self.outcome is AcquireOutcome.SUCCESS:
            _non_blank(self.lease_id, "lease_id")
            _non_blank(self.safe_handle, "safe_handle")
            if self.lease_state is not LeaseState.ACQUIRED:
                raise CoreDTOError("a successful acquire must report lease_state=ACQUIRED")
            if self.error_code is not None:
                raise CoreDTOError("success results must not carry an error_code")
        elif self.outcome is AcquireOutcome.REFUSED:
            _non_blank(self.error_code, "error_code")
            if self.lease_id is not None or self.safe_handle is not None or self.lease_state is not None:
                raise CoreDTOError(
                    "a refused acquire promises zero side effect: no lease, handle or state"
                )
        else:  # UNKNOWN
            if self.lease_state not in (None, LeaseState.ACQUIRE_UNKNOWN):
                raise CoreDTOError(
                    "an unknown acquire may only fix lease_state=ACQUIRE_UNKNOWN; "
                    "it must never be fabricated into another verdict"
                )
            if self.safe_handle is not None or self.error_code is not None:
                raise CoreDTOError(
                    "unknown stays queryable via (execution_id, operation_key); "
                    "it carries no handle and no verdict code"
                )


@dataclass(frozen=True)
class ReleaseRequest:
    operation_key: str
    execution_id: str
    lease_id: str
    ownership: OwnershipKind
    safe_handle: str | None = None
    declared_inputs: tuple[ResolvedInputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _non_blank(self.lease_id, "lease_id")
        _owned_enum(self.ownership, OwnershipKind, "ownership")
        if self.safe_handle is not None:
            _non_blank(self.safe_handle, "safe_handle")
        object.__setattr__(self, "declared_inputs", _validate_declared_inputs(self.declared_inputs))


@dataclass(frozen=True)
class ReleaseResult:
    outcome: ReleaseOutcome
    operation_key: str
    execution_id: str
    lease_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.outcome, ReleaseOutcome, "outcome")
        if self.outcome is ReleaseOutcome.SUCCESS:
            _non_blank(self.lease_id, "lease_id")
            if self.error_code is not None:
                raise CoreDTOError("success results must not carry an error_code")
        elif self.outcome is ReleaseOutcome.REFUSED:
            _non_blank(self.error_code, "error_code")
        else:  # UNKNOWN: queryable, never auto-retried, never an implicit release
            if self.lease_id is not None or self.error_code is not None:
                raise CoreDTOError("an unknown release carries no verdict payload")


@dataclass(frozen=True)
class ReconcileRequest:
    operation_key: str
    execution_id: str
    lease_id: str
    safe_handle: str
    declared_inputs: tuple[ResolvedInputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _non_blank(self.lease_id, "lease_id")
        _non_blank(self.safe_handle, "safe_handle")
        object.__setattr__(self, "declared_inputs", _validate_declared_inputs(self.declared_inputs))


@dataclass(frozen=True)
class ReconcileResult:
    outcome: ReconcileOutcome
    operation_key: str
    execution_id: str
    resolution_ref: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.outcome, ReconcileOutcome, "outcome")
        if self.outcome is ReconcileOutcome.SUCCESS:
            _non_blank(self.resolution_ref, "resolution_ref")
            if self.error_code is not None:
                raise CoreDTOError("success results must not carry an error_code")
        elif self.outcome is ReconcileOutcome.REFUSED:
            _non_blank(self.error_code, "error_code")
        else:  # UNKNOWN: still no evidence; the caller keeps asking, never guesses
            if self.resolution_ref is not None or self.error_code is not None:
                raise CoreDTOError("an unknown reconcile carries no verdict payload")


@dataclass(frozen=True)
class StartRequest:
    operation_key: str
    execution_id: str
    provider_id: str
    plan_digest: str
    declared_inputs: tuple[ResolvedInputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        validate_component_id(self.provider_id, kind="provider")
        _validate_digest(self.plan_digest, "plan_digest")
        object.__setattr__(self, "declared_inputs", _validate_declared_inputs(self.declared_inputs))


@dataclass(frozen=True)
class StartResult:
    outcome: StartOutcome
    operation_key: str
    execution_id: str
    run_safe_handle: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.outcome, StartOutcome, "outcome")
        if self.outcome is StartOutcome.SUCCESS:
            _non_blank(self.run_safe_handle, "run_safe_handle")
            if self.error_code is not None:
                raise CoreDTOError("success results must not carry an error_code")
        elif self.outcome is StartOutcome.REFUSED:
            _non_blank(self.error_code, "error_code")
            if self.run_safe_handle is not None:
                raise CoreDTOError("a refused start promises zero spawn: no run handle")
        else:  # UNKNOWN: a start may have happened; query, never blind-redispatch
            if self.run_safe_handle is not None or self.error_code is not None:
                raise CoreDTOError(
                    "an unknown start stays queryable and fabricates nothing"
                )


@dataclass(frozen=True)
class RunHandle:
    execution_id: str
    provider_id: str
    safe_handle: str

    def __post_init__(self) -> None:
        _non_blank(self.execution_id, "execution_id")
        validate_component_id(self.provider_id, kind="provider")
        _non_blank(self.safe_handle, "safe_handle")


@dataclass(frozen=True)
class Observation:
    execution_id: str
    kind: ObservationKind
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.kind, ObservationKind, "kind")
        if self.evidence_ref is not None:
            _non_blank(self.evidence_ref, "evidence_ref")


@dataclass(frozen=True)
class StopRequest:
    operation_key: str
    execution_id: str
    reason: str | None = None
    declared_inputs: tuple[ResolvedInputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        if self.reason is not None:
            _non_blank(self.reason, "reason")
        object.__setattr__(self, "declared_inputs", _validate_declared_inputs(self.declared_inputs))


@dataclass(frozen=True)
class StopResult:
    outcome: StopOutcome
    operation_key: str
    execution_id: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        _non_blank(self.operation_key, "operation_key")
        _non_blank(self.execution_id, "execution_id")
        _owned_enum(self.outcome, StopOutcome, "outcome")
        if self.outcome is StopOutcome.REFUSED:
            _non_blank(self.error_code, "error_code")
        elif self.error_code is not None:
            raise CoreDTOError("only refused results carry an error_code")
