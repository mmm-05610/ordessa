"""Framework-access wire formats: capability advertisement and provider read methods.

Access/capability contract only. The instance-management wire fragments live with
their unit owners; the composed contract and the shared envelope/digest live in
the Agent public aggregation entry.
"""
from __future__ import annotations

ACCESS_METHODS = (
    ("agents.capabilities", "capabilities", (), ()),
)

PROVIDER_READ_METHODS = (
    ("agents.providers.list", "providersList", (), ()),
    ("agents.providers.describe", "providersDescribe", ("definitionRef",), ()),
)


def access_wire_sections() -> dict:
    """Return ``{"legacy_methods": ..., "management_methods": ...}``.

    ``legacy_methods`` are the v1 method bindings (no ``additionalProperties``);
    ``management_methods`` are added by the v3 assembly contract.
    """
    return {
        "legacy_methods": {
            method: {"action": action, "required": list(required),
                     "optional": list(optional), "effectful": "requestId" in required}
            for method, action, required, optional in ACCESS_METHODS
        },
        "management_methods": {
            method: {"action": action, "required": list(required),
                     "optional": list(optional),
                     "effectful": "requestId" in required or action == "applyConfiguration",
                     "additionalProperties": False}
            for method, action, required, optional in PROVIDER_READ_METHODS
        },
    }
