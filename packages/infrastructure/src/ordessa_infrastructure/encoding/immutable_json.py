"""Bounded canonical JSON and immutable snapshots of mapping values.

The accepted profile preserves finite floats, unrestricted integers, and the
historical depth/UTF-8 size limits of stored execution payloads. Serialization
uses the shared canonical encoder; this module adds container materialization
and immutable copies, without execution or persistence semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from types import MappingProxyType
from typing import Any

from .canonical_json import CanonicalJSONError, LIBRARY_JSON_PROFILE, canonical_text

MAX_JSON_BYTES = 262144


def _plain(value: Any, depth: int = 0) -> Any:
    if depth > LIBRARY_JSON_PROFILE.max_depth:
        raise CanonicalJSONError("depth", message="json_depth")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalJSONError("key_type", message="json_key_type")
        return {str(key): _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    return value


def safe_json(value: Mapping[str, Any], *, max_bytes: int = MAX_JSON_BYTES) -> str:
    """Encode a mapping with an explicit finite owner budget, defaulting to 256KiB."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise CanonicalJSONError("size_limit", message="json_size_limit")
    if not isinstance(value, Mapping):
        raise CanonicalJSONError("type", message="json_mapping_required")
    text = canonical_text(_plain(value), profile=LIBRARY_JSON_PROFILE)
    if len(text.encode("utf-8")) > max_bytes:
        raise CanonicalJSONError("size", message="json_size")
    return text


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def sealed_mapping(value: Mapping[str, Any], *, max_bytes: int = MAX_JSON_BYTES) -> Mapping[str, Any]:
    """Snapshot a mapping so nested mutation cannot alter retained data."""
    return _freeze(json.loads(safe_json(value, max_bytes=max_bytes)))
