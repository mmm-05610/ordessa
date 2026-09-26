"""Content-addressed immutable object publication."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class ObjectRecord:
    digest: str
    size: int
    path: Path


class ObjectStore:
    def __init__(self, data_root: Path | str) -> None:
        self.root = Path(data_root).resolve() / "objects" / "sha256"

    def path_for(self, digest: str) -> Path:
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("invalid object digest")
        value = digest[7:]
        return self.root / value[:2] / value

    def publish(self, content: bytes) -> ObjectRecord:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_bytes()
            if hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
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
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != digest:
            raise IOError("immutable object digest mismatch")
        return content
