"""Explicit history/wire/storage identifiers; mappings, never runtime fallbacks."""
from __future__ import annotations

from ..definitions.models import Profile, ProfileRevisionRef
from ..definitions.codec import encode_profile, encode_revision_ref

PROFILE_RECORDS = "agents.profile-catalog"
REVISION_RECORDS = "agents.profile-manifests"
SNAPSHOT_RECORDS = "agents.profile-snapshots"
SNAPSHOT_PREFIX = "snap-"
PROFILE_CAPABILITY = "profileCatalog"


def historical_action(action: str) -> str:
    """Keep previously authenticated surface and fingerprint facts unchanged."""
    return "edit" if action == "revise" else action


def creation_facts(profile: Profile, content_json: str) -> dict[str, object]:
    return {"entry": encode_profile(profile), "content": content_json}


def revision_facts(profile_id: str, content_json: str, expected_version: int,
                   base_revision: ProfileRevisionRef) -> dict[str, object]:
    return {"profileId": profile_id, "content": content_json,
            "expectedCatalogRevision": expected_version,
            "baseManifestRef": encode_revision_ref(base_revision)}


def metadata_facts(action: str, profile_id: str, expected_version: int,
                   name: str | None = None) -> dict[str, object]:
    facts = {"profileId": profile_id, "expectedCatalogRevision": expected_version}
    if action == "rename":
        facts["displayName"] = name
    return facts


def clone_facts(source: ProfileRevisionRef, profile_id: str, name: str) -> dict[str, object]:
    return {"sourceRef": encode_revision_ref(source), "profileId": profile_id, "displayName": name}
