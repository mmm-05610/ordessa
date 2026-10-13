"""Agent operation read wire formats (operations.read).

Instance-management contract owned by the admission unit. Pure format data; the
composed contract lives in the Agent public aggregation entry.
"""

_METHODS = (
    ("agents.operations.read", "operationRead", ("operationRef",), ()),
)


def admission_wire_sections() -> dict:
    return {
        "methods": {
            method: {"action": action, "required": list(required), "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in _METHODS
        },
        "results": {
            "operationMetadata": {"required": ["operationRef", "kind", "revision", "status", "nodeRef", "hasResult"],
                "additionalProperties": False,
                "statuses": ["reserved", "running", "unknown", "published", "refused", "cancelled"]},
        },
    }
