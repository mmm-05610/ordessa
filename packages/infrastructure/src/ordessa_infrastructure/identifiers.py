"""Stable opaque opaque identifiers and record timestamps."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

__all__ = ["now", "opaque_id", "RequestKey"]

_LOCAL_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_PRINCIPAL_SCOPE = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True)
class RequestKey:
    """Opaque idempotency partition and request key.

    These historical field names do not authenticate a principal, verify an
    Environment lifecycle or namespace owner, or grant permission. The
    ``comparison`` payload is caller-provided comparison data; this technical
    value does not interpret it as a binding, guarantee, or target. It carries
    no business references.
    """

    environment_namespace: str
    principal_scope: str
    request_id: str
    comparison: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.environment_namespace, str) or not _LOCAL_ID.match(self.environment_namespace):
            raise ValueError(
                f"RequestKey.environment_namespace must match { _LOCAL_ID.pattern!r}: "
                f"{self.environment_namespace!r}"
            )
        if not isinstance(self.principal_scope, str) or not _PRINCIPAL_SCOPE.match(self.principal_scope):
            raise ValueError("RequestKey.principal_scope is malformed")
        if not isinstance(self.request_id, str) or not _LOCAL_ID.match(self.request_id):
            raise ValueError(
                f"RequestKey.request_id must match { _LOCAL_ID.pattern!r}: {self.request_id!r}"
            )
