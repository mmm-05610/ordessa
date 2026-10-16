"""Pure Profile wire/1 format: ProfileRef, catalog results and the Profile methods.

Format definitions only. The shared Agent wire envelope, version selection and
contract composition live in the Agent public aggregation entry; this module owns
the Profile-specific fragment. The id/digest patterns are *format* constants and
are the single source consumed by ``profiles.definitions.validation``.
"""
from __future__ import annotations

import re

LOCAL_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

PROFILE_METHODS = (
    ("agents.profiles.list", "list", (), ("includeArchived",)),
    ("agents.profiles.read", "read", ("profileRef",), ()),
    ("agents.profiles.readEntry", "readEntry", ("profileId",), ()),
    ("agents.profiles.create", "create", ("profileId", "displayName", "manifest", "requestId"), ()),
    ("agents.profiles.edit", "edit", ("profileId", "manifest", "expectedCatalogRevision", "baseManifestRef", "requestId"), ()),
    ("agents.profiles.clone", "clone", ("profileRef", "profileId", "displayName", "requestId"), ()),
    ("agents.profiles.rename", "rename", ("profileId", "displayName", "expectedCatalogRevision", "requestId"), ()),
    ("agents.profiles.archive", "archive", ("profileId", "expectedCatalogRevision", "requestId"), ()),
    ("agents.profiles.restore", "restore", ("profileId", "expectedCatalogRevision", "requestId"), ()),
    ("agents.profiles.preview", "preview", ("profileRef",), ()),
)


def _method(action, required, optional):
    return {"action": action, "required": list(required), "optional": list(optional),
            "effectful": "requestId" in required}


def profile_wire_sections() -> dict:
    """Return the Profile wire fragment: profileRef, catalog results, Profile methods."""
    return {
        "profileRef": {
            "required": ["environmentNamespace", "profileId", "manifestRevision", "contentDigest"],
            "additionalProperties": False,
            "properties": {
                "environmentNamespace": {"type": "string", "pattern": LOCAL_ID.pattern},
                "profileId": {"type": "string", "pattern": LOCAL_ID.pattern},
                "manifestRevision": {"type": "integer", "minimum": 1},
                "contentDigest": {"type": "string", "pattern": DIGEST.pattern},
            },
        },
        "results": {
            "catalogEntry": {"required": ["profileId", "catalogRevision", "displayName", "archivedAt", "currentManifestRef"]},
            "manifest": {"required": ["ref", "content"]},
            "list": {"required": ["entries"]},
            "preview": {"required": ["profileRef", "status", "referenceCoverage", "ready", "error"]},
        },
        "methods": {method: _method(action, required, optional)
                    for method, action, required, optional in PROFILE_METHODS},
    }
