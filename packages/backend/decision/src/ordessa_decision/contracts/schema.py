"""Public schema generation and DTO decoding use only the standard library."""
from dataclasses import fields, is_dataclass, MISSING
from types import UnionType
from typing import get_type_hints, get_origin, get_args, Union, Any
from collections.abc import Mapping
from .codec import ContractError, decode, canonical, plain
from . import models

def construct(cls,value):
    if isinstance(value,cls): return value
    if not isinstance(value,Mapping): raise ContractError('dto_mapping')
    hints=get_type_hints(cls)
    known={f.name for f in fields(cls)}
    if set(value)-known: raise ContractError('dto_fields')
    def convert(t,v):
        if t is Any: return v
        origin=get_origin(t); args=get_args(t)
        if origin in (Union,UnionType):
            if v is None and type(None) in args: return None
            for item in args:
                if item is type(None): continue
                try: return convert(item,v)
                except (ContractError,TypeError,ValueError): pass
            raise ContractError('dto_union')
        if is_dataclass(t): return construct(t,v)
        if origin is tuple or t is tuple:
            if not isinstance(v,(list,tuple)): raise ContractError('dto_tuple')
            return tuple(convert(args[0],x) if args else x for x in v)
        if origin in (Mapping,dict) or t in (Mapping,dict):
            if not isinstance(v,Mapping): raise ContractError('dto_mapping')
            return v
        if t is float:
            if type(v) not in (float,int): raise ContractError('dto_number')
        elif t in (str,int,bool,type(None)) and type(v) is not t: raise ContractError('dto_scalar')
        return v
    try: return cls(**{k:convert(hints[k],v) for k,v in value.items()})
    except TypeError: raise ContractError('dto_fields') from None

def decode_request(data):
    return construct(models.DecisionRequest,decode(data))

def json_schema(cls):
    definitions={}
    def typ(t):
        origin=get_origin(t); args=get_args(t)
        if origin in (Union,UnionType): return {'anyOf':[typ(a) for a in args]}
        if is_dataclass(t):
            add(t); return {'$ref':'#/$defs/'+t.__name__}
        if origin is tuple or t is tuple: return {'type':'array','items':typ(args[0]) if args else {}}
        if origin in (Mapping,dict) or t in (Mapping,dict): return {'type':'object'}
        return {str:'string',int:'integer',float:'number',bool:'boolean',type(None):'null'}.get(t) and {'type':{str:'string',int:'integer',float:'number',bool:'boolean',type(None):'null'}[t]} or {}
    def add(t):
        if t.__name__ in definitions: return
        definitions[t.__name__]={}
        hints=get_type_hints(t)
        definitions[t.__name__]={'type':'object','additionalProperties':False,
            'properties':{f.name:typ(hints[f.name]) for f in fields(t)},
            'required':[f.name for f in fields(t) if f.default is MISSING and f.default_factory is MISSING]}
    add(cls)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$ref':'#/$defs/'+cls.__name__,'$defs':definitions}
