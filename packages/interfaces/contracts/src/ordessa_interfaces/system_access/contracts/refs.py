"""Neutral immutable identity values. These values confer no authorization."""
from dataclasses import dataclass
import re


def identifier(value: str) -> None:
    if type(value) is not str or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_identifier")


def digest_hex(value: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid_digest")


@dataclass(frozen=True)
class Digest:
    algorithm: str
    hex: str

    def __post_init__(self):
        if self.algorithm != "sha256":
            raise ValueError("unsupported_digest_algorithm")
        digest_hex(self.hex)


@dataclass(frozen=True)
class Scope:
    realm_id: str
    project_id: str

    def __post_init__(self):
        identifier(self.realm_id)
        identifier(self.project_id)


@dataclass(frozen=True)
class ExactRef:
    namespace: str
    id: str
    revision: str
    digest: str

    def __post_init__(self):
        for value in (self.namespace, self.id, self.revision):
            identifier(value)
        digest_hex(self.digest)


@dataclass(frozen=True)
class OperationRef:
    authority_id: str
    operation_id: str

    def __post_init__(self):
        identifier(self.authority_id)
        identifier(self.operation_id)
