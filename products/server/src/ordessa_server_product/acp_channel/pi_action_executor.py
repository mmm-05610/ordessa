"""Pi's admitted native action dialect over the shared owner-fenced executor."""
from .native_action_executor import ACTION_ID, NativeSessionActionExecutor, configuration_digest


class PiSessionActionExecutor(NativeSessionActionExecutor):
    def __init__(self, registry, owners, *, target, expected_configuration_digest):
        super().__init__(registry, owners, target=target,
            expected_configuration_digest=expected_configuration_digest, harness_id='pi')
