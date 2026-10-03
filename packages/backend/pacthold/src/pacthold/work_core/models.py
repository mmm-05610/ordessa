"""Small provider-neutral domain values for the production Work Core."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional

from .errors import InvalidRef
from .projection import ExecutionProjection

MAX_METADATA_ITEMS = 16
MAX_METADATA_KEY_LENGTH = 64
MAX_METADATA_VALUE_LENGTH = 256


class WorkLifecycle(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class RefType(str, Enum):
    SESSION = "SessionRef"
    WORKFLOW_INSTANCE = "WorkflowInstanceRef"
    RUN = "RunRef"
    WORKSPACE = "WorkspaceRef"
    ARTIFACT = "ArtifactRef"


def _bounded_metadata(value: Mapping[str, str]) -> dict[str, str]:
    result = dict(value)
    if len(result) > MAX_METADATA_ITEMS:
        raise InvalidRef(f"metadata has more than {MAX_METADATA_ITEMS} items")
    for key, item in result.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise InvalidRef("metadata must be a flat string-to-string map")
        if len(key) > MAX_METADATA_KEY_LENGTH or len(item) > MAX_METADATA_VALUE_LENGTH:
            raise InvalidRef("metadata item exceeds bounded size")
    return result


@dataclass(frozen=True)
class Ref:
    type: RefType
    provider: str
    native_id: str
    uri: Optional[str] = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider or not self.native_id:
            raise InvalidRef("provider and native_id are required")
        object.__setattr__(self, "metadata", _bounded_metadata(self.metadata))


@dataclass(frozen=True)
class Work:
    id: str
    objective: str
    lifecycle: WorkLifecycle
    created_at: datetime
    updated_at: datetime
    closure_reason: Optional[str] = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    version: int = 0

    def __post_init__(self) -> None:
        if not self.id or not self.objective:
            raise ValueError("work id and objective are required")
        object.__setattr__(self, "metadata", _bounded_metadata(self.metadata))


@dataclass(frozen=True)
class Execution:
    id: str
    work_id: str
    provider_id: str
    projection: ExecutionProjection
    created_at: datetime
    dispatched_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    provenance: Mapping[str, str] = field(default_factory=dict)
    version: int = 0

    def __post_init__(self) -> None:
        if not self.id or not self.work_id or not self.provider_id:
            raise ValueError("execution id, work_id and provider_id are required")
        object.__setattr__(self, "provenance", _bounded_metadata(self.provenance))
