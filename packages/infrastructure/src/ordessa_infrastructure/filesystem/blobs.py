"""Content-addressed immutable object publication."""
from __future__ import annotations

from dataclasses import dataclass
from ..encoding.digests import sha256
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class ObjectRecord:
    digest: str
    size: int
    path: Path


class ObjectStore:
    """Content-addressed bytes at an explicit root; no product layout.

    The two-character SHA256 shard, digest and ObjectRecord format, corruption
    errors and file fsync/replace sequence retain the original mechanism. This
    is not the Engineering BlobStore authority or a record-format validator.
    It does not add a directory-fsync or no-clobber guarantee. Temporary cleanup
    retains the original path-based behavior and requires trusted namespace
    control; it is not asserted race-free against arbitrary same-UID mutation.
    """

    def __init__(self, storage_root: Path | str) -> None:
        self.root = Path(storage_root).resolve()

    def path_for(self, digest: str) -> Path:
        if (not isinstance(digest, str) or not digest.startswith("sha256:")
                or len(digest) != 71
                or any(character not in "0123456789abcdef" for character in digest[7:])):
            raise ValueError("invalid object digest")
        value = digest[7:]
        return self.root / value[:2] / value

    def publish(self, content: bytes) -> ObjectRecord:
        digest = "sha256:" + sha256(content).hex()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_bytes()
            if sha256(existing) != sha256(content):
                raise IOError("existing immutable object failed digest verification")
            return ObjectRecord(digest, len(content), target)
        fd, temporary = tempfile.mkstemp(prefix="publish-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            if target.read_bytes() != content:
                raise IOError("published immutable object failed verification")
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return ObjectRecord(digest, len(content), target)

    def read(self, digest: str) -> bytes:
        content = self.path_for(digest).read_bytes()
        actual = "sha256:" + sha256(content).hex()
        if actual != digest:
            raise IOError("immutable object digest mismatch")
        return content

__all__ = ["ObjectRecord", "ObjectStore"]
