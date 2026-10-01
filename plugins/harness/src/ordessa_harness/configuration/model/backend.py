"""Harness-owned native model services for neutral product integrations.

Profile stores desired values; ModelProvider resolves resources. Neither needs
to know native launch options, account directories or per-brand preparation.
"""
from pathlib import Path

from .bridge import BRANDS
from .initial import initial_model_params


class NativeModelLaunchRefused(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def installation_routes(*, artifact_root=None, artifact_roots=None):
    roots = {} if artifact_roots is None else dict(artifact_roots)
    if any(brand not in BRANDS for brand in roots):
        raise ValueError('Unknown Profile installation route')
    # The legacy single-root argument names the first shipped native route.
    if artifact_root is not None:
        if 'pi' in roots and roots['pi'] != artifact_root:
            raise ValueError('Conflicting Pi installation route')
        roots['pi'] = artifact_root
    return roots


def requires_model_catalog(harness_id, credential):
    if harness_id not in BRANDS:
        raise ValueError('Unknown native model route')
    return harness_id == 'pi' and credential is not None


def preparation_params(harness_id, payload, operation_id, *, credential=None, models=None):
    if harness_id == 'pi' and credential is None:
        return None  # Native catalogue-only route has no startup provider effect.
    return initial_model_params(harness_id, payload, operation_id, credential=credential, models=models)


def launch_options(harness_id, payload, *, managed_account_factory=None):
    if payload.get('authentication') != 'managed-account':
        return {}
    initial_model_params(harness_id, payload, 'create:launch-check')
    if not callable(managed_account_factory):
        raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable')
    account = managed_account_factory(harness_id)
    if account.read(refresh=True) != {'authenticated': True, 'method': 'chatgpt-managed'}:
        raise NativeModelLaunchRefused('AUTHENTICATION_REQUIRED', 'Ordessa Codex login required')
    return {'codex_account_directory': account.account_directory}


class NativeModelServices:
    def __init__(self, *, roots, channels, owners, carrier, journal_path):
        self.roots = installation_routes(artifact_roots=roots)
        self.channels, self.owners, self.carrier = channels, owners, carrier
        self.journal_path = journal_path
        self._installations, self._accounts = {}, {}

    def verify(self, harness_id):
        from .live_service import verified_installation
        if harness_id not in self.roots:
            raise ValueError('Trusted native installation route unavailable')
        if harness_id not in self._installations:
            self._installations[harness_id] = verified_installation(harness_id, self.roots[harness_id])
        return self._installations[harness_id]

    def create_service(self, target, *, credential_binding):
        from .live_service import create_model_service
        native = self.owners.readback(target)
        channel = self.channels.get(native.owner.connection_id)
        if channel is None:
            raise ValueError('Native owner unavailable')
        installation = self.verify(channel.harness_id)
        return create_model_service(registry=self.channels, owners=self.owners, target=target,
            carrier=self.carrier, installation=installation, journal_path=self.journal_path,
            credential_binding=credential_binding)

    def managed_account(self, harness_id):
        if harness_id != 'codex' or harness_id not in self.roots:
            raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')
        if harness_id not in self._accounts:
            from ...codex.managed_account import CodexManagedAccount
            self._accounts[harness_id] = CodexManagedAccount.for_installation(
                self.roots[harness_id], Path.home() / '.ordessa/accounts/codex')
        return self._accounts[harness_id]
