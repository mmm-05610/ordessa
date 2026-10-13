"""A fixed Agent-Box profile selected for an Execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class AgentBoxProfileV1:
    contract_id: ClassVar[str] = "agent-box.profile@1"

    name: str
    agent_type: str
    digest: str
    revision: int = 1
    provider: str = "agent-box-profile"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("agent_type", self.agent_type),
            ("digest", self.digest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Agent-Box profile {field_name} is required")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Agent-Box profile revision must be positive")



def exact_historical_envelope(view, *, harness_type: str, profile_id: str,
                              revision: int, digest: str) -> dict:
    """Validate one explicitly supplied historical view for native projection.

    A view is supplied by the admitted modern ProfileService migration reader;
    this pure codec neither discovers files nor grants native execution. Its
    old ref/digest remain distinct from the modern ProfileRevisionRef/digest.
    """
    import hashlib
    import json
    from collections.abc import Mapping

    old_ref = getattr(view, "historical_ref", None)
    envelope = getattr(view, "envelope", None)
    if not callable(envelope) or old_ref is None:
        raise ValueError("EXPLICIT_HISTORICAL_PROFILE_VIEW_REQUIRED")
    if (getattr(old_ref, "harness_type", None) != harness_type
            or getattr(old_ref, "profile_id", None) != profile_id
            or getattr(old_ref, "revision", None) != revision
            or getattr(old_ref, "digest", None) != digest):
        raise ValueError("PROFILE_REF_MISMATCH")
    value = envelope()
    if not isinstance(value, Mapping) or set(value) != {
            "profile_id", "harness_type", "provider_id", "name", "schema_version",
            "revision", "disabled", "credential_source_ref", "capability_refs",
            "session_overlay_policy", "import_provenance", "native_payload", "digest"}:
        raise ValueError("PROFILE_ENVELOPE_IDENTITY_MISMATCH")
    if (value["profile_id"] != profile_id or value["harness_type"] != harness_type
            or value["provider_id"] != "harness-profile" or value["revision"] != revision
            or value["digest"] != digest or value["schema_version"] != 1):
        raise ValueError("PROFILE_ENVELOPE_IDENTITY_MISMATCH")
    body = {key: child for key, child in value.items() if key not in {"digest", "revision"}}
    expected = "sha256:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()
    if expected != digest:
        raise ValueError("PROFILE_DIGEST_DRIFT")
    if value["disabled"] is True:
        raise ValueError("PROFILE_DISABLED")
    if value["disabled"] is not False:
        raise ValueError("PROFILE_ENVELOPE_IDENTITY_MISMATCH")
    if not isinstance(value["native_payload"], Mapping):
        raise ValueError("PROFILE_NATIVE_PAYLOAD_UNAVAILABLE")
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))

from typing import Protocol, runtime_checkable

@runtime_checkable
class HistoricalProfileViewPort(Protocol):
    """Read an exact imported historical view from one admitted Environment.

    Implementations must check the current modern ref and the old ref/digest;
    the view itself grants neither provider admission nor launch authority.
    """
    def select_current(self, modern_ref: object, historical_ref: object) -> object: ...
