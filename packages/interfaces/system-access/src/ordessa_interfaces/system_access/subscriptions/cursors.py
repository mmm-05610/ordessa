"""Authenticated opaque positions in the existing durable event order."""
from __future__ import annotations

import base64
import hashlib
import hmac
from ordessa_server_plugin_api.wire_errors import WireError

CURSOR_PREFIX = "w1"
OLDER_CURSOR_PREFIX = "w1o"


class CursorCodec:
    """Mint and read opaque session cursors.

    A cursor addresses one position in one session's durable event order. It is
    authenticated with the per-instance server secret so a cursor cannot be
    hand-forged into another session or an out-of-range position.
    """

    def __init__(self, secret: bytes) -> None:
        self._key = hashlib.sha256(secret).digest()

    def encode(self, session_id: str, seq: int) -> str:
        return self._encode(CURSOR_PREFIX, session_id, seq)

    def encode_older(self, session_id: str, raw_seq: int) -> str:
        """Mint a backward-history cursor that cannot resume the live feed."""
        return self._encode(OLDER_CURSOR_PREFIX, session_id, raw_seq)

    def _encode(self, prefix: str, session_id: str, seq: int) -> str:
        payload = f"{prefix}:{session_id}:{seq}".encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()[:12]
        return f"{payload.decode('utf-8')}:{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"

    def decode(self, cursor: str, *, expected_session: str | None = None) -> tuple[str, int]:
        return self._decode(cursor, CURSOR_PREFIX, expected_session=expected_session)

    def decode_older(self, cursor: str, *, expected_session: str | None = None) -> tuple[str, int]:
        return self._decode(cursor, OLDER_CURSOR_PREFIX, expected_session=expected_session)

    def _decode(
        self, cursor: str, expected_prefix: str, *, expected_session: str | None = None,
    ) -> tuple[str, int]:
        try:
            prefix, session_id, raw_seq, raw_signature = cursor.split(":", 3)
        except (AttributeError, ValueError) as exc:
            raise WireError("INVALID_REQUEST", "cursor is not a wire/1 cursor") from exc
        if prefix != expected_prefix:
            raise WireError("INVALID_REQUEST", "cursor generation is not supported")
        payload = f"{prefix}:{session_id}:{raw_seq}".encode("utf-8")
        padded = raw_signature + "=" * (-len(raw_signature) % 4)
        try:
            provided = base64.urlsafe_b64decode(padded)
        except (ValueError, TypeError) as exc:
            raise WireError("INVALID_REQUEST", "cursor signature is malformed") from exc
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()[:12]
        if not hmac.compare_digest(provided, expected):
            raise WireError("INVALID_REQUEST", "cursor signature did not verify")
        if expected_session is not None and session_id != expected_session:
            raise WireError("INVALID_REQUEST", "cursor belongs to a different session")
        try:
            seq = int(raw_seq)
        except ValueError as exc:
            raise WireError("INVALID_REQUEST", "cursor position is malformed") from exc
        if seq < 0:
            raise WireError("INVALID_REQUEST", "cursor position is malformed")
        return session_id, seq

