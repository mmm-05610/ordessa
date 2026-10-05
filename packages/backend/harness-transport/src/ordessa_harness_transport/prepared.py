"""Frozen native JSONL before original capture/claim; no effect authority.

Two native RPC clients allocate request IDs before admission. This shared
framing utility keeps the exact UTF-8 frame, with client-local one-shot handles.
It has no durable truth, request retry, provider registry or native semantics.
"""
from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Mapping

from .channel import ChannelFailure, FramingError, MAX_FRAME_BYTES


class PreparedFrameRefused(ChannelFailure):
    def __init__(self, detail='prepared native frame unavailable or already consumed'):
        super().__init__('PREPARED_FRAME_REFUSED', detail)


def native_frame_bytes(payload, *, max_frame_bytes=MAX_FRAME_BYTES):
    """Same exact codec as ProcessChannel, including LF; freeze before effects."""
    if not isinstance(payload, Mapping):
        raise FramingError('native frame must be a JSON object')
    try:
        encoded = (json.dumps(dict(payload), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    except (ValueError, UnicodeError, TypeError):
        raise FramingError('native frame must be finite UTF-8 JSON') from None
    if len(encoded) - 1 > max_frame_bytes:
        raise FramingError('native frame exceeds byte limit')
    return encoded


class PreparedFrame:
    """Opaque client-local handle. Facts/bytes are capture input, not a grant."""
    __slots__ = ('_protocol', '_request_id', '_wire', '_digest')

    def __new__(cls, *args, **kwargs):
        raise TypeError('prepared frames are issued by the native client')

    def __setattr__(self, name, value):
        raise AttributeError('prepared native frame is immutable')

    @property
    def protocol(self): return self._protocol

    @property
    def request_id(self): return self._request_id

    @property
    def frame_bytes(self): return self._wire

    @property
    def frame_digest(self): return self._digest

    @property
    def payload(self): return json.loads(self._wire)

    def __reduce__(self):
        raise TypeError('prepared native handles cannot be serialized')

    def __copy__(self):
        clone = object.__new__(PreparedFrame)
        for name in self.__slots__: object.__setattr__(clone, name, getattr(self, name))
        return clone

    def __deepcopy__(self, memo): return self.__copy__()


class PreparedFramePool:
    """One native client's unconsumed frames; bounded and revoked on close."""
    def __init__(self, protocol, *, max_pending=1024):
        if not isinstance(protocol, str) or not protocol or len(protocol) > 256 or any(ord(c) < 32 for c in protocol):
            raise ValueError('native protocol identity required')
        if type(max_pending) is not int or max_pending < 1:
            raise ValueError('bounded prepared frame capacity required')
        self._protocol, self._max = protocol, max_pending
        self._frames, self._closed = {}, False
        self._lock = RLock()

    def prepare(self, payload, request_id):
        if type(request_id) not in (str, int) or isinstance(request_id, str) and not request_id:
            raise ValueError('native request ID required')
        wire = native_frame_bytes(payload)
        # Family encoding provides the actual id. This does not assign ids or
        # turn owner correlation into fields absent from the native protocol.
        if json.loads(wire).get('id') != request_id or type(json.loads(wire).get('id')) is not type(request_id):
            raise ValueError('frozen native frame request identity differs')
        with self._lock:
            if self._closed or len(self._frames) >= self._max:
                raise PreparedFrameRefused('prepared native frame capacity unavailable')
            frame = object.__new__(PreparedFrame)
            digest = 'sha256:' + hashlib.sha256(wire).hexdigest()
            for key, value in (('_protocol', self._protocol), ('_request_id', request_id), ('_wire', wire), ('_digest', digest)):
                object.__setattr__(frame, key, value)
            self._frames[id(frame)] = (frame, request_id, wire, digest)
            return frame

    def consume(self, frame):
        """Consume before any hook/write, returning the original immutable bytes.

        Hook failure spends the handle too. It never authorizes a new claim or
        another send. Core retains the original attempt and unknown facts.
        """
        with self._lock:
            entry = self._frames.get(id(frame))
            if (self._closed or type(frame) is not PreparedFrame or entry is None or entry[0] is not frame
                    or frame.protocol != self._protocol or frame.request_id != entry[1]
                    or type(frame.request_id) is not type(entry[1]) or frame.frame_bytes != entry[2]
                    or frame.frame_digest != entry[3]):
                raise PreparedFrameRefused()
            del self._frames[id(frame)]
            return entry[1], entry[2]

    def discard(self, frame):
        self.consume(frame)

    def close(self):
        with self._lock:
            self._closed = True
            self._frames.clear()
