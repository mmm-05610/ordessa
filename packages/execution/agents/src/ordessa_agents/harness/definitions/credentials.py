"""Harness credential-locator binding contract.

CredentialRefV1 preserves the historical provider/native-locator wire shape.
It is not a secret value or Profile SecretRef. NativeCredentialRef remains the
Harness-owned locator received at the native boundary; providers explicitly
validate and project between those contracts where required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Mapping


@dataclass(frozen=True)
class CredentialRefV1:
    """Provider-neutral, locator-only credential binding contract."""

    contract_id: ClassVar[str] = "agent-box.credential@1"

    provider: str
    native_locator: str
    harness_scope: str
    revision: int = 1
    schema_version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("provider", self.provider), ("native_locator", self.native_locator),
                            ("harness_scope", self.harness_scope)):
            if not isinstance(value, str) or not value or len(value) > 256 or "\0" in value:
                raise ValueError(f"invalid credential {name}")
        if self.revision < 1 or self.schema_version != 1:
            raise ValueError("unsupported credential schema")
        if len(self.metadata) > 16 or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in self.metadata.items()):
            raise ValueError("invalid credential metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))


__all__ = ["CredentialRefV1"]
