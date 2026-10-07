"""Explicit native configuration contributions for pi."""


def configuration_adapters():
    """Create fresh implementations; runtime state belongs to an instance.

    Import lazily because the shared C2 translation imports brand compilers.
    No discovery by filesystem scan and no process launch during registration.
    """
    from ordessa_server_product.harness_adapters.configuration.model.bridge import BridgeConfigurationAdapter

    return (BridgeConfigurationAdapter("pi"),)
