"""Public JSON-schema declaration generation for the decision DTOs (stdlib only)."""
from dataclasses import fields, is_dataclass, MISSING
from types import UnionType
from typing import get_type_hints, get_origin, get_args, Union, Mapping

__all__ = ['json_schema']


def json_schema(cls):
    definitions = {}
    def typ(t):
        origin = get_origin(t); args = get_args(t)
        if origin in (Union, UnionType): return {'anyOf': [typ(a) for a in args]}
        if is_dataclass(t):
            add(t); return {'$ref': '#/$defs/' + t.__name__}
        if origin is tuple or t is tuple: return {'type': 'array', 'items': typ(args[0]) if args else {}}
        if origin in (Mapping, dict) or t in (Mapping, dict): return {'type': 'object'}
        return {str: 'string', int: 'integer', float: 'number', bool: 'boolean', type(None): 'null'}.get(t) and {'type': {str: 'string', int: 'integer', float: 'number', bool: 'boolean', type(None): 'null'}[t]} or {}
    def add(t):
        if t.__name__ in definitions: return
        definitions[t.__name__] = {}
        hints = get_type_hints(t)
        definitions[t.__name__] = {'type': 'object', 'additionalProperties': False,
            'properties': {f.name: typ(hints[f.name]) for f in fields(t)},
            'required': [f.name for f in fields(t) if f.default is MISSING and f.default_factory is MISSING]}
    add(cls)
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$ref': '#/$defs/' + cls.__name__, '$defs': definitions}
