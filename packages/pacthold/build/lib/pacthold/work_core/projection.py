"""Provider-neutral, material Execution lifecycle projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .errors import InvalidProjection


class Phase(str, Enum):
    ACTIVE = "active"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"


class Outcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class Freshness(str, Enum):
    OBSERVED = "observed"
    STALE = "stale"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class ExecutionProjection:
    """Current provider observation, never provider-native state."""

    phase: Phase
    outcome: Optional[Outcome]
    resumable_now: Optional[bool]
    freshness: Freshness
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.phase is Phase.TERMINAL and self.outcome is None:
            raise InvalidProjection("terminal projection requires an outcome")
        if self.phase is not Phase.TERMINAL and self.outcome is not None:
            raise InvalidProjection("only terminal projection may have an outcome")
        if self.phase is Phase.UNKNOWN and self.outcome is not None:
            raise InvalidProjection("unknown projection may not claim an outcome")

    @property
    def terminal(self) -> bool:
        return self.phase is Phase.TERMINAL
