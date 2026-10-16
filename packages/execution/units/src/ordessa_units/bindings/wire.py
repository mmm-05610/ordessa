"""Agent node-binding wire formats (prepare/query/list/read, node refs, profile source).

Instance-management contract owned by the bindings unit. Pure format data; the
composed contract lives in the Agent public aggregation entry.
"""

_METHODS = (
    ("agents.nodes.prepare", "prepare", ("context", "options", "requestId"), ("profileRef", "profileManifest")),
    ("agents.nodes.queryPreparation", "queryPreparation", ("requestId",), ()),
    ("agents.nodes.list", "nodesList", (), ()),
    ("agents.nodes.read", "nodeRead", ("nodeRef",), ()),
)

_RESULTS = {
    "preparationOperation": {"required": ["operationRef", "revision", "status", "node"],
        "additionalProperties": False,
        "statuses": ["reserved", "running", "unknown", "published", "refused", "cancelled"]},
    "preparationQuery": {"required": ["operation"], "additionalProperties": False, "missing": None},
    "nodesList": {"required": ["nodes"], "additionalProperties": False},
    "nodeRead": {"required": ["node"], "additionalProperties": False, "missing": None},
    "nodeRecord": {"required": ["nodeRef", "binding", "lineage", "publicationRevision",
        "resourceUsageRefs", "managementSurfaceRefs", "accessSurfaceRefs"], "additionalProperties": False},
    "nodeBinding": {"required": ["nodeRef", "harnessProviderRef", "harnessDefinitionRef",
        "harnessUnitRef", "profileSnapshotRef", "preparationContextRef", "configurationTargetRef",
        "nativeSessionRefs", "operationRef"], "additionalProperties": False},
}


def bindings_wire_sections() -> dict:
    return {
        "methods": {
            method: {"action": action, "required": list(required), "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in _METHODS
        },
        "results": {name: dict(schema) for name, schema in _RESULTS.items()},
        "nodeRef": {"required": ["environmentNamespace", "instanceId", "generation"], "additionalProperties": False},
        "profileSource": {"exactlyOneOf": ["profileRef", "profileManifest"],
            "manifest": {"required": ["harnessDefinitionRef", "schemaVersion", "declarations"],
                         "optional": ["metadata"], "additionalProperties": False}},
    }
