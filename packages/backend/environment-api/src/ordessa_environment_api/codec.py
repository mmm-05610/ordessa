"""Canonical wire codec — the cross-language identity contract.

Rules (frozen; the TypeScript mirror in
``packages/desktop-platform/contracts/foundation/src/open-environment/codec.ts``
must produce byte-identical output):

1. Payloads are JSON objects; keys are sorted by UTF-16 code unit (Python's
   ``sorted()`` over ``str`` and JS ``Object.keys(...).sort()`` agree on the
   BMP subset these DTOs use — ids are restricted to ASCII by validation).
2. No insignificant whitespace: separators ``{"," : ":"}``, ``ensure_ascii``
   false, UTF-8 bytes.
3. Tuples/arrays encode as JSON arrays; mappings as objects; ``None`` as
   ``null``; enums as their value strings.
4. Every envelope carries ``contractVersion`` and ``kind``; an unknown
   ``kind`` or an unknown payload key is a decode error — extra fields are
   rejected, not ignored (a silent field drop would mint a new writer of the
   same fact).
5. Construction order never leaks into the wire form: two equal values built
   with different field orders encode identically.
"""
from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from . import CONTRACT_VERSION

__all__ = ["canonical_json", "encode_envelope", "decode_envelope", "CodecError"]


class CodecError(ValueError):
    code = "CODEC_ERROR"


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if is_dataclass(value):
        out: dict[str, Any] = {}
        for f in fields(value):
            out[f.name] = _plain(getattr(value, f.name))
        return out
    raise CodecError(f"cannot canonically encode {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Canonical encoding — deterministic across construction order."""
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def encode_envelope(kind: str, payload: Any) -> str:
    if not isinstance(kind, str) or not kind:
        raise CodecError("envelope kind is required")
    envelope = {"contractVersion": CONTRACT_VERSION, "kind": kind, "payload": _plain(payload)}
    return canonical_json(envelope)


def decode_envelope(
    text: str,
    expected_kind: str | None = None,
    expected_version: str = CONTRACT_VERSION,
) -> tuple[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CodecError(f"not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CodecError("envelope must be an object")
    keyset = set(value)
    if keyset != {"contractVersion", "kind", "payload"}:
        raise CodecError(f"envelope keys must be exactly the frozen set, got {sorted(keyset)}")
    if value["contractVersion"] != expected_version:
        raise CodecError(
            f"contract version {value['contractVersion']!r} != expected {expected_version!r}"
        )
    kind = value["kind"]
    if not isinstance(kind, str) or not kind:
        raise CodecError("envelope kind must be a non-empty string")
    if expected_kind is not None and kind != expected_kind:
        raise CodecError(f"kind {kind!r} != expected {expected_kind!r}")
    return kind, value["payload"]
