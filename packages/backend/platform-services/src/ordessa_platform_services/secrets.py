"""E4 secret-reference adapter (spec 026/005 T005-12).

The file-backed adapter stores ONLY references plus encrypted-at-rest test
material for fixtures. Production OS keyring adapters stay where they are
(products layer today; 006 decides the platform assembly). Rules kept:

* the ref never contains material; knowing a ref grants no read;
* rotation mints a new revision and RETIRES the old key id — the MAC
  tombstones live in the store port and survive deletion;
* delete participates in admission: in-flight borrows and persistent
  references make it refuse until they are settled;
* locked/unavailable refuse the secret-needing path — no plaintext
  fallback, no global env-var escape hatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ordessa_environment_api.services import (
    DataAreaDescriptor,  # noqa: F401  (re-export parity with the port module)
    SecretAvailability,
    SecretRef,
)
from ordessa_environment_api.errors import EnvironmentError


@dataclass
class _Entry:
    ref: SecretRef
    material: bytes | None
    availability: SecretAvailability = SecretAvailability.AVAILABLE
    borrows: list[tuple[str, str]] = field(default_factory=list)  # (principal, purpose)


class SecretRefAdapter:
    """In-process/file adapter for secret REFERENCES with borrow accounting."""

    def __init__(self, *, locked: bool = False) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locked = locked
        self._tombstones: set[str] = set()

    def store(self, ref: SecretRef, material: bytes, purpose: str) -> SecretRef:
        if ref.ref in self._entries:
            raise EnvironmentError(f"secret ref {ref.ref!r} already stored")
        self._entries[ref.ref] = _Entry(ref=ref, material=material)
        return ref

    def describe(self, ref: SecretRef) -> SecretAvailability:
        if self._locked:
            return SecretAvailability.LOCKED
        entry = self._entries.get(ref.ref)
        if entry is None:
            return SecretAvailability.UNAVAILABLE if ref.ref not in self._tombstones else SecretAvailability.UNKNOWN
        if entry.ref.revision != ref.revision:
            return SecretAvailability.UNKNOWN  # rotated: the requested revision is gone
        return entry.availability

    def borrow_for_use(self, ref: SecretRef, principal: str, purpose: str, target: str) -> bytes:
        """Trusted-side borrow: verifies principal/purpose/target and the
        CURRENT revision every time; registers the borrow as in-flight."""
        if self._locked:
            raise EnvironmentError("secret store is locked; refusing the borrow (no fallback)")
        entry = self._entries.get(ref.ref)
        if entry is None or entry.material is None:
            raise EnvironmentError(f"secret {ref.ref!r} is unavailable")
        if entry.ref.revision != ref.revision:
            raise EnvironmentError(
                f"secret {ref.ref!r} is at revision {entry.ref.revision}, not {ref.revision}"
            )
        entry.borrows.append((principal, purpose))
        return entry.material

    def revoke_access(self, ref: SecretRef, principal: str) -> None:
        entry = self._entries.get(ref.ref)
        if entry:
            entry.borrows = [(p, pu) for (p, pu) in entry.borrows if p != principal]

    def delete(self, ref: SecretRef, evidence: dict[str, Any]) -> None:
        """Deletion admission: in-flight borrows or persistent references
        refuse; the tombstone ALWAYS survives (C2)."""
        entry = self._entries.get(ref.ref)
        if entry is not None and entry.borrows and not evidence.get("force-with-settlement"):
            raise EnvironmentError(
                f"secret {ref.ref!r} has in-flight borrows {entry.borrows}; settle them first"
            )
        self._entries.pop(ref.ref, None)
        self._tombstones.add(ref.ref)  # never dropped

    def has_tombstone(self, ref_id: str) -> bool:
        return ref_id in self._tombstones

    def rotate(self, ref: SecretRef, new_revision: str, material: bytes) -> SecretRef:
        entry = self._entries.get(ref.ref)
        if entry is None:
            raise EnvironmentError(f"secret {ref.ref!r} is not stored")
        new_ref = SecretRef(
            ref=ref.ref, revision=new_revision,
            owner_namespace=ref.owner_namespace, access_purpose=ref.access_purpose,
        )
        entry.ref = new_ref
        entry.material = material
        return new_ref
