"""Explicit native configuration contributions for claude-code."""


def configuration_adapters():
    """Create fresh implementations; runtime state belongs to an instance.

    Import lazily because the shared C2 translation imports brand compilers.
    No discovery by filesystem scan and no process launch during registration.
    """
    from ..configuration.model.bridge import BridgeConfigurationAdapter

    return (BridgeConfigurationAdapter("claude-code"),)
