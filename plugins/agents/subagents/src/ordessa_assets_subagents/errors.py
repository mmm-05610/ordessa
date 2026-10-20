"""Domain refusals: one code per contracts.md §C5 entry, item-level reason.

`DomainError` never carries a rejected value: an oversized or credential-shaped
field is described by name and bound only, so a refusal cannot echo a secret
into a log, a response body or a repr.
"""
from __future__ import annotations

from typing import Any, Mapping

DEFINITION_INVALID = "DEFINITION_INVALID"
REVISION_STALE = "REVISION_STALE"
ASSIGNMENT_CONFLICT = "ASSIGNMENT_CONFLICT"
REFERENCE_UNRESOLVED = "REFERENCE_UNRESOLVED"
PERMISSION_EXCEEDS_CEILING = "PERMISSION_EXCEEDS_CEILING"
NATIVE_VERSION_UNKNOWN = "NATIVE_VERSION_UNKNOWN"
NATIVE_ENTRY_UNAVAILABLE = "NATIVE_ENTRY_UNAVAILABLE"
NATIVE_NAME_CONFLICT = "NATIVE_NAME_CONFLICT"
NATIVE_DISCOVERY_UNCONTROLLED = "NATIVE_DISCOVERY_UNCONTROLLED"
ADAPTER_MISSING = "ADAPTER_MISSING"
TARGET_CONFLICT = "TARGET_CONFLICT"
LOAD_UNVERIFIED = "LOAD_UNVERIFIED"
OPERATION_UNKNOWN = "OPERATION_UNKNOWN"
PROVIDER_BUSY = "PROVIDER_BUSY"

ERROR_CODES: frozenset[str] = frozenset({
    DEFINITION_INVALID,
    REVISION_STALE,
    ASSIGNMENT_CONFLICT,
    REFERENCE_UNRESOLVED,
    PERMISSION_EXCEEDS_CEILING,
    NATIVE_VERSION_UNKNOWN,
    NATIVE_ENTRY_UNAVAILABLE,
    NATIVE_NAME_CONFLICT,
    NATIVE_DISCOVERY_UNCONTROLLED,
    ADAPTER_MISSING,
    TARGET_CONFLICT,
    LOAD_UNVERIFIED,
    OPERATION_UNKNOWN,
    PROVIDER_BUSY,
})


class DomainError(RuntimeError):
    """A typed refusal raised before any native or storage side effect."""

    def __init__(
        self,
        code: str,
        *,
        item_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown C5 error code: {code!r}")
        self.code = code
        self.item_id = item_id
        self.detail = detail
        super().__init__(self._message())

    def _message(self) -> str:
        parts = [self.code]
        if self.item_id:
            parts.append(f"[{self.item_id}]")
        if self.detail:
            parts.append(self.detail)
        return " ".join(parts)

    def __repr__(self) -> str:
        return (f"DomainError(code={self.code!r}, item_id={self.item_id!r}, "
                f"detail={self.detail!r})")

    def as_mapping(self) -> dict[str, Any]:
        return {"code": self.code, "item_id": self.item_id, "detail": self.detail}


def refused(
    code: str,
    *,
    item_id: str | None = None,
    detail: str | None = None,
    offenders: Mapping[str, Any] | None = None,
) -> DomainError:
    """Build a refusal, naming the first offending item when none was given."""
    if item_id is None and offenders:
        item_id = str(next(iter(offenders)))
    return DomainError(code, item_id=item_id, detail=detail)
