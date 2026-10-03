"""Canonical product-record encoding shared by every domain that stores one.

Moved out of `ordessa_server.records` by T014-S2c: three plugins
(`server-compat`, `workspace`, `harness`) encode and digest records with these
helpers, and importing them from the host was a rule-3 breach. They are
genuinely shared wire/storage shape, not business rules, so they belong to the
contract package the host *also* imports (the host re-exports them for its own
neutral use cases) — never to one sibling plugin, which would only move the
breach.

The frozen strings are the contract: a record that is already stored was
digested by this exact encoding, so `canonical`'s JSON settings and the
`sha256:` prefix are byte-pinned by
`apps/server/tests/platform/test_platform_record_encoding.py`-era gates. Do not
"tidy" them.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .internal_errors import ServerError


_SENSITIVE = re.compile(r"(secret|token|api[_-]?key|password|private[_-]?key|authorization|cookie|credential_value)", re.I)

#: The product-record ceiling `canonical` refuses above; part of the frozen
#: refusal (`REQUEST_TOO_LARGE`), not a tunable.
MAX_CANONICAL_BYTES = 262_144


def canonical(value: Any) -> bytes:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ServerError("REQUEST_TOO_LARGE", "Request content exceeds the product record limit", status=422)
    return encoded


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def reject_sensitive_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SENSITIVE.search(str(key)):
                raise ServerError("SECRET_FIELD_FORBIDDEN", "Configuration contains a forbidden secret field", status=422)
            reject_sensitive_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_sensitive_keys(child)
