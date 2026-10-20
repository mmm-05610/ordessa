"""Exact legacy Profile projections, distinct from modern Profile revisions.

This is a read-only migration/rendering contract. A HistoricalProfileView is
selected through the already admitted modern Profile owner; it does not grant
Profile access, Harness admission, or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentBoxProfileV1:
    """A fixed historical Agent-Box profile projection consumed by Harnesses."""

    contract_id: ClassVar[str] = "agent-box.profile@1"

    name: str
    agent_type: str
    digest: str
    revision: int = 1
    provider: str = "agent-box-profile"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("agent_type", self.agent_type),
            ("digest", self.digest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Agent-Box profile {field_name} is required")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Agent-Box profile revision must be positive")


@runtime_checkable
class HistoricalProfileViewPort(Protocol):
    """Read an exact imported historical view from one admitted Environment.

    Implementations check the current modern ref and the old ref/digest. The
    view itself grants neither provider admission nor launch authority.
    """

    def select_current(self, modern_ref: object, historical_ref: object) -> object: ...


__all__ = ["AgentBoxProfileV1", "HistoricalProfileViewPort"]
