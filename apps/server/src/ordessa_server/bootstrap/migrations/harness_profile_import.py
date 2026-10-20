"""Explicit one-shot historical capture import into an admitted ProfileService.

The caller supplies target identity, accepted declarations and request/CAS facts.
This module constructs no Environment, supports no native schema and reads no files.
"""
from __future__ import annotations

from ordessa_execution_agents.profiles import (
    HistoricalProfileIdentityMismatch, ProfileService, ProfileRevisionRef,
    ProfileValidationError,
    decode_content, encode_content,
)
from ordessa_infrastructure.identifiers import RequestKey
from .harness_profile_history import CapturedHarnessProfile, validated_capture

PROVENANCE_FIELD = "historicalHarnessProfile"


def import_harness_profile(*, profiles: ProfileService, captured: CapturedHarnessProfile,
                           profile_id: str, name: str | None, content: dict,
                           request: RequestKey, expected_version: int | None = None,
                           base_revision: ProfileRevisionRef | None = None):
    """Create or revise exclusively through the supplied service's original authority.

    None/None explicitly selects create. Revise requires both current management
    version and exact base ref. Disabled captures refuse until policy is decided.
    Historical native/provenance data is metadata, never an executable declaration.
    """
    if type(profiles) is not ProfileService:
        raise TypeError("original public ProfileService required")
    if type(request) is not RequestKey:
        raise TypeError("explicit authenticated Profile RequestKey required")
    if request.environment_namespace != profiles.environment_namespace:
        raise HistoricalProfileIdentityMismatch("Profile request environment differs")
    if (expected_version is None) != (base_revision is None):
        raise ValueError("both management CAS and fixed base revision required")
    if base_revision is not None and (
            type(base_revision) is not ProfileRevisionRef
            or base_revision.environment_namespace != profiles.environment_namespace
            or base_revision.profile_id != profile_id):
        raise HistoricalProfileIdentityMismatch("fixed base Profile identity differs")
    historical = validated_capture(captured)
    if historical.get("disabled"):
        raise ValueError("PROFILE_DISABLED")
    # Freeze caller intent and historical bytes before any admission callback.
    body = encode_content(decode_content(content, profiles.environment_namespace))
    metadata = body.setdefault("metadata", {})
    if PROVENANCE_FIELD in metadata:
        raise ValueError("historical provenance must not be supplied by caller content")
    metadata[PROVENANCE_FIELD] = historical
    # Original Profile validation enforces bounded/finite JSON and SecretRef rules
    # on metadata; no legacy secret/native values bypass its admitted boundary.
    body = encode_content(decode_content(body, profiles.environment_namespace))
    if base_revision is None:
        return profiles.create(profile_id=profile_id, name=name, content=body, request=request)
    # Name is create-only. Replay must not compare against today's catalog.
    if name is not None:
        raise ValueError("revise name must be omitted; use explicit rename")
    return profiles.revise(profile_id, content=body, expected_version=expected_version,
                           base_revision=base_revision, request=request)
