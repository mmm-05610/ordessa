"""Input decode/check actions: bounded DTO construction and request decoding.

These are validation actions; the shared freeze/canonical value mechanism lives in
``definitions.values`` so there is no definitions -> validation reverse dependency.
"""
from dataclasses import fields, is_dataclass
from types import UnionType
from typing import get_type_hints, get_origin, get_args, Union, Any
from collections.abc import Mapping

from .errors import ContractError
from .values import decode
from . import models


def construct(cls, value):
    if isinstance(value, cls): return value
    if not isinstance(value, Mapping): raise ContractError('dto_mapping')
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    if set(value) - known: raise ContractError('dto_fields')
    def convert(t, v):
        if t is Any: return v
        origin = get_origin(t); args = get_args(t)
        if origin in (Union, UnionType):
            if v is None and type(None) in args: return None
            for item in args:
                if item is type(None): continue
                try: return convert(item, v)
                except (ContractError, TypeError, ValueError): pass
            raise ContractError('dto_union')
        if is_dataclass(t): return construct(t, v)
        if origin is tuple or t is tuple:
            if not isinstance(v, (list, tuple)): raise ContractError('dto_tuple')
            return tuple(convert(args[0], x) if args else x for x in v)
        if origin in (Mapping, dict) or t in (Mapping, dict):
            if not isinstance(v, Mapping): raise ContractError('dto_mapping')
            return v
        if t is float:
            if type(v) not in (float, int): raise ContractError('dto_number')
        elif t in (str, int, bool, type(None)) and type(v) is not t: raise ContractError('dto_scalar')
        return v
    try: return cls(**{k: convert(hints[k], v) for k, v in value.items()})
    except TypeError: raise ContractError('dto_fields') from None


def decode_request(data):
    return construct(models.DecisionRequest, decode(data))
