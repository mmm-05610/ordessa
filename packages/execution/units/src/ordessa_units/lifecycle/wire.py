"""Agent lifecycle wire formats (recover/stop/release).

Instance-management contract owned by the lifecycle unit. Pure format data; the
composed contract lives in the Agent public aggregation entry.
"""

_METHODS = (
    ("agents.nodes.recover", "recover", ("nodeRef", "preconditions", "requestId"), ()),
    ("agents.nodes.stop", "stop", ("nodeRef", "preconditions", "requestId"), ()),
    ("agents.nodes.release", "release", ("nodeRef", "preconditions", "requestId"), ()),
)


def lifecycle_wire_sections() -> dict:
    return {
        "methods": {
            method: {"action": action, "required": list(required), "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in _METHODS
        },
        "results": {
            "lifecycleOperation": {"required": ["operationRef", "revision", "status", "action"],
                "additionalProperties": False,
                "statuses": ["reserved", "running", "unknown", "published", "refused", "cancelled"]},
        },
    }
