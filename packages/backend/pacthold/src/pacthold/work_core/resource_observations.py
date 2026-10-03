"""Minimal structured observations about frozen Execution inputs.

A ``ResourceObservation`` is a frozen value object, not a Core entity: it
records *who* claims *what* about one frozen ``(contract_id, Ref)`` input,
with no lifecycle of its own.  Core stores and validates these records; it
never compares claims, ranks observers, or derives a final truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .errors import InvalidResourceObservation
from .models import MAX_METADATA_VALUE_LENGTH, Ref, RefType

MAX_OBSERVER_ID_LENGTH = 64
MAX_DETAIL_LENGTH = MAX_METADATA_VALUE_LENGTH


class ResourceObservationKind(str, Enum):
    """What kind of claim is being made about the frozen input."""

    PROJECTED = "projected"
    READ_BACK = "read_back"
    CONSUMPTION_REPORTED = "consumption_reported"


class ResourceObservationResult(str, Enum):
    """The observer's comparison of the claim against the frozen input."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    UNVERIFIABLE = "unverifiable"


class ResourceObserverRole(str, Enum):
    """The seat the observer claims; a label, never a proof of trust."""

    EXECUTION_PROVIDER = "execution_provider"
    RESOURCE_PROVIDER = "resource_provider"
    HOST_OBSERVER = "host_observer"
    EXTERNAL_AUTHORITY = "external_authority"


class ResourceObservationCoverage(str, Enum):
    """How much of the observation surface the claim covers.

    COMPLETE/PARTIAL claims are only "complete/partial within the surface
    the observer states in ``detail``" — never a global completeness claim.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


def _validate_contract_id(contract_id: str) -> None:
    if not isinstance(contract_id, str) or not contract_id.strip():
        raise InvalidResourceObservation("contract_id is required")
    if len(contract_id) > MAX_METADATA_VALUE_LENGTH:
        raise InvalidResourceObservation("contract_id exceeds bounded length")
    # Reuse the dispatch-side contract id shape ("vendor.name@1").
    from .registry import _CONTRACT_ID

    if not _CONTRACT_ID.fullmatch(contract_id):
        raise InvalidResourceObservation(
            f"contract_id must look like vendor.name@1: {contract_id!r}"
        )


@dataclass(frozen=True)
class ResourceObservation:
    """One observer's typed claim about one frozen Execution input."""

    contract_id: str
    ref: Ref
    kind: ResourceObservationKind
    result: ResourceObservationResult
    observer_role: ResourceObserverRole
    observer_id: str
    observed_at: datetime
    coverage: ResourceObservationCoverage
    evidence_ref: Optional[Ref] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_contract_id(self.contract_id)
        if not isinstance(self.ref, Ref):
            raise InvalidResourceObservation("observation requires a Ref")
        if not isinstance(self.kind, ResourceObservationKind):
            raise InvalidResourceObservation("kind must be a ResourceObservationKind")
        if not isinstance(self.result, ResourceObservationResult):
            raise InvalidResourceObservation(
                "result must be a ResourceObservationResult"
            )
        if not isinstance(self.observer_role, ResourceObserverRole):
            raise InvalidResourceObservation(
                "observer_role must be a ResourceObserverRole"
            )
        if not isinstance(self.coverage, ResourceObservationCoverage):
            raise InvalidResourceObservation(
                "coverage must be a ResourceObservationCoverage"
            )
        if not isinstance(self.observer_id, str) or not self.observer_id.strip():
            raise InvalidResourceObservation("observer_id is required")
        if len(self.observer_id.strip()) > MAX_OBSERVER_ID_LENGTH:
            raise InvalidResourceObservation(
                f"observer_id exceeds {MAX_OBSERVER_ID_LENGTH} characters"
            )
        if not isinstance(self.observed_at, datetime):
            raise InvalidResourceObservation("observed_at must be a datetime")
        if self.evidence_ref is not None and (
            not isinstance(self.evidence_ref, Ref)
            or self.evidence_ref.type is not RefType.ARTIFACT
        ):
            raise InvalidResourceObservation("evidence_ref must be an ArtifactRef")
        if self.detail is not None:
            if not isinstance(self.detail, str):
                raise InvalidResourceObservation("detail must be text")
            if len(self.detail) > MAX_DETAIL_LENGTH:
                raise InvalidResourceObservation(
                    f"detail exceeds {MAX_DETAIL_LENGTH} characters"
                )
        # COMPLETE/PARTIAL coverage claims must state the observation surface
        # so "complete" can never be read as globally complete.
        if (
            self.coverage
            in (ResourceObservationCoverage.COMPLETE, ResourceObservationCoverage.PARTIAL)
            and not (self.detail or "").strip()
        ):
            raise InvalidResourceObservation(
                "COMPLETE/PARTIAL coverage requires detail describing the "
                "observation surface"
            )


__all__ = [
    "MAX_DETAIL_LENGTH",
    "MAX_OBSERVER_ID_LENGTH",
    "ResourceObservation",
    "ResourceObservationCoverage",
    "ResourceObservationKind",
    "ResourceObservationResult",
    "ResourceObserverRole",
]
