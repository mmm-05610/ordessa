"""Pure JSON-compatible value/depth validation; no parser or loading dependency."""
from typing import Any
from ..definitions.errors import MethodError, MethodFailure

def validate_json_value(value: Any, *, path: str, depth_limit: int = 64) -> None:
    def visit(item: Any, depth: int) -> None:
        if depth > depth_limit:
            raise MethodFailure(MethodError("STRUCTURE_TOO_DEEP", "resource exceeds the nesting limit", path=path))
        if item is None or type(item) in (str, bool, int):
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            if not all(type(key) is str for key in item):
                raise MethodFailure(MethodError("YAML_NON_STRING_KEY", "mapping keys must be strings", path=path))
            for child in item.values():
                visit(child, depth + 1)
            return
        # In particular reject floats, timestamps and binary values. Decimal
        # thresholds are represented as strings in the method contract.
        raise MethodFailure(MethodError("NON_JSON_VALUE", "method resources must use JSON-compatible values", path=path))

    visit(value, 0)
