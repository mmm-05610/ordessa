"""Structural host view of an injected database, without a product schema."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import ContextManager, Protocol


class DatabasePort(Protocol):
    path: Path

    def initialize(self) -> None: ...
    def read(self) -> ContextManager[sqlite3.Connection]: ...
    def transaction(self) -> ContextManager[sqlite3.Connection]: ...
