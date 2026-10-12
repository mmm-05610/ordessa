"""Neutral process/framing primitives.

Pure technical line framing and the typed frame-failure contract. No Agent,
provider, lease, writer-admission, receipt or instance semantics live here.
Business owners keep leases, writer admission, receipts and instance state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

MAX_FRAME_BYTES = 8 * 1024 * 1024


class ChannelFailure(Exception):
    """Typed transport failure. Callers must not blanket-retry these."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class FramingError(ChannelFailure):
    """Frame stream violated the framing contract (G5)."""

    def __init__(self, detail: str):
        super().__init__("FRAMING_ERROR", detail)


@dataclass(frozen=True)
class Message:
    """One decoded protocol message. ``raw`` is preserved verbatim (G4)."""

    raw: Mapping[str, Any]

    @property
    def kind(self) -> str:
        if "method" in self.raw and "id" in self.raw:
            return "request"
        if "method" in self.raw:
            return "notification"
        return "response"

    @property
    def method(self) -> str | None:
        value = self.raw.get("method")
        return value if isinstance(value, str) else None

    @property
    def id(self) -> Any:
        return self.raw.get("id")


class FrameReader:
    """Byte-safe line framing for protocol streams (G5)."""

    def __init__(self, *, max_frame_bytes: int = MAX_FRAME_BYTES):
        self._max = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """Consume bytes, return every complete frame decoded so far.

        Raises FramingError on oversize frames, invalid UTF-8 or a truncated
        final frame at EOF (via :meth:`close`).
        """
        self._buffer += data
        frames: list[str] = []
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                if len(self._buffer) > self._max:
                    raise FramingError(f"frame exceeded {self._max} bytes")
                break
            if index > self._max:
                raise FramingError(f"frame exceeded {self._max} bytes")
            chunk = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            frames.append(self._decode(chunk.rstrip(b"\r")))
        return frames

    def close(self) -> None:
        """EOF. Any undecoded remainder is a truncated frame (G5 counter-example:
        silently accepting a half frame would corrupt the message boundary)."""
        if self._buffer:
            raise FramingError("truncated frame at EOF")

    def _decode(self, chunk: bytes) -> str:
        try:
            # Each LF-delimited frame must contain complete UTF-8. Chunk
            # boundaries are buffered above; frame boundaries cannot borrow
            # continuation bytes from another native message.
            return chunk.decode('utf-8',errors='strict')
        except UnicodeDecodeError as exc:
            raise FramingError(f"invalid UTF-8 in frame: {exc.reason}") from exc


__all__ = ["MAX_FRAME_BYTES", "ChannelFailure", "FramingError", "Message", "FrameReader"]
