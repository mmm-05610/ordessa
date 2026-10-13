"""codex's public native model composition facts and effect factories."""
from ordessa_execution_agents.harness.definitions.native_model_ports import NativeModelProviderPort
from ordessa_execution_agents.harness.contracts.errors.native import NativeModelLaunchRefused
from .c2 import descriptor
from .initial import initial_model_params
from .runtime import CodexLiveModelRuntime, NATIVE_VERSION
from .service import verified_installation
from .native_actions import create_action_executor


def requires_catalog(credential):
    return False


def preparation_params(payload, operation_id, *, credential=None, models=None):
    return initial_model_params(payload, operation_id, credential=credential, models=models)


def launch_options(payload, *, managed_account_factory=None):
    if payload.get('authentication') != 'managed-account':
        return {}
    initial_model_params(payload, 'create:launch-check')
    if not callable(managed_account_factory):
        raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable')
    account = managed_account_factory('codex')
    if not authenticated(account):
        raise NativeModelLaunchRefused('AUTHENTICATION_REQUIRED', 'Ordessa Codex login required')
    return {'codex_account_directory': account.account_directory}


def authenticated(account):
    return account.read(refresh=True) == {'authenticated': True, 'method': 'chatgpt-managed'}


def create_managed_account(artifact_root):
    from pathlib import Path
    from ..managed_account import CodexManagedAccount
    return CodexManagedAccount.for_installation(artifact_root, Path.home() / '.ordessa/accounts/codex')


def provider():
    return NativeModelProviderPort('codex', NATIVE_VERSION, descriptor, initial_model_params,
        CodexLiveModelRuntime, verified_installation, create_action_executor, requires_catalog,
        preparation_params, launch_options, create_managed_account, authenticated,
        managed_account_supported=True, publication_unavailable_message='One published matching model adapter required', live_registration=False, provider_restoration=True, single_root_alias=False)
