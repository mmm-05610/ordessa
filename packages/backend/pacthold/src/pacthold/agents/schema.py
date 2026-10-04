"""Single authoritative Profile wire/1 binding schema (core-owned).

The CLI ships a generated JSON mirror. No Server transport lives in core.
"""
from __future__ import annotations

import json
import hashlib
from .contracts import AGENT_CONTRACT_VERSION, _LOCAL_ID, _DIGEST

_BINDINGS = (
    ("agents.capabilities", "capabilities", (), ()),
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


def wire_contract() -> dict:
    """Return an isolated JSON view; callers cannot mutate core authority."""
    return {"contractVersion": AGENT_CONTRACT_VERSION, "transport": "wire/1",
            "requestKeyScope": ["environmentNamespace", "principalScope", "requestId"],
            "profileRef": {"required": ["environmentNamespace", "profileId", "manifestRevision", "contentDigest"],
                           "additionalProperties": False,
                           "properties": {
                               "environmentNamespace": {"type": "string", "pattern": _LOCAL_ID.pattern},
                               "profileId": {"type": "string", "pattern": _LOCAL_ID.pattern},
                               "manifestRevision": {"type": "integer", "minimum": 1},
                               "contentDigest": {"type": "string", "pattern": _DIGEST.pattern},
                           }},
            "results": {
                "catalogEntry": {"required": ["profileId", "catalogRevision", "displayName", "archivedAt", "currentManifestRef"]},
                "manifest": {"required": ["ref", "content"]},
                "list": {"required": ["entries"]},
                "preview": {"required": ["profileRef", "status", "referenceCoverage", "ready", "error"]},
            },
            "methods": {method: {"action": action, "required": list(required),
                                 "optional": list(optional), "effectful": "requestId" in required}
                        for method, action, required, optional in _BINDINGS}}


def wire_schema_digest() -> str:
    value = json.dumps(wire_contract(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
