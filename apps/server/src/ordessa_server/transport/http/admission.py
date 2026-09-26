"""Host transport admission dependencies shared by host and plugin routes.

Deliberately free of any application import: plugin route modules import this
module to declare the same admission discipline the host routes declare, so
the wall stays host-owned and single-sourced.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Header

from ordessa_server.errors import ServerError


def idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if value is None or not (1 <= len(value) <= 160):
        raise ServerError("IDEMPOTENCY_KEY_REQUIRED", "A bounded Idempotency-Key is required", status=400)
    return value
