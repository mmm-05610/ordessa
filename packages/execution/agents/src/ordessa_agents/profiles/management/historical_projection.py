"""Decode and validate explicit historical Profile projections."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def exact_historical_envelope(view, *, harness_type: str, profile_id: str,
                              revision: int, digest: str) -> dict:
    """Validate one explicitly supplied historical view for native projection.

    The old ref/digest remain distinct from modern ProfileRevisionRef and its
    digest. This parser neither discovers files nor grants native execution.
    """
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


__all__ = ["exact_historical_envelope"]
