"""Injected request replay records; transaction ownership stays with the caller.

The host implements this port over its existing journal. No database, schema,
clock, serializer or implementation is selected by this contract.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class IdempotencyRecordsPort(Protocol):
    """One injected journal bound to the same database as the business records.

    Matching (scope, key, request_digest) replays the original status/body;
    a different digest refuses with the existing IDEMPOTENCY_CONFLICT error.
    check/insert use the exact caller connection without opening or committing
    a transaction. The caller's business write and journal insert commit or
    roll back together. get/save retain the host's standalone read/write
    scopes; save returns the winning receipt under concurrent acceptance.
    """

    def check(self, conn: Any, scope: str, key: str,
              request_digest: str) -> Optional[tuple[int, dict[str, Any]]]: ...

    def insert(self, conn: Any, scope: str, key: str, request_digest: str,
               status: int, body: dict[str, Any]) -> None: ...

    def get(self, scope: str, key: str,
            request_digest: str) -> Optional[tuple[int, dict[str, Any]]]: ...

    def save(self, scope: str, key: str, request_digest: str, status: int,
             body: dict[str, Any]) -> tuple[int, dict[str, Any]]: ...
