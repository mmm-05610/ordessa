"""Harness-owned native model services for neutral product integrations.

Profile stores desired values; ModelProvider resolves resources. Neither needs
to know native launch options, account directories or per-brand preparation.
"""

from .bindings import model_descriptor, supports_model_route
from .bindings import model_port
from ordessa_agents.harness.contracts.errors.native import NativeModelLaunchRefused
from .bindings import capture_selected_native_model_ports




def installation_routes(*, artifact_root=None, artifact_roots=None):
    roots = {} if artifact_roots is None else dict(artifact_roots)
    if any(not supports_model_route(brand) for brand in roots):
        raise ValueError('Unknown Profile installation route')
    # The legacy single-root argument names the first shipped native route.
    if artifact_root is not None:
        aliases = [port.harness_id for port in capture_selected_native_model_ports() if port.single_root_alias]
        if len(aliases) != 1:
            raise ValueError('Unknown Profile installation route')
        alias = aliases[0]
        if alias in roots and roots[alias] != artifact_root:
            raise ValueError('Conflicting Pi installation route')
        roots[alias] = artifact_root
    return roots


def requires_model_catalog(harness_id, credential):
    if not supports_model_route(harness_id):
        raise ValueError('Unknown native model route')
    return model_port(harness_id).requires_catalog(credential)


def preparation_params(harness_id, payload, operation_id, *, credential=None, models=None):
    return model_port(harness_id).prepare(payload, operation_id, credential=credential, models=models)


def launch_options(harness_id, payload, *, managed_account_factory=None):
    return model_port(harness_id).launch(payload, managed_account_factory=managed_account_factory)
