"""Method identities and exact references shared across stages."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class MethodIdentity:
    method_id: str
    release_version: str
    schema_version: int



@dataclass(frozen=True)
class MethodRef:
    method_id: str
    release_version: str
    schema_version: int
    snapshot_digest: str



@dataclass(frozen=True)
class ReleasedIdentity:
    method_id: str
    release_version: str
    snapshot_digest: str



@dataclass(frozen=True)
class ResourceRef:
    resource_id: str
    sha256: str
    kind: str



@dataclass(frozen=True)
class BlobRef:
    digest: str
    byte_length: int
    media_type: str
    storage_object_id: str


from ordessa_infrastructure.encoding import canonical_bytes, sha256


def digest_bytes(raw: bytes) -> str:
    return sha256(raw).hex()


def method_digest(record_type: str, payload: object) -> str:
    if not record_type or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-/" for ch in record_type):
        raise ValueError("invalid_record_type")
    return sha256(f"ordessa/{record_type}/v1\n".encode("utf-8") + canonical_bytes(payload)).hex()
