"""Shared configuration identity: all fields, scalar Unicode, safe integers.

Fractional/unsafe numbers are refused, never rounded or silently omitted.
Existing ASCII/string selector hashes retain their canonical bytes.
"""
import hashlib
import json
import math

_MAX_SAFE_INTEGER = (1 << 53) - 1


def _identity_value(value, active):
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        value.encode("utf-8")  # Refuse unpaired surrogates on the UTF-8 wire.
        return value
    if type(value) in (int, float):
        if (type(value) is float and (not math.isfinite(value) or not value.is_integer())
                or abs(value) > _MAX_SAFE_INTEGER):
            raise ValueError("Unsupported native configuration identity number: expected safe integer")
        return int(value)
    if type(value) not in (list, dict):
        raise ValueError("Unsupported native configuration identity value")
    if id(value) in active:
        raise ValueError("Cyclic native configuration identity")
    active.add(id(value))
    try:
        if type(value) is list:
            return [_identity_value(item, active) for item in value]
        if any(type(key) is not str for key in value):
            raise ValueError("Native configuration identity keys must be strings")
        # JS sorts UTF-16 code units, rather than Unicode scalar values.
        return {key: _identity_value(value[key], active)
                for key in sorted(value, key=lambda key: key.encode("utf-16-be"))}
    finally:
        active.remove(id(value))

def configuration_digest(options: list) -> str:
    if type(options) is not list:
        raise ValueError("Native configuration identity requires configOptions array")
    encoded = json.dumps(_identity_value(options, set()), ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

