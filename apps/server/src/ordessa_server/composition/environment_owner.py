"""Server-owned Environment owner: the local provider, real use/process lifetime.

The capability, store, alias bindings and use operations are the environments
owner's own; this module only assembles them inside the locked data root and maps
the instance identity onto the existing owner scope. No shell, terminal or
credential handling is added here — the provider's own contract stays in force.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from ordessa_environments import EnvironmentManager, EnvironmentRefused, SQLiteEnvironmentStore
from ordessa_environments.capability import EnvironmentCapabilityService, factory
from ordessa_environments_local import LocalEnvironmentResourceProvider, probe_local
from ordessa_interfaces.system_access.access_control.authentication import (
    InstanceAccessAuthority,
    AccessError,
)
from ordessa_server.composition.agent_owner import AgentOwnerUnavailable
from ordessa_server.composition.invocation import ServerInvocation

#: The exact environment operations this product exposes. Grants name these ids.
ENVIRONMENT_OPERATIONS: 'tuple[str, ...]' = tuple(
    'environments.' + action for action in (
        'providers', 'list', 'inspect', 'create', 'register', 'stop', 'delete',
        # Binds the evidence of an uncertain creation; it never creates again.
        'reconcile',
        'exec', 'files', 'acquire', 'release', 'process-release',
        'export-endpoint', 'endpoint-inspect', 'use-inspect',
        # The thin native management entry: a bounded, read-only view over the
        # provider's own control plane.
        'native.describe', 'native.request', 'native.query', 'native.events',
        # Permission rights the exec/endpoint paths also authorize.
        'launch', 'observe', 'communicate', 'terminate', 'detach', 'export', 'resolve'))


@dataclass
class ServerEnvironmentOwner:
    """The single retained Environment owner for this runtime."""

    store: SQLiteEnvironmentStore
    manager: EnvironmentManager
    services: EnvironmentCapabilityService
    capability: object
    work_root: Path
    openshell: object | None = None

    def close(self) -> None:
        try:
            if self.openshell is not None:
                # The gateway client is the plugin's own; close it, never the service.
                client = getattr(getattr(self.openshell, 'provider', None), '_client', None)
                if callable(getattr(client, 'close', None)):
                    client.close()
        finally:
            close = getattr(self.store, 'close', None)
            if callable(close):
                close()


def _authorize_factory(authority: InstanceAccessAuthority):
    def authorize(scope, action, target, invocation):
        if type(invocation) is not ServerInvocation:
            return False
        try:
            authority.verify(invocation.principal)
        except AccessError:
            return False
        if invocation.owner_scope != scope:
            return False
        operation = 'environments.' + str(action)
        return any(grant.scope == scope_scope and operation in grant.capabilities
                   for scope_scope, grant in _grants_of(invocation, authority))
    return authorize


def _grants_of(invocation, authority):
    """The verified principal's grants, paired with their own scopes."""
    return [(grant.scope, grant) for grant in invocation.principal.grants]


def _unavailable_openshell(reason):
    """One explicit catalog entry for an OpenShell this instance cannot use."""
    return {'id': 'openshell', 'available': False, 'status': 'UNAVAILABLE',
            'reason': reason, 'capabilities': []}


def _openshell_missing_reason(error):
    """Tell a missing SDK extra apart from a missing plugin distribution.

    The provider plugin and the official OpenShell SDK are two separate
    installations. Reporting "the plugin is not installed" when only the
    declared ``openshell`` extra is absent would state something false about
    this instance.
    """
    missing = getattr(error, 'name', None) or ''
    if missing == 'ordessa_environments_openshell' or missing.startswith('ordessa_environments_openshell.'):
        return 'OpenShell plugin is not installed'
    return ('OpenShell SDK is not installed (declared openshell extra missing: '
            + (missing or 'openshell') + ')')


def _close_openshell(binding):
    """Release the SDK client of a binding this instance refuses to use."""
    client = getattr(getattr(binding, 'provider', None), '_client', None)
    if callable(getattr(client, 'close', None)):
        client.close()


def _openshell_entry(state, manager):
    """Bind the configured OpenShell provider, or say exactly why it is unusable.

    The catalog always names OpenShell: an unconfigured instance, an absent
    plugin distribution and an absent SDK extra are three different facts, and
    a client must be able to tell them apart. A configured-but-unusable
    gateway is never a silent Local fallback.
    """
    try:
        from ordessa_environments_openshell import build_binding, read_configuration
    except ModuleNotFoundError as error:
        return None, _unavailable_openshell(_openshell_missing_reason(error))
    try:
        config = read_configuration(state / 'openshell.json')
    except EnvironmentRefused as error:
        return None, _unavailable_openshell(str(error))
    if not config:
        return None, _unavailable_openshell(
            'no OpenShell configuration in this state directory')
    try:
        binding = build_binding(config)
    except Exception as error:
        return None, _unavailable_openshell(type(error).__name__ + ': ' + str(error))
    try:
        # The registry binds a provider to its immutable gateway/workspace
        # binding. A changed binding is refused, never silently rebound.
        manager.store.bind_provider(binding.provider.identity, binding.provider.binding_id)
    except Exception as error:
        _close_openshell(binding)
        return None, _unavailable_openshell(type(error).__name__ + ': ' + str(error))
    manager.providers[binding.provider.identity] = binding.provider
    return binding, binding.catalog


def build_environment_owner(root: Path, *, authority: InstanceAccessAuthority,
                            invocation_resolver) -> ServerEnvironmentOwner:
    """Assemble the local Environment owner inside an already locked data root."""
    if not isinstance(root, Path) or not root.is_absolute():
        raise AgentOwnerUnavailable('explicit absolute product root required')
    state = root / 'state'
    work_root = state / 'environments'
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    store = SQLiteEnvironmentStore(state / 'environments.sqlite')
    try:
        provider = LocalEnvironmentResourceProvider(default_root=str(work_root))
        manager = EnvironmentManager(store=store, providers={'local': provider})
        probe = probe_local(default_root=str(work_root))
        catalog = [{
            'id': 'local',
            'available': bool(probe['available']),
            'isolation': 'none',
            'capabilities': sorted(probe.get('capabilities', ())),
            'endpointKind': 'local-directory',
            'operations': sorted(provider.operations),
        }]
        # OpenShell is opt-in through one explicit state file: absence is a
        # normal unconfigured state, a configured-but-unusable gateway becomes a
        # catalog entry carrying its reason — never a silent Local fallback.
        # The catalog always names OpenShell, so a client can tell "not
        # configured here" from "not installed here".
        binding, openshell_catalog = _openshell_entry(state, manager)
        catalog.append(openshell_catalog)
        services = EnvironmentCapabilityService(
            manager,
            authorize=_authorize_factory(authority),
            provider_catalog=catalog,
            aliases_path=state / 'environment-aliases.json',
        )
        capability = factory.build({'services': services, 'invocation_resolver': invocation_resolver})
    except BaseException:
        close = getattr(store, 'close', None)
        if callable(close):
            close()
        raise
    return ServerEnvironmentOwner(store=store, manager=manager, services=services,
                                  capability=capability, work_root=work_root,
                                  openshell=binding)


__all__ = ["ENVIRONMENT_OPERATIONS", "ServerEnvironmentOwner", "build_environment_owner"]
