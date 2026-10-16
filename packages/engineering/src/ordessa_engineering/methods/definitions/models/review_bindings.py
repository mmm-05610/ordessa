"""Neutral, immutable method-owned review binding declarations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .identity import ResourceRef
from .compiled import SemanticValue


@dataclass(frozen=True)
class ReviewTargetSource(SemanticValue):
    source: Literal["slot", "proposal_proposed_revisions", "submission_output_revisions"]
    slot: str | None
    document_types: tuple[str, ...]
    role: Literal["primary", "base", "proposed", "output", "support"]

    def __post_init__(self):
        super().__post_init__()
        if (self.source == "slot") != (self.slot is not None):
            raise ValueError("target source slot shape invalid")
        if not self.document_types or len(self.document_types) != len(set(self.document_types)):
            raise ValueError("target document types must be nonempty and unique")


@dataclass(frozen=True)
class ReviewMaterialSource(SemanticValue):
    name: str
    source: Literal[
        "slot", "targets", "method_content", "proposal_record", "implementation_intent",
        "source_captures", "claim_bindings", "package_record", "submission_record",
        "review_record", "acceptance_mapping",
    ]
    slot: str | None

    def __post_init__(self):
        super().__post_init__()
        slotless = {"targets", "method_content", "source_captures", "claim_bindings"}
        if ((self.source == "slot" and self.slot is None)
                or (self.source in slotless and self.slot is not None)):
            raise ValueError("material source slot shape invalid")


@dataclass(frozen=True)
class ReviewGroupMember(SemanticValue):
    member_id: str
    request_node: str
    plan_slot: str
    standard_ref: ResourceRef
    response_wait: str
    record_node: str
    advance_waits: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewBindingSpec(SemanticValue):
    contract: Literal["ordessa.method-review-binding/1"]
    anchor_node: str
    group_id: str
    member_id: str


@dataclass(frozen=True)
class ReviewGroupSpec(SemanticValue):
    contract: Literal["ordessa.method-review-group/1"]
    anchor_node: str
    group_id: str
    subject_slot: str
    target_sources: tuple[ReviewTargetSource, ...]
    material_sources: tuple[ReviewMaterialSource, ...]
    members: tuple[ReviewGroupMember, ...]
    gate_wait: str
    required_members: Literal["all_declared"]
    empty_members: Literal["error"]

    def __post_init__(self):
        super().__post_init__()
        if not self.members:
            raise ValueError("review group must declare members")
        if len({member.member_id for member in self.members}) != len(self.members):
            raise ValueError("review member ids must be unique")
        if len({member.request_node for member in self.members}) != len(self.members):
            raise ValueError("review request nodes must be unique")
        if len({member.standard_ref for member in self.members}) != len(self.members):
            raise ValueError("review standards must be unique in a group")
        if any(len(member.advance_waits) != len(set(member.advance_waits)) for member in self.members):
            raise ValueError("member advance waits must be unique")
        if not self.target_sources:
            raise ValueError("review group must declare target sources")
        if len(set(self.target_sources)) != len(self.target_sources):
            raise ValueError("review target sources must be unique")
        if len({item.name for item in self.material_sources}) != len(self.material_sources):
            raise ValueError("review material names must be unique")
