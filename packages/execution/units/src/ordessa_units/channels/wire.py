"""Agent input/access wire formats (nodes.acquireAccess).

Instance-management contract owned by the channels unit. Pure format data; the
composed contract lives in the Agent public aggregation entry.
"""

_METHODS = (
    ("agents.nodes.acquireAccess", "acquireAccess", ("nodeRef", "purpose", "protocol", "requestId"), ()),
)


def channels_wire_sections() -> dict:
    return {
        "methods": {
            method: {"action": action, "required": list(required), "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in _METHODS
        },
        "results": {},
    }
