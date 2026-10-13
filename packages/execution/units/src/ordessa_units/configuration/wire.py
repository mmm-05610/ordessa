"""Agent configuration wire formats (describe/inspect/apply/query, applyProfile, change).

Instance-management contract owned by the configuration unit. Pure format data;
the composed contract lives in the Agent public aggregation entry. ``configurationChange``
and ``configurationSnapshot`` are top-level contract sections; the other units'
results are merged into ``results`` by the aggregator.
"""

_METHODS = (
    ("agents.nodes.configuration.describe", "describeConfiguration", ("nodeRef",), ()),
    ("agents.nodes.configuration.inspect", "inspectConfiguration", ("nodeRef",), ()),
    ("agents.nodes.configuration.apply", "applyConfiguration", ("nodeRef", "change"), ()),
    ("agents.nodes.configuration.query", "queryChange", ("nodeRef", "operationRef"), ()),
    ("agents.nodes.applyProfile", "applyProfile", ("nodeRef", "baseProfileRef", "expectedConfigurationRevision", "applicationPolicy", "requestId"), ("profileRef", "profileManifest")),
)


def configuration_wire_sections() -> dict:
    return {
        "methods": {
            method: {"action": action, "required": list(required), "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in _METHODS
        },
        "configurationChange": {"contractVersion": "agent-configuration/1", "additionalProperties": False,
            "required": ["requestId", "expectedConfigurationRevision", "declarations", "applicationPolicy"],
            "applicationPolicy": {"allowDeferred": False, "allowRestart": False},
            "itemOutcomes": ["applied", "deferred", "restartRequired", "rejected", "conflict", "unknown"],
            "overallOutcomes": ["applied", "deferred", "restartRequired", "rejected", "conflict", "unknown", "partial"],
            "appliedRequires": ["operationRef", "unitRef", "scopeRef", "requestDigest", "evidenceRef"],
            "providerContractVersion": "agent-runtime/2"},
        "configurationSnapshot": {"required": ["unitRef", "scopeRef", "sourceRevision", "observedAt", "configuration", "unknownItems", "confirmationEvidence", "comparisonGuarantee"]},
        "omissionError": {"code": "CONFIGURATION_DECLARATIONS_OMITTED",
            "details": ["omittedDeclarationIds"], "requiresResubmit": "explicit reset or disabled declarations"},
    }
