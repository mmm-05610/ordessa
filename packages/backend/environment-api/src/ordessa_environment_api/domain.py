"""Optional atomic domain-record capability of the existing StorePort.

This additive face leaves oe-contract/1 and RequestKey identity unchanged.
It performs data-only changes: no external callback, dispatch or retry loop.
The request result and all CAS writes commit together in the same store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .identity import RequestKey
from .errors import IdentityMismatchError

DOMAIN_STORE_VERSION = "domain-records/1"


class DomainRevisionConflict(IdentityMismatchError):
    code = "DOMAIN_REVISION_CONFLICT"


@dataclass(frozen=True)
class DomainWrite:
    namespace: str
    record_id: str
    expected_revision: int
    value: Mapping[str, Any]

    def __post_init__(self):
        if not self.namespace or not self.record_id:
            raise ValueError("domain namespace and record id are required")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected revision must be a nonnegative integer; 0 means absent")


@runtime_checkable
class DomainStorePort(Protocol):
    """Optional face, implemented on the same instance as StorePort.

    Every read is scoped by environment. commit_domain_change uses the exact
    existing RequestKey, comparing kind/target/CAS/content via the digest.
    A spent uncertain/legacy request cannot acquire a second data write.
    """

    def read_domain(self, environment: str, namespace: str,
                    record_id: str) -> Mapping[str, Any] | None: ...

    def list_domain(self, environment: str,
                    namespace: str) -> tuple[Mapping[str, Any], ...]: ...

    def read_domain_result(self, request: RequestKey,
                           digest: str) -> Mapping[str, Any] | None: ...

    def commit_domain_change(self, request: RequestKey, digest: str,
                             writes: tuple[DomainWrite, ...],
                             result: Mapping[str, Any]) -> Mapping[str, Any]: ...
