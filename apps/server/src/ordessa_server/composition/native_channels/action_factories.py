"""Host dispatch over explicitly selected independent native action ports."""
from .native_action_executor import NativeSessionActionExecutor


def create_native_action_executor(registry, owners, *, target, expected_configuration_digest, harness_id):
    from ordessa_server.composition.configuration.model.bindings import model_port
    try:
        port = model_port(harness_id)
    except ValueError:
        raise ValueError('Pinned native action brand required') from None
    return port.create_action_executor(registry, owners, executor_factory=NativeSessionActionExecutor,
        target=target, expected_configuration_digest=expected_configuration_digest)


def create_pi_action_executor(registry, owners, *, target, expected_configuration_digest):
    from ordessa_server.composition.selected_native_configuration import capture_selected_native_model_ports
    ports = [port for port in capture_selected_native_model_ports() if port.live_registration]
    if len(ports) != 1:
        raise ValueError('Pinned native action brand required')
    return create_native_action_executor(registry, owners, target=target,
        expected_configuration_digest=expected_configuration_digest, harness_id=ports[0].harness_id)
