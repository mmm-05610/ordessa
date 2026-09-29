"""Frozen public DTOs for PE2 native observation facts.

These mirror the C4 native receipt protocol already enforced by the Harness
service (operation-bound ``NativeActivationReceipt`` plus an independent,
distinct readback verification).  They expose those facts for reading; they
are deliberately not a second activation protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .application import ApplicationTarget
from .errors import ContractError

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContractError(f"invalid {name}")


@dataclass(frozen=True)
class NativeOwnerReceiptFacts:
    """One persisted native-owner activation receipt (C4 receipt fields, read-only)."""

    operation_id: str
    target: ApplicationTarget
    manifest_digest: str
    native_session_identity: str
    applied_revision: str
    evidence_ref: str
    kind: Literal["native-owner-receipt"] = field(default="native-owner-receipt", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget):
            raise ContractError("receipt needs ApplicationTarget")
        if not _DIGEST.fullmatch(self.manifest_digest):
            raise ContractError("invalid receipt manifest digest")
        for name in ("operation_id", "native_session_identity", "applied_revision", "evidence_ref"):
            _nonempty(getattr(self, name), name)


@dataclass(frozen=True)
class NativeReadbackVerificationFacts:
    """The independent readback proof recorded for one operation."""

    operation_id: str
    readback_evidence_ref: str
    distinct_from_receipt: bool
    consistent_with_receipt: bool
    kind: Literal["native-readback-verification"] = field(default="native-readback-verification", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.operation_id, "operation_id")
        _nonempty(self.readback_evidence_ref, "readback_evidence_ref")
        if type(self.distinct_from_receipt) is not bool or type(self.consistent_with_receipt) is not bool:
            raise ContractError("readback verification flags must be bool")


@dataclass(frozen=True)
class NativeSessionIdentityFacts:
    """A native session identity confirmed by the Agent on one live channel."""

    harness_id: str
    connection_id: str
    execution_id: str
    ledger_session_id: str
    native_session_id: str
    kind: Literal["native-session-identity"] = field(default="native-session-identity", init=False)

    def __post_init__(self) -> None:
        for name in ("harness_id", "connection_id", "execution_id", "ledger_session_id",
                     "native_session_id"):
            _nonempty(getattr(self, name), name)


@dataclass(frozen=True)
class LaunchProvenanceFacts:
    """Declared launch reference for one registry harness (facts, not a launch)."""

    harness_type: str
    driver: str
    registry_version: str
    registry_digest: str
    launch_source: str
    launch_profile_id: str
    launch_modes: tuple[tuple[str, tuple[str, ...], str], ...]
    controlled: bool
    kind: Literal["launch-provenance"] = field(default="launch-provenance", init=False)

    def __post_init__(self) -> None:
        for name in ("harness_type", "driver", "registry_version", "registry_digest",
                     "launch_source", "launch_profile_id"):
            _nonempty(getattr(self, name), name)
        if type(self.controlled) is not bool:
            raise ContractError("launch provenance controlled flag must be bool")
        if self.launch_source not in {"upstream", "agentbox"}:
            raise ContractError("invalid launch provenance source")
        if (not isinstance(self.launch_modes, (tuple, list)) or not self.launch_modes
                or any(not isinstance(mode, tuple) or len(mode) != 3 or not mode[0] or not mode[1]
                       for mode in self.launch_modes)):
            raise ContractError("invalid launch provenance modes")
        object.__setattr__(self, "launch_modes",
                           tuple((name, tuple(argv), io) for name, argv, io in self.launch_modes))


@dataclass(frozen=True)
class NativeEvidence:
    """The native observation bundle for one operation.

    ``status`` is complete only when the receipt and a consistent, distinct
    readback verification are both persisted; partial means the effect was
    acknowledged but no readback proof exists yet; inconsistent means the two
    proofs contradict each other.  A missing operation or a reservation
    without any native evidence yields no bundle at all (the query returns
    None), never a synthesized one.
    """

    receipt: NativeOwnerReceiptFacts
    readback: NativeReadbackVerificationFacts | None
    status: Literal["complete", "partial", "inconsistent"]
    reason: str | None = None
    kind: Literal["native-evidence"] = field(default="native-evidence", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, NativeOwnerReceiptFacts):
            raise ContractError("native evidence needs a receipt")
        if self.readback is not None and not isinstance(self.readback, NativeReadbackVerificationFacts):
            raise ContractError("invalid native evidence readback")
        if self.status not in {"complete", "partial", "inconsistent"}:
            raise ContractError("invalid native evidence status")
        if self.status == "complete" and (self.readback is None
                or not self.readback.consistent_with_receipt
                or not self.readback.distinct_from_receipt):
            raise ContractError("complete evidence requires a distinct, consistent readback")
        if self.status in {"partial", "inconsistent"} and not self.reason:
            raise ContractError("incomplete native evidence requires a reason")
