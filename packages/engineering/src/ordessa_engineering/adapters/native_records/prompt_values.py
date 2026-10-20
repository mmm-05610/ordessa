"""Neutral exact prompt validation shared by execution consumers; no owner imports."""
from collections.abc import Mapping
import json
import math
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ...application.contracts.errors import ApplicationError

_CALLBACK_KEYS = {'on_request', 'before_write', 'on_observation'}
_MAX_PROMPT_BYTES = 262144


def _plain(value, depth=0):
    if depth > 32:
        raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
    raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')


def _reject_callbacks(value):
    if isinstance(value, Mapping):
        if _CALLBACK_KEYS.intersection(value):
            raise ApplicationError('RECORDED_DISPATCH_CALLBACK_FORBIDDEN')
        for item in value.values():
            _reject_callbacks(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_callbacks(item)


def _decode_prompt(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON number')))
        if type(value) is not dict or canonical_bytes(value, profile=LIBRARY_JSON_PROFILE) != raw:
            raise ValueError('prompt JSON is not canonical')
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ApplicationError('RECORDED_DISPATCH_INPUT_NOT_CANONICAL') from exc


