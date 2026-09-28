"""Provider-neutral, locator-only credential binding contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Mapping


@dataclass(frozen=True)
class CredentialRefV1:
    """The only credential value allowed to cross the Core binding boundary."""

    contract_id: ClassVar[str] = "agent-box.credential@1"
    provider: str
    native_locator: str
    harness_scope: str
    revision: int = 1
    schema_version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("provider", self.provider), ("native_locator", self.native_locator), ("harness_scope", self.harness_scope)):
            if not isinstance(value, str) or not value or len(value) > 256 or "\0" in value:
                raise ValueError(f"invalid credential {name}")
        if self.revision < 1 or self.schema_version != 1:
            raise ValueError("unsupported credential schema")
        if len(self.metadata) > 16 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.metadata.items()):
            raise ValueError("invalid credential metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))
