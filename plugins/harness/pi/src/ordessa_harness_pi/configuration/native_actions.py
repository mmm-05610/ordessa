"""pi native configuration dialect over an explicit executor factory."""
CONFIGURATION_IDS = ('model', 'thinkingLevel')


def create_action_executor(registry, owners, *, executor_factory, target, expected_configuration_digest):
    if not callable(executor_factory):
        raise ValueError("Explicit native action executor factory required")
    return executor_factory(registry, owners, target=target,
        expected_configuration_digest=expected_configuration_digest,
        harness_id='pi', configuration_ids=CONFIGURATION_IDS)
