"""Bounded immutable JSON values and omission marker for Profile intent."""
from __future__ import annotations

import math
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias, Union

from .validation import MAX_CONTENT_DEPTH, ProfileValidationError

# Objects and arrays are immutable mappings and tuples, never mutable input aliases.
JsonValue: TypeAlias = Union[None, bool, int, float, str,
                            Mapping[str, "JsonValue"], tuple["JsonValue", ...]]


class Omitted(Enum):
    FIELD = "omitted"


OMITTED = Omitted.FIELD


def freeze_json(value: object, depth: int = 0) -> JsonValue:
    if depth > MAX_CONTENT_DEPTH:
        raise ProfileValidationError("manifest nesting exceeds limit")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ProfileValidationError("JSON object keys must be strings")
        return MappingProxyType({key: freeze_json(item, depth + 1) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item, depth + 1) for item in value)
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ProfileValidationError("manifest must contain finite JSON values")


def json_data(value: JsonValue) -> object:
    """Return a detached JSON tree for validation, wire encoding and provider ports."""
    if isinstance(value, Mapping):
        return {key: json_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_data(item) for item in value]
    return value


def _object(value: object) -> Mapping[str, JsonValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise ProfileValidationError("structured reference/metadata must be an object")
    return frozen


