"""Canonical JSON bytes with explicit immutable acceptance profiles.

Profiles preserve historical wire acceptance without adding another encoder.
The default remains signed-int64, no-float JSON with a depth bound of 64.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from collections.abc import Mapping

MAX_INTEGER = 2**63 - 1

@dataclass(frozen=True)
class JSONProfile:
    max_depth: int
    max_integer: int | None
    allow_finite_floats: bool = False

STRICT_JSON_PROFILE = JSONProfile(64, MAX_INTEGER)
LIBRARY_JSON_PROFILE = JSONProfile(32, None, True)

class CanonicalJSONError(ValueError):
    def __init__(self, reason: str, *, stage: str = "validation", message: str = "noncanonical_json_value"):
        self.reason = reason
        self.stage = stage
        super().__init__(message)

def _validate(value: object, depth: int = 0, *, profile: JSONProfile = STRICT_JSON_PROFILE) -> None:
    if depth > profile.max_depth:
        raise CanonicalJSONError("depth", message="json_depth")
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        if profile.max_integer is None or -profile.max_integer - 1 <= value <= profile.max_integer:
            return
        raise CanonicalJSONError("type")
    if type(value) is float and profile.allow_finite_floats:
        if math.isfinite(value):
            return
        raise CanonicalJSONError("non_finite")
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate(item, depth + 1, profile=profile)
        return
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise CanonicalJSONError("key_type")
        for item in value.values():
            _validate(item, depth + 1, profile=profile)
        return
    raise CanonicalJSONError("type")

def canonical_text(value: object, *, profile: JSONProfile = STRICT_JSON_PROFILE) -> str:
    _validate(value, profile=profile)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        if profile == STRICT_JSON_PROFILE:
            raise
        raise CanonicalJSONError("encode", stage="encode", message="json_encode") from exc
    return encoded

def canonical_bytes(value: object, *, profile: JSONProfile = STRICT_JSON_PROFILE) -> bytes:
    return canonical_text(value, profile=profile).encode("utf-8")

def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result

def decode_json(raw: bytes | str) -> object:
    value = json.loads(raw, object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("json_nonfinite")))
    _validate(value)
    return value
