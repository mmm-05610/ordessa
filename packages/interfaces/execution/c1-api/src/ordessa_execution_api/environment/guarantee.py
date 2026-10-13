"""Guarantee levels, protected fingerprints and input capture (C1/C2, V3-2, M06/D6).

Frozen rules (user-confirmed M06):

* ``raw`` — ordinary native interaction with a stable request id, no auto
  retry, observable receipts reported as observed. No restart-consistency
  claim.
* ``reliable`` — requires a protected complete-input fingerprint plus the
  capabilities the Harness declares; when any of them is missing the
  *reliable path is refused before dispatch* (typed
  ``GuaranteeUnavailableError``). Missing guarantees must NOT disable ordinary
  raw interaction and must NOT silently downgrade a reliable request to raw.

Request-key digest encoding (T002-04 freeze):
``REQUEST_KEY_MAC = HMAC-SHA256(canonical_json({
    key: RequestKey identity fields,
    binding: BindingSnapshot identity fields,
    guarantee: level,
    input: InputCapture.content_digest (sha256 of the immutable snapshot),
}), key = port-managed opaque key material identified by key_id)``
The MAC covers attachments/config/target via the immutable content digest —
never a path or a stat result. Key unavailability yields
``ComparisonUnavailableError``; a spent tombstone is never re-dispatched and
never auto-deleted by TTL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ALGO = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class GuaranteeLevel(Enum):
    RAW = "raw"
    RELIABLE = "reliable"

    @classmethod
    def from_wire(cls, value: str) -> "GuaranteeLevel":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"unknown guarantee level: {value!r}") from exc


@dataclass(frozen=True)
class FingerprintDescriptor:
    """How a request's complete input was fingerprinted (never the payload)."""

    algorithm: str
    key_id: str
    comparison_scope: str

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, str) or not _ALGO.match(self.algorithm):
            raise ValueError("FingerprintDescriptor.algorithm is malformed")
        _mac_key(self.key_id)
        if not isinstance(self.comparison_scope, str) or not _ALGO.match(
            self.comparison_scope.replace(":", "-").replace("_", "-")
        ) and ":" not in self.comparison_scope:
            raise ValueError("FingerprintDescriptor.comparison_scope is malformed")


def _mac_key(value: str) -> str:
    if not isinstance(value, str) or not re.match(r"^[a-z0-9][a-z0-9._:-]{0,127}$", value):
        raise ValueError("key id is malformed")
    return value


@dataclass(frozen=True)
class InputCapture:
    """The immutable content snapshot a reliable submission freezes.

    ``content_digest`` is the sha256 of the canonical encoding of the frozen
    text/config/attachment contents (the fingerprint input). ``handles`` are
    immutable content references; a bare file path or an open handle is NOT a
    valid capture (C2 内容冻结) and must not appear here.
    """

    content_digest: str
    attachment_digests: tuple[str, ...] = ()
    config_operation_ids: tuple[str, ...] = ()
    base_revision: str | None = None
    handles: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.content_digest, str) or not _DIGEST.match(self.content_digest):
            raise ValueError("InputCapture.content_digest must be a lowercase sha256 hex")
        for d in self.attachment_digests:
            if not isinstance(d, str) or not _DIGEST.match(d):
                raise ValueError("InputCapture.attachment_digests entries must be sha256 hex")
        for op in self.config_operation_ids:
            if not isinstance(op, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", op):
                raise ValueError("InputCapture.config_operation_ids entries are malformed")
        if self.base_revision is not None and not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.base_revision
        ):
            raise ValueError("InputCapture.base_revision is malformed")
