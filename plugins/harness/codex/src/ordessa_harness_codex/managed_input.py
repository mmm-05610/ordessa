"""Historical Codex capture codec; execution uses formal Unit captured inputs.

The native-provider managed-input coordinator is retired. Serialized capture
identifiers and loss checks remain readable; this module dispatches nothing.
"""
from dataclasses import dataclass
from typing import Mapping, Protocol
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import safe_json
from ordessa_units.channels.reservations import CapturedInputEvidence, CapturedInputRef

TEXT_CAPTURE_VERSION = "managed-codex-text/1"

@dataclass(frozen=True)
class ManagedTextCapture:
    """The capture owner's text-only canonical envelope and loss checks."""
    evidence: CapturedInputEvidence
    envelope: Mapping
    metadata: Mapping

    def canonical_bytes(self) -> bytes:
        if not isinstance(self.evidence, CapturedInputEvidence):
            raise GuaranteeUnavailableError("original captured-input metadata is unavailable")
        if (not isinstance(self.envelope, Mapping)
                or set(self.envelope) != {"schemaVersion", "text"}
                or self.envelope.get("schemaVersion") != TEXT_CAPTURE_VERSION
                or type(self.envelope.get("text")) is not str):
            raise GuaranteeUnavailableError("only the canonical managed Codex text envelope is supported")
        if (not isinstance(self.metadata, Mapping)
                or set(self.metadata) != {"attachmentDigests", "configOperationIds", "handles", "baseRevision"}
                or self.metadata["attachmentDigests"] not in ((), [])
                or self.metadata["configOperationIds"] not in ((), [])
                or self.metadata["handles"] not in ((), [])
                or self.metadata["baseRevision"] is not None):
            raise GuaranteeUnavailableError("capture contains unsupported attachments or configuration")
        try:
            body = safe_json(self.envelope).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise GuaranteeUnavailableError("capture text is not canonical finite UTF-8 JSON") from None
        if len(body) > 262144:
            raise GuaranteeUnavailableError("managed Codex text capture exceeds the supported size")
        return body


class ManagedTextCaptureContentPort(Protocol):
    """Read the exact immutable text owned by the existing capture authority."""
    def read_content(self, captured_ref: CapturedInputRef, principal: str) -> ManagedTextCapture | None: ...


__all__ = ["TEXT_CAPTURE_VERSION", "ManagedTextCapture", "ManagedTextCaptureContentPort"]
