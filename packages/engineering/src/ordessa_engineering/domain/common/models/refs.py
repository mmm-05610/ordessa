"""Generic stored-content identity and locator; business references have their own owners."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from .values import Digest, validate_id
from ..outcomes.diagnostics import ReferenceError

@dataclass(frozen=True)
class BlobRef:
    """Content identity plus an opaque locator, never a download permission."""
    digest: Digest
    byte_length: int
    media_type: str
    storage_object_id: str

    def __post_init__(self):
        if (type(self.digest) is not Digest or type(self.byte_length) is not int
                or not 0 <= self.byte_length <= 16 * 1024 * 1024
                or type(self.media_type) is not str or not self.media_type
                or len(self.media_type) > 256 or any(ord(c) < 32 for c in self.media_type)):
            raise ReferenceError("INVALID_BLOB_REF")
        validate_id(self.storage_object_id)
        if "://" in self.storage_object_id:
            raise ReferenceError("INVALID_BLOB_REF")

    def identity_projection(self):
        # Moving verified bytes changes their locator, not their identity.
        return {"digest": asdict(self.digest), "byte_length": self.byte_length,
                "media_type": self.media_type}
