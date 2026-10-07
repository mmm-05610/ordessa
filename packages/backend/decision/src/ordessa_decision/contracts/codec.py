"""decision-json/1. Deliberately not RFC 8785. No remote references."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType
import hashlib
import json
import math

CODEC_VERSION = 'decision-json/1'
class ContractError(ValueError):
    code = 'contract_invalid'

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

def canonical(value, *, max_bytes=262144):
    data = json.dumps(plain(freeze(plain(value))), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
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

def digest(domain, value):
    if domain not in {'request','proposal','result','descriptor','runmanifest','question','answer','policy','feedback','event','flow'}:
        raise ContractError('digest_domain')
    return 'sha256:' + hashlib.sha256(('decision.'+domain+'\n'+CODEC_VERSION+'\n').encode()+canonical(value, max_bytes=2097152)).hexdigest()

def name(value):
    if type(value) is not str or not value or len(value)>256 or value.strip()!=value or any(ord(c)<32 for c in value):
        raise ContractError('identity')
    return value

def revision(value):
    if value is not None: name(value)
    return value
