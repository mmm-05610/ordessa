"""Single authoritative Profile wire/1 binding schema (core-owned).

The CLI ships a generated JSON mirror. No Server transport lives in core.
"""
from __future__ import annotations

import json
import hashlib
from pacthold.agents.contracts import AGENT_CONTRACT_VERSION, _LOCAL_ID, _DIGEST

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

AGENT_MANAGEMENT_CONTRACT_VERSION = "agent-assembly/3"
_MANAGEMENT_BINDINGS = (
    ("agents.providers.list", "providersList", (), ()),
    ("agents.providers.describe", "providersDescribe", ("definitionRef",), ()),
    ("agents.nodes.prepare", "prepare", ("context", "options", "requestId"), ("profileRef", "profileManifest")),
    ("agents.nodes.queryPreparation", "queryPreparation", ("requestId",), ()),
    ("agents.nodes.list", "nodesList", (), ()),
    ("agents.nodes.read", "nodeRead", ("nodeRef",), ()),
    ("agents.nodes.configuration.describe", "describeConfiguration", ("nodeRef",), ()),
    ("agents.nodes.configuration.inspect", "inspectConfiguration", ("nodeRef",), ()),
    ("agents.nodes.configuration.apply", "applyConfiguration", ("nodeRef", "change"), ()),
    ("agents.nodes.configuration.query", "queryChange", ("nodeRef", "operationRef"), ()),
    ("agents.nodes.applyProfile", "applyProfile", ("nodeRef", "baseProfileRef", "expectedConfigurationRevision", "applicationPolicy", "requestId"), ("profileRef", "profileManifest")),
    ("agents.nodes.acquireAccess", "acquireAccess", ("nodeRef", "purpose", "protocol", "requestId"), ()),
    ("agents.nodes.recover", "recover", ("nodeRef", "preconditions", "requestId"), ()),
    ("agents.nodes.stop", "stop", ("nodeRef", "preconditions", "requestId"), ()),
    ("agents.nodes.release", "release", ("nodeRef", "preconditions", "requestId"), ()),
    ("agents.operations.read", "operationRead", ("operationRef",), ()),
)


def wire_contract(version=AGENT_CONTRACT_VERSION) -> dict:
    """Return an isolated JSON view; callers cannot mutate core authority."""
    if version not in (AGENT_CONTRACT_VERSION, AGENT_MANAGEMENT_CONTRACT_VERSION):
        raise ValueError("unsupported Agent wire contract version")
    value = {"contractVersion": version, "transport": "wire/1",
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
    if version == AGENT_MANAGEMENT_CONTRACT_VERSION:
        # Thin projections of NodePublication.list/read. Absence retains the
        # core's None; publication is not a current native readiness claim.
        value['results'].update({
            'preparationOperation': {'required': ['operationRef', 'revision', 'status', 'node'],
                'additionalProperties': False,
                'statuses': ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']},
            'lifecycleOperation': {'required': ['operationRef', 'revision', 'status', 'action'],
                'additionalProperties': False,
                'statuses': ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']},
            # Sealed six-field operation metadata; no body, evidence or step.
            'operationMetadata': {'required': ['operationRef', 'kind', 'revision', 'status', 'nodeRef', 'hasResult'],
                'additionalProperties': False,
                'statuses': ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']},
            'preparationQuery': {'required': ['operation'], 'additionalProperties': False, 'missing': None},
            'nodesList': {'required': ['nodes'], 'additionalProperties': False},
            'nodeRead': {'required': ['node'], 'additionalProperties': False, 'missing': None},
            'nodeRecord': {'required': ['nodeRef', 'binding', 'lineage', 'publicationRevision',
                'resourceUsageRefs', 'managementSurfaceRefs', 'accessSurfaceRefs'], 'additionalProperties': False},
            'nodeBinding': {'required': ['nodeRef', 'harnessProviderRef', 'harnessDefinitionRef',
                'harnessUnitRef', 'profileSnapshotRef', 'preparationContextRef', 'configurationTargetRef',
                'nativeSessionRefs', 'operationRef'], 'additionalProperties': False},
        })
        value["methods"].update({method: {"action": action, "required": list(required),
            "optional": list(optional), "effectful": "requestId" in required or action == "applyConfiguration",
            "additionalProperties": False}
            for method, action, required, optional in _MANAGEMENT_BINDINGS})
        value["configurationChange"] = {
            "contractVersion": "agent-configuration/1", "additionalProperties": False,
            "required": ["requestId", "expectedConfigurationRevision", "declarations", "applicationPolicy"],
            "applicationPolicy": {"allowDeferred": False, "allowRestart": False},
            "itemOutcomes": ["applied", "deferred", "restartRequired", "rejected", "conflict", "unknown"],
            "overallOutcomes": ["applied", "deferred", "restartRequired", "rejected", "conflict", "unknown", "partial"],
            "appliedRequires": ["operationRef", "unitRef", "scopeRef", "requestDigest", "evidenceRef"],
            "providerContractVersion": "agent-runtime/2",
        }
        value["nodeRef"] = {"required": ["environmentNamespace", "instanceId", "generation"], "additionalProperties": False}
        value["configurationSnapshot"] = {"required": ["unitRef", "scopeRef", "sourceRevision", "observedAt", "configuration", "unknownItems", "confirmationEvidence", "comparisonGuarantee"]}
        # Exactly one configuration source per preparation/update request
        # (interfaces.md 3.1): an exact ProfileRef or a full profile manifest
        # body. Both together, neither, or a bare name are refused before any
        # native effect; the core alone normalizes and digests the body.
        value["profileSource"] = {"exactlyOneOf": ["profileRef", "profileManifest"],
            "manifest": {"required": ["harnessDefinitionRef", "schemaVersion", "declarations"],
                         "optional": ["metadata"], "additionalProperties": False}}
        value["omissionError"] = {"code": "CONFIGURATION_DECLARATIONS_OMITTED",
            "details": ["omittedDeclarationIds"], "requiresResubmit": "explicit reset or disabled declarations"}
    return value


def wire_schema_digest(version=AGENT_CONTRACT_VERSION) -> str:
    value = json.dumps(wire_contract(version), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
