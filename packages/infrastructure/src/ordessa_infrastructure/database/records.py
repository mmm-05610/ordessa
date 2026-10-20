"""Business-neutral compare-and-swap record contracts for existing stores.

This module defines the shape and semantics of an optional technical store
capability. It opens no connection and owns no backend, transaction manager,
record lifecycle, authorization policy, or interpretation of stored values.
The existing store owner remains responsible for making request-result
idempotency and all supplied record writes atomic in its existing transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ..identifiers import RequestKey

DOMAIN_STORE_VERSION = "domain-records/1"


class DomainRevisionConflict(RuntimeError):
    """A generic record CAS did not match the currently stored revision."""

    code = "DOMAIN_REVISION_CONFLICT"


class DomainRequestConflict(RuntimeError):
    """The same scoped request key was already spent with another digest."""

    code = "DOMAIN_REQUEST_CONFLICT"


@dataclass(frozen=True)
class DomainWrite:
    """One opaque value replacement guarded by its expected record revision.

    ``expected_revision == 0`` means that the record must be absent;
    a positive value must match the revision on the existing record. ``value``
    is retained as supplied. This declaration neither interprets nor freezes
    its mapping.
    """

    namespace: str
    record_id: str
    expected_revision: int
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not self.namespace:
            raise ValueError("record namespace must be a non-empty string")
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("record id must be a non-empty string")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected revision must be a nonnegative integer; 0 means absent")
        if not isinstance(self.value, Mapping):
            raise TypeError("record value must be a Mapping")


@runtime_checkable
class DomainStorePort(Protocol):
    """Optional generic record capability on the caller's existing store.

    ``environment`` is an opaque persistence partition label. Implementations
    perform compare-and-swap for each ``DomainWrite`` (zero requires absence;
    positive revisions require an exact match) and commit those writes together
    with the request result in the same existing transaction. The request key
    and digest identify an idempotent request/result according to the store
    owner's contract. A spent key with another digest raises
    ``DomainRequestConflict`` from either read or commit; consumers may map it
    to their own identity conflict without depending on a backend's domain.
    This port grants no authority, performs no ACL checks,
    and assigns no business meaning to namespace, key, value, or result.
    """

    def read_domain(
        self, environment: str, namespace: str, record_id: str
    ) -> Mapping[str, Any] | None: ...

    def list_domain(
        self, environment: str, namespace: str
    ) -> tuple[Mapping[str, Any], ...]: ...

    def read_domain_result(
        self, request: RequestKey, digest: str
    ) -> Mapping[str, Any] | None: ...

    def commit_domain_change(
        self,
        request: RequestKey,
        digest: str,
        writes: tuple[DomainWrite, ...],
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


__all__ = [
    "DOMAIN_STORE_VERSION",
    "DomainRevisionConflict",
    "DomainRequestConflict",
    "DomainStorePort",
    "DomainWrite",
]
