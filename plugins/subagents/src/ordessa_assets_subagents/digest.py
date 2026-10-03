"""Canonical digests over revision content (data-model.md, gate G04).

`sha256:<64 lowercase hex>`, taken over the canonical JSON of the revision's
*content* only — body, declarations and source — so identity fields
(`definition_id`, `revision`) never change a digest: the same content always
yields the same digest and one changed byte always yields a different one.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .dto import DefinitionRevision

DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_PREFIX = "sha256:"

#: Identity fields stay out of the content digest on purpose.
_NON_CONTENT_FIELDS = ("definition_id", "revision", "content_digest")


def canonical_json(payload: Any) -> str:
    return json.dumps(
        _plain(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _plain(value: Any) -> Any:
    from dataclasses import fields, is_dataclass

    if isinstance(value, bool):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, entry in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical payloads need string keys")
            out[key] = _plain(entry)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(entry) for entry in value]
    if isinstance(value, (str, int, float)) or value is None:
        return value
    raise TypeError(f"not canonicalisable: {type(value).__name__}")


def canonical_digest(payload: Any) -> str:
    return _PREFIX + hashlib.sha256(
        canonical_json(payload).encode("utf-8", errors="strict")
    ).hexdigest()


def bytes_digest(data: bytes) -> str:
    return _PREFIX + hashlib.sha256(data).hexdigest()


def revision_payload(revision: DefinitionRevision) -> dict[str, Any]:
    from dataclasses import fields, is_dataclass

    payload: dict[str, Any] = {}
    for f in fields(revision):
        if f.name in _NON_CONTENT_FIELDS:
            continue
        payload[f.name] = _plain(getattr(revision, f.name))
    return payload


def revision_digest(revision: DefinitionRevision) -> str:
    return canonical_digest(revision_payload(revision))


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_RE.match(value) is not None
