"""Record safety and canonical encoding, semantics preserved from legacy.

``reject_sensitive_keys`` mirrors ``ordessa_server.records`` (the historical
import is deliberately not used — this package must not reach host internals),
and ``canonical``/``digest`` keep the legacy record-encoding contract so the
effective-config digests stay comparable across layers.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .errors import ProfileError

_SENSITIVE = re.compile(
    r"(secret|token|api[_-]?key|password|private[_-]?key|authorization|cookie|credential_value)",
    re.I,
)

_MAX_RECORD_BYTES = 262_144


def reject_sensitive_keys(value: Any) -> None:
    """Refuse any mapping whose *key* looks like a secret carrier."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SENSITIVE.search(str(key)):
                raise ProfileError(
                    "SECRET_FIELD_FORBIDDEN",
                    "Configuration contains a forbidden secret field",
                    status=422,
                )
            reject_sensitive_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_sensitive_keys(child)


def canonical(value: Any) -> bytes:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > _MAX_RECORD_BYTES:
        raise ProfileError(
            "REQUEST_TOO_LARGE",
            "Request content exceeds the product record limit",
            status=422,
        )
    return encoded


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def json_dumps(value: Any) -> str:
    """Compact stable encoding used for every stored value column."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(raw: str) -> Any:
    return json.loads(raw)
