"""Harness provider identity, owned by Execution Agents."""
from dataclasses import dataclass
import re

_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    display_name: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _COMPONENT_ID.fullmatch(self.id):
            raise ValueError(f"invalid provider id: {self.id!r}")
        for name, value in (("display_name", self.display_name), ("version", self.version)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider descriptor {name} is required")
