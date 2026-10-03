"""Receipts and snapshots (E1) — immutable receipts vs current-fact projections.

The V2-3 split is frozen in the type shapes: an ``ActivityReceipt`` is the
answer that was issued (never overwritten) while ``CurrentFactView`` is the
environment's current knowledge with its own revision; every query returns
both plus conflicts/obligations so a replayed receipt can never masquerade as
the current truth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .guarantee import GuaranteeLevel
from .identity import ActivationRef, ObjectRef, RequestKey, UsageRef
from .sequences import SequenceTriple

_OUTCOME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class ActivationReceipt:
    """Result of activate(manifest, principal): one transaction, all-or-nothing."""

    activation: ActivationRef
    published_contribution_revision: str
    settlement_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.published_contribution_revision, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.published_contribution_revision
        ):
            raise ValueError("ActivationReceipt.published_contribution_revision is malformed")


@dataclass(frozen=True)
class CreationReceipt:
    """Result of instantiate: creation attempt first, Object/Usage handed over
    in one connected transaction (V3-1 — the startup obligation transfers in
    the SAME transaction or stays unresolved)."""

    activity: str
    objects: tuple[ObjectRef, ...]
    usages: tuple[UsageRef, ...]
    unknown_outputs_possible: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.activity, str) or not self.activity:
            raise ValueError("CreationReceipt.activity is required")


@dataclass(frozen=True)
class BindingSnapshot:
    """Fixed environment axis of a binding (V2-6).

    Fixed: environment, logical surface, activation/instance generation,
    transport contract, environment context revision, grant refs, requested
    guarantee. Native mutable axes (desired/observed/enforced revisions,
    dynamic catalog cursor, native incarnation) live in ``native_axis`` and
    are reported, never rewritten by the environment.
    """

    environment: str
    logical_surface: str
    provider_activation: ActivationRef
    transport_contract: str
    environment_context_revision: str
    grant_refs: tuple[str, ...] = ()
    guarantee: GuaranteeLevel = GuaranteeLevel.RAW
    binding_digest: str = ""
    native_axis: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.logical_surface, str) or not self.logical_surface:
            raise ValueError("BindingSnapshot.logical_surface is required")
        if not isinstance(self.transport_contract, str) or not self.transport_contract:
            raise ValueError("BindingSnapshot.transport_contract is required")
        if not isinstance(self.environment_context_revision, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.environment_context_revision
        ):
            raise ValueError("BindingSnapshot.environment_context_revision is malformed")


@dataclass(frozen=True)
class CurrentFactView:
    """Current knowledge projection with revision — never overwrites receipts."""

    outcome: str  # pending|running|unknown|concluded|disputed
    revision: int
    conflicts: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, str) or not _OUTCOME.match(self.outcome):
            raise ValueError("CurrentFactView.outcome is malformed")
        if self.outcome not in {"pending", "running", "unknown", "concluded", "disputed"}:
            raise ValueError(f"CurrentFactView.outcome {self.outcome!r} is not a frozen value")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("CurrentFactView.revision must be a non-negative int")


@dataclass(frozen=True)
class ActivityReceipt:
    """What was issued, when — immutable; pair with CurrentFactView on query."""

    request: RequestKey
    issued_revision: str
    delivery: str  # not_issued|claim_reserved|issue_possible|acknowledged|unknown
    safe_summary: Mapping[str, Any] = field(default_factory=dict, compare=True)
    sequences: SequenceTriple | None = None

    def __post_init__(self) -> None:
        if self.delivery not in {
            "not_issued", "claim_reserved", "issue_possible", "acknowledged", "unknown",
        }:
            raise ValueError(f"ActivityReceipt.delivery {self.delivery!r} is not a frozen value")
        if not isinstance(self.issued_revision, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.issued_revision
        ):
            raise ValueError("ActivityReceipt.issued_revision is malformed")


@dataclass(frozen=True)
class UsageRecord:
    """One usage relation: grantee and rights fixed; release only decrements."""

    usage: UsageRef
    rights: tuple[str, ...]
    state: str  # active|released|expired|revoked

    def __post_init__(self) -> None:
        if self.state not in {"active", "released", "expired", "revoked"}:
            raise ValueError(f"UsageRecord.state {self.state!r} is not a frozen value")


@dataclass(frozen=True)
class CutReceipt:
    """Result of drain: the admission cut plus the blockers that remain."""

    activation: ActivationRef
    admission_cut_revision: str
    blockers: tuple[str, ...] = ()
    closed_new_admission: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.admission_cut_revision, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.admission_cut_revision
        ):
            raise ValueError("CutReceipt.admission_cut_revision is malformed")
