"""Closed, JSON-safe schema values shared by adapter descriptions and intents."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, ClassVar, Literal, Mapping, TypeAlias, Union, cast

from .errors import ContractError

JsonScalar: TypeAlias = Union[None, bool, int, float, str]
JsonValue: TypeAlias = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]


def snapshot_json(value: object) -> str:
    """Store validated JSON as immutable text, away from caller-owned containers."""
    return json.dumps(validate_json(value), ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def read_snapshot(snapshot: str) -> JsonValue:
    """Give callers a fresh JSON value; changes cannot reach the stored DTO."""
    return cast(JsonValue, json.loads(snapshot))


class _JsonSnapshotField:
    """Keep a dataclass JSON field serializable without exposing stored mutability."""

    _snapshot_field: ClassVar[str]

    def _seal_json_field(self) -> None:
        name = object.__getattribute__(self, "_snapshot_field")
        value = object.__getattribute__(self, name)
        object.__setattr__(self, "_json_snapshot", snapshot_json(value))
        object.__setattr__(self, name, None)

    def __getattribute__(self, name: str) -> Any:
        if name == object.__getattribute__(self, "_snapshot_field"):
            try:
                snapshot = object.__getattribute__(self, "_json_snapshot")
            except AttributeError:
                pass
            else:
                return read_snapshot(snapshot)
        return object.__getattribute__(self, name)


def looks_secret_name(name: str) -> bool:
    """Reject common credential fields in ordinary JSON/field intents.

    This is a guard against accidental plaintext; adapters still must classify
    every secret-bearing field and use BindSecret at the service boundary.
    """
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    return compact in {"secret", "password", "token", "apikey", "privatekey", "credential", "credentials"} or compact.endswith(("secret", "password", "apikey", "accesstoken", "authtoken", "bearertoken", "privatekey"))


def validate_json(value: object, *, secret_free: bool = True) -> JsonValue:
    """Return a detached JSON value; reject arbitrary objects and secret-bearing keys."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        import math
        if math.isfinite(value):
            return value
        raise ContractError("non-finite number")
    if isinstance(value, (list, tuple)):
        return [validate_json(item, secret_free=secret_free) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("JSON object key must be a string")
            if secret_free and looks_secret_name(key):
                raise ContractError("secret value must use BindSecret")
            result[key] = validate_json(item, secret_free=secret_free)
        return result
    raise ContractError(f"not a JSON value: {type(value).__name__}")


@dataclass(frozen=True)
class ValueSchema:
    """Small closed JSON schema subset; adapters may implement richer business validation."""

    kind: Literal["null", "boolean", "integer", "number", "string", "array", "object"]
    nullable: bool = False
    enum: tuple[JsonScalar, ...] = ()
    properties: tuple[tuple[str, "ValueSchema"], ...] = ()
    required: tuple[str, ...] = ()
    items: "ValueSchema | None" = None
    additional_properties: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"null", "boolean", "integer", "number", "string", "array", "object"}:
            raise ContractError("unknown schema kind")
        if type(self.nullable) is not bool or type(self.additional_properties) is not bool:
            raise ContractError("invalid schema flags")
        if (not isinstance(self.enum, (tuple, list)) or not isinstance(self.properties, (tuple, list))
                or not isinstance(self.required, (tuple, list))):
            raise ContractError("invalid schema members")
        if any(not isinstance(pair, (tuple, list)) or len(pair) != 2
               or not isinstance(pair[0], str) or not pair[0]
               or not isinstance(pair[1], ValueSchema) for pair in self.properties):
            raise ContractError("invalid property schema")
        if any(not isinstance(name, str) or not name for name in self.required):
            raise ContractError("invalid required property")
        object.__setattr__(self, "enum", tuple(self.enum))
        object.__setattr__(self, "properties", tuple((name, schema) for name, schema in self.properties))
        object.__setattr__(self, "required", tuple(self.required))
        names = [name for name, _ in self.properties]
        if len(names) != len(set(names)) or any(not name for name in names):
            raise ContractError("duplicate or empty property")
        if any(not isinstance(schema, ValueSchema) for _, schema in self.properties):
            raise ContractError("property needs ValueSchema")
        if len(self.required) != len(set(self.required)):
            raise ContractError("duplicate required property")
        if not set(self.required) <= set(names):
            raise ContractError("required property has no schema")
        if self.kind != "object" and (self.properties or self.required or self.additional_properties):
            raise ContractError("properties require object schema")
        if self.kind != "array" and self.items is not None:
            raise ContractError("items require array schema")
        if self.kind == "array" and self.items is None:
            raise ContractError("array items schema required")
        if self.items is not None and not isinstance(self.items, ValueSchema):
            raise ContractError("array items need ValueSchema")
        if any(not isinstance(item, (type(None), bool, int, float, str)) for item in self.enum):
            raise ContractError("enum must contain JSON scalars")
        for item in self.enum:
            validate_json(item, secret_free=False)

    def validate(self, value: object) -> JsonValue:
        result = validate_json(value)
        if result is None and self.nullable:
            return result
        matches = {
            "null": lambda: result is None,
            "boolean": lambda: isinstance(result, bool),
            "integer": lambda: isinstance(result, int) and not isinstance(result, bool),
            "number": lambda: isinstance(result, (int, float)) and not isinstance(result, bool),
            "string": lambda: isinstance(result, str),
            "array": lambda: isinstance(result, list),
            "object": lambda: isinstance(result, dict),
        }
        if not matches[self.kind]():
            raise ContractError(f"expected {self.kind}")
        if self.enum and not any(type(result) is type(item) and result == item for item in self.enum):
            raise ContractError("value outside enum")
        if isinstance(result, list):
            assert self.items is not None
            return [self.items.validate(item) for item in result]
        if isinstance(result, dict):
            fields = dict(self.properties)
            if not set(self.required) <= result.keys():
                raise ContractError("missing required property")
            if not self.additional_properties and not result.keys() <= fields.keys():
                raise ContractError("unknown property")
            return {key: fields[key].validate(item) if key in fields else item for key, item in result.items()}
        return result


def closed_object(**fields: ValueSchema) -> ValueSchema:
    return ValueSchema("object", properties=tuple(fields.items()), required=tuple(fields))
