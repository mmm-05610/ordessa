"""Neutral lookup over explicitly selected independent public native ports."""
from ordessa_server.composition.selected_native_configuration import capture_selected_native_model_ports

def model_port(harness_id):
    matches = [port for port in capture_selected_native_model_ports() if port.harness_id == harness_id]
    if len(matches) != 1:
        raise ValueError('Unknown native model route')
    return matches[0]


def model_descriptor(harness_id):
    return model_port(harness_id).descriptor()


def supports_model_route(harness_id):
    return any(port.harness_id == harness_id for port in capture_selected_native_model_ports())


def initial_model_factory(harness_id):
    return model_port(harness_id).initial_params
