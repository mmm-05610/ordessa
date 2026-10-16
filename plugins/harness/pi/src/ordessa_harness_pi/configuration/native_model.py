"""pi's public native model composition facts and effect factories."""
from ordessa_execution_agents.harness.definitions.native_model_ports import NativeModelProviderPort
from ordessa_execution_agents.harness.contracts.errors.native import NativeModelLaunchRefused
from .c2 import descriptor
from .initial import initial_model_params
from .runtime import PiLiveModelRuntime, NATIVE_VERSION
from .service import verified_installation
from .native_actions import create_action_executor


def requires_catalog(credential):
    return credential is not None


def preparation_params(payload, operation_id, *, credential=None, models=None):
    if credential is None:
        return None
    return initial_model_params(payload, operation_id, credential=credential, models=models)


def launch_options(payload, *, managed_account_factory=None):
    if payload.get('authentication') != 'managed-account':
        return {}
    initial_model_params(payload, 'create:launch-check')
    if not callable(managed_account_factory):
        raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable')
    account = managed_account_factory('pi')
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')


def authenticated(account):
    return False


def create_managed_account(artifact_root):
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')


def provider():
    return NativeModelProviderPort('pi', NATIVE_VERSION, descriptor, initial_model_params,
        PiLiveModelRuntime, verified_installation, create_action_executor, requires_catalog,
        preparation_params, launch_options, create_managed_account, authenticated,
        managed_account_supported=False, publication_unavailable_message='One published Pi model adapter required', live_registration=True, provider_restoration=False, single_root_alias=True)
