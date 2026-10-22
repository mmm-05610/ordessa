"""Provider-owned native codec port (dialect only, no state, no authority).

A codec encodes the caller's protocol-shaped message with the platform-assigned
correlation id and classifies inbound frames. It never persists, never decides
the completion of an Ordessa operation and never authorizes a write; the one
receiver in ``native_runtime`` owns those responsibilities.

Capabilities are advertised exactly: an unadvertised category is refused before
any write and never reported by ``agents.native.describe``.
"""
from __future__ import annotations

import json
from typing import Mapping, Protocol

from .native_envelope import CAPABILITY_NAMES, MAX_MESSAGE_BYTES

MAX_FRAME_BYTES = 1048576


class NativeCodecError(ValueError):
    """Bounded dialect refusal; diagnostics never include the frame contents."""


def _object(value, name):
    if type(value) is not dict:
        raise NativeCodecError(name + ' must be a JSON object')
    return value


def _text(value, name, limit=128):
    if (type(value) is not str or not value or value.strip() != value
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise NativeCodecError(name + ' is not a bounded identifier')
    return value


def _finite(value, depth=0):
    if depth > 32:
        raise NativeCodecError('native JSON depth exceeded')
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if value != value or value in (float('inf'), float('-inf')):
            raise NativeCodecError('native finite JSON required')
        return
    if type(value) is str:
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise NativeCodecError('native UTF-8 invalid') from None
        return
    if type(value) is list:
        for item in value:
            _finite(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise NativeCodecError('native JSON key invalid')
            _finite(key, depth + 1)
            _finite(item, depth + 1)
        return
    raise NativeCodecError('native finite JSON required')


def encode_frame(value):
    """Canonical single-LF frame bytes with a bounded size."""
    _finite(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise NativeCodecError('native frame encoding invalid') from None
    if len(raw) > MAX_FRAME_BYTES:
        raise NativeCodecError('native frame too large')
    return raw


def validate_codec(codec):
    """Structural admission for a provider codec (capabilities must be exact)."""
    protocol_id = getattr(codec, 'protocol_id', None)
    _text(protocol_id, 'protocol id')
    version = getattr(codec, 'protocol_version', None)
    if type(version) is not int or version < 1:
        raise NativeCodecError('protocol version invalid')
    capabilities = getattr(codec, 'capabilities', None)
    if not isinstance(capabilities, frozenset) or not capabilities <= CAPABILITY_NAMES:
        raise NativeCodecError('protocol capabilities invalid')
    if not all(callable(getattr(codec, name, None)) for name in
               ('encode_request', 'classify', 'terminal_state')):
        raise NativeCodecError('native codec is incomplete')
    if 'notify' in capabilities and not callable(getattr(codec, 'encode_notify', None)):
        raise NativeCodecError('notify is advertised without an encoder')
    if 'reverse_requests' in capabilities and not callable(getattr(codec, 'encode_reply', None)):
        raise NativeCodecError('reverse requests are advertised without an encoder')
    return codec


def _split_scalars(message):
    return _object(message, 'native message')


class NativeCodec(Protocol):
    protocol_id: str
    protocol_version: int
    capabilities: frozenset

    def encode_request(self, correlation_id: str, message: Mapping) -> bytes: ...

    def encode_notify(self, message: Mapping) -> bytes: ...

    def classify(self, value: Mapping) -> tuple[str, str | None, str | None]: ...

    def terminal_state(self, value: Mapping) -> str: ...

    def response_state(self, method: str, value: Mapping) -> str:
        """Return pending only when the acknowledgement precedes completion."""
        ...

    def notification_state(self, value: Mapping, *, session_id=None,
                           request=None, response=None) -> str | None:
        """Match a terminal to the original message and pending acknowledgement.

        The runtime calls this only for acknowledged pending operations. A
        protocol without sufficient correlation may match several operations;
        the runtime records unknown rather than choosing one arbitrarily.
        """
        ...

    def encode_reply(self, correlation_id: str, reply: Mapping) -> bytes: ...


__all__ = ['NativeCodecError', 'NativeCodec', 'validate_codec', 'encode_frame',
           'MAX_FRAME_BYTES']
