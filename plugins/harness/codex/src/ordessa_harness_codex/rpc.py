"""Pure codex app-server JSON-RPC frame values; no session or runtime owner.

The protocol is pinned by ``codex app-server generate-json-schema``
(codex-cli 0.157.1): requests are ``{"jsonrpc":"2.0","id":…,"method":…,"params":…}``
and responses carry ``result`` or ``error`` for the same ``id``. This module only
encodes one bounded request frame; correlation and guarded I/O belong to the
caller.
"""
import json
import math

MAX_FRAME_BYTES = 1048576
MAX_DEPTH = 32


class CodexRpcFrameError(ValueError):
    """Bounded codec refusal; diagnostics never include the input contents."""


def _text(value, limit):
    if (type(value) is not str or not value or value.strip() != value or len(value) > limit
            or any(ord(char) < 32 for char in value)):
        raise CodexRpcFrameError('native identifier invalid')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise CodexRpcFrameError('native identifier invalid') from None
    return value


def _finite(value, depth=0):
    if depth > MAX_DEPTH:
        raise CodexRpcFrameError('native JSON depth exceeded')
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise CodexRpcFrameError('native UTF8 invalid') from None
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _finite(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise CodexRpcFrameError('native JSON key invalid')
            _finite(key, depth + 1)
            _finite(item, depth + 1)
        return
    raise CodexRpcFrameError('native finite JSON required')


def encode_request(request_id, method, params=None):
    """Encode one correlated request frame with exactly one trailing LF."""
    _text(request_id, 512)
    _text(method, 128)
    if params is None:
        params = {}
    if type(params) is not dict:
        raise CodexRpcFrameError('native request parameters invalid')
    value = {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}
    _finite(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CodexRpcFrameError('native request encoding invalid') from None
    if len(raw) > MAX_FRAME_BYTES:
        raise CodexRpcFrameError('native frame too large')
    return raw


__all__ = ['CodexRpcFrameError', 'MAX_FRAME_BYTES', 'encode_request']
