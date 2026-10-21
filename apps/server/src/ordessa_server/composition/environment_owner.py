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

from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
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
        'exec', 'files', 'acquire', 'release', 'process-release',
        'export-endpoint', 'endpoint-inspect', 'use-inspect',
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
        binding = None
        openshell_catalog = None
        try:
            from ordessa_environments_openshell import build_binding, read_configuration
            config = read_configuration(state / 'openshell.json')
            if config:
                binding = build_binding(config)
                manager.providers[binding.provider.identity] = binding.provider
                openshell_catalog = binding.catalog
        except ModuleNotFoundError:
            openshell_catalog = {'id': 'openshell', 'available': False, 'status': 'UNAVAILABLE',
                                 'reason': 'OpenShell plugin is not installed', 'capabilities': []}
        except Exception as error:
            openshell_catalog = {'id': 'openshell', 'available': False, 'status': 'UNAVAILABLE',
                                 'reason': type(error).__name__ + ': ' + str(error), 'capabilities': []}
        if openshell_catalog is not None:
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
