"""Immutable decision value codec (freeze/canonical) — decision-json/1."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType
import hashlib
import json
import math

from .errors import ContractError

__all__ = ['ContractError', 'CODEC_VERSION', 'plain', 'freeze', 'canonical', 'decode',
           'digest', 'name', 'revision']

CODEC_VERSION = 'decision-json/1'

def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value) if not f.name.startswith('_')}
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value

def freeze(value, *, depth=0, max_depth=32, max_string=65536):
    if depth > max_depth: raise ContractError('json_depth')
    if value is None or type(value) is bool: return value
    if type(value) is int: return value
    if type(value) is float:
        if not math.isfinite(value): raise ContractError('nonfinite')
        return value
    if type(value) is str:
        if len(value.encode('utf-8')) > max_string: raise ContractError('string_size')
        return value
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value): raise ContractError('json_key')
        return MappingProxyType({k: freeze(v, depth=depth+1, max_depth=max_depth, max_string=max_string) for k, v in value.items()})
    if type(value) in (tuple, list):
        return tuple(freeze(v, depth=depth+1, max_depth=max_depth, max_string=max_string) for v in value)
    raise ContractError('json_type')

# The codec budgets are explicit parameters so one DTO can widen them; the shared
# defaults stay 64KiB per string and 256KiB per canonical object.
def canonical(value, *, max_string=65536, max_bytes=262144):
    data = json.dumps(plain(freeze(plain(value), max_string=max_string)), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > max_bytes: raise ContractError('json_size')
    return data

def decode(data, *, max_bytes=262144):
    if len(data) > max_bytes: raise ContractError('json_size')
    def pairs(items):
        out = {}
        for k,v in items:
            if k in out: raise ContractError('duplicate_key')
            out[k] = v
        return out
    def bad(_): raise ContractError('nonfinite')
    try: return freeze(json.loads(data, object_pairs_hook=pairs, parse_constant=bad))
    except (ValueError, UnicodeError, RecursionError) as exc: raise ContractError('json_invalid') from None

# Digest keeps its original 2MiB envelope default; only the string budget is
# shared with canonical so a digest can bind the exact bytes of one widened DTO.
def digest(domain, value, *, max_string=65536, max_bytes=2097152):
    if domain not in {'request','proposal','result','descriptor','runmanifest','question','answer','policy','feedback','event','flow'}:
        raise ContractError('digest_domain')
    return 'sha256:' + hashlib.sha256(('decision.'+domain+'\n'+CODEC_VERSION+'\n').encode()+canonical(value, max_string=max_string, max_bytes=max_bytes)).hexdigest()

def name(value):
    if type(value) is not str or not value or len(value)>256 or value.strip()!=value or any(ord(c)<32 for c in value):
        raise ContractError('identity')
    return value

def revision(value):
    if value is not None: name(value)
    return value
