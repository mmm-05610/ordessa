"""Persistent resource references (E5) — declared relations, not a second bus.

A ``PersistentReference`` is a saved object-version's declared relation to a
resource version. It survives plugin retirement (published stays published),
is keyed by neutral stable resource keys (never a socket or an executable
ObjectRef generation), and grants no permission and no secret read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .targets import CanonicalFactTarget

_SELECTOR_OP = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ReferenceStatus(Enum):
    PREPARED = "prepared"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class RevisionSelector:
    """How a relation pins its target: exact, floor, or declared-none.

    The environment only compares selectors by contract; it never interprets
    providerId/modelId/skill semantics.
    """

    op: str  # exact|floor|any
    revision: str | None = None

    def __post_init__(self) -> None:
        if self.op not in {"exact", "floor", "any"}:
            raise ValueError(f"RevisionSelector.op {self.op!r} is not a frozen value")
        if self.op != "any":
            if not isinstance(self.revision, str) or not re.match(
                r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$", self.revision
            ):
                raise ValueError("RevisionSelector.revision is required unless op=any")
        elif self.revision is not None:
            raise ValueError("RevisionSelector.revision must be null when op=any")


@dataclass(frozen=True)
class PersistentReference:
    """One declared relation from a saved source version to a target version."""

    relation_id: str
    source_key: CanonicalFactTarget
    source_revision: str
    target_key: CanonicalFactTarget
    revision_selector: RevisionSelector
    declaring_owner_domain: str
    policy_contract_id: str
    policy_contract_version: int
    operation_id: str
    source_commit_evidence: str
    status: ReferenceStatus = ReferenceStatus.PREPARED
    coverage_epoch: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.relation_id, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", self.relation_id
        ):
            raise ValueError("PersistentReference.relation_id is malformed")
        for name in ("source_revision", "source_commit_evidence"):
            v = getattr(self, name)
            if not isinstance(v, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:+=-]{0,255}$", v):
                raise ValueError(f"PersistentReference.{name} is malformed")
        if not isinstance(self.policy_contract_id, str) or not re.match(
            r"^[a-z][a-z0-9.-]{0,95}$", self.policy_contract_id
        ):
            raise ValueError("PersistentReference.policy_contract_id is malformed")
        if type(self.policy_contract_version) is not int or self.policy_contract_version < 1:
            raise ValueError("PersistentReference.policy_contract_version must be >= 1")
        if not isinstance(self.operation_id, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", self.operation_id
        ):
            raise ValueError("PersistentReference.operation_id is malformed")
        if type(self.coverage_epoch) is not int or self.coverage_epoch < 0:
            raise ValueError("PersistentReference.coverage_epoch must be a non-negative int")


@dataclass(frozen=True)
class ChangeReservation:
    """Admission ticket a destructive target change must hold (E5 §变更准入).

    ``conflicting_relations`` lists the published relations the same gate
    refused; a change and a new relation to the same target can never both
    pass the same gate. The reservation survives UI close/TTL — only evidence
    resolves it.
    """

    reservation_id: str
    target_key: CanonicalFactTarget
    expected_revision: str
    change_kind: str  # archive|delete|rewrite (owner contract decides semantics)
    operation_id: str
    refused_relations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reservation_id, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", self.reservation_id
        ):
            raise ValueError("ChangeReservation.reservation_id is malformed")
        if self.change_kind not in {"archive", "delete", "rewrite"}:
            raise ValueError(f"ChangeReservation.change_kind {self.change_kind!r} is not frozen")
        if not isinstance(self.expected_revision, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$", self.expected_revision
        ):
            raise ValueError("ChangeReservation.expected_revision is malformed")
        if not isinstance(self.operation_id, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", self.operation_id
        ):
            raise ValueError("ChangeReservation.operation_id is malformed")
