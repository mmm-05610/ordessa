"""Explicit bounded method source reader contract."""
from typing import Protocol
from ..models.sources import MethodSource

class ResourceReader(Protocol):
    def read(self, source: MethodSource, relative_path: str, max_bytes: int) -> bytes: ...


