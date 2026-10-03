"""Evidence sequencing, recovery bindings and unclassified deliveries (E2).

Three sequence domains are frozen and never conflated:

* ``source_revision`` — native/source order; comparable only within one
  trusted source incarnation;
* ``ingest_sequence`` — collection order at the environment edge;
* ``environment_knowledge_revision`` — the environment's accepted-knowledge
  version. A newer observer number is never native causality (V3-4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$")


@dataclass(frozen=True)
class SequenceTriple:
    source_revision: str | None
    ingest_sequence: int
    environment_knowledge_revision: int

    def __post_init__(self) -> None:
        if self.source_revision is not None and (
            not isinstance(self.source_revision, str) or not _TOKEN.match(self.source_revision)
        ):
            raise ValueError("SequenceTriple.source_revision is malformed")
        for name in ("ingest_sequence", "environment_knowledge_revision"):
            v = getattr(self, name)
            if type(v) is not int or v < 0:
                raise ValueError(f"SequenceTriple.{name} must be a non-negative int")


@dataclass(frozen=True)
class RecoveryBinding:
    """A new observer's read-evidence relation to an old native target (V3-8).

    PID/path/version equality proves nothing; the binding must name the
    native authority, owner identity, native session id and native
    generation, the evidence kind and the authorized principal.
    """

    environment: str
    binding_id: str
    native_authority: str
    native_owner_identity: str
    native_session_id: str
    native_generation: int
    evidence_kind: str
    principal: str
    scope: str = "read-evidence"
    continuity: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        for name in ("environment", "binding_id", "native_authority",
                     "native_owner_identity", "native_session_id", "evidence_kind",
                     "principal"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _TOKEN.match(v):
                raise ValueError(f"RecoveryBinding.{name} is malformed")
        if self.scope != "read-evidence":
            raise ValueError("RecoveryBinding.scope is frozen to read-evidence")
        if type(self.native_generation) is not int or self.native_generation < 0:
            raise ValueError("RecoveryBinding.native_generation must be a non-negative int")


@dataclass(frozen=True)
class UnclassifiedDeliveryFact:
    """A delivery whose ROLE is unknown — an obligation, not a plain log line.

    Bounded: ``budget_used``/``budget_max`` make the merge-to-scope-unknown
    behaviour explicit instead of silently dropping obligations (V3-7).
    """

    environment: str
    fact_id: str
    source_identity: str
    correlated_object: str | None
    ingest_revision: int
    safe_digest: str
    budget_used: int = 1
    budget_max: int = 1024

    def __post_init__(self) -> None:
        for name in ("environment", "fact_id", "source_identity"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _TOKEN.match(v):
                raise ValueError(f"UnclassifiedDeliveryFact.{name} is malformed")
        if self.correlated_object is not None and (
            not isinstance(self.correlated_object, str)
            or not _TOKEN.match(self.correlated_object)
        ):
            raise ValueError("UnclassifiedDeliveryFact.correlated_object is malformed")
        if not isinstance(self.safe_digest, str) or not re.match(
            r"^[0-9a-f]{16,128}$", self.safe_digest
        ):
            raise ValueError("UnclassifiedDeliveryFact.safe_digest is malformed")
        if (
            type(self.ingest_revision) is not int
            or self.ingest_revision < 0
            or type(self.budget_used) is not int
            or self.budget_used < 1
            or type(self.budget_max) is not int
            or self.budget_max < 1
            or self.budget_used > self.budget_max
        ):
            raise ValueError("UnclassifiedDeliveryFact budget fields are malformed")
