"""Typed error surface of the Profile plugin family.

Stable string codes are the contract (specs/001-profile/contracts/core-api.md);
no host error class is imported or subclassed.
"""
from __future__ import annotations

from typing import Any


class ProfileError(Exception):
    """One domain refusal with a stable code, message and HTTP-ish status."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        # Optional item-level evidence, always non-secret:
        self.blockers: list[dict[str, Any]] | None = None
        self.conflicts: list[dict[str, Any]] | None = None
        self.item: str | None = None
        self.current: dict[str, Any] | None = None

    def with_blockers(self, blockers: list[dict[str, Any]]) -> "ProfileError":
        self.blockers = blockers
        return self

    def with_conflicts(self, conflicts: list[dict[str, Any]]) -> "ProfileError":
        self.conflicts = conflicts
        return self

    def with_item(self, item: str) -> "ProfileError":
        self.item = item
        return self

    def with_current(self, current: dict[str, Any]) -> "ProfileError":
        self.current = current
        return self
