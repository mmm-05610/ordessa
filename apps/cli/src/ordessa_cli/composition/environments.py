"""Local Environment assembly for the CLI: real providers, one owner.

One-shot commands expose only operations that can complete inside the same
process. ``acquire``/``launch``/``export-endpoint``/``process-release`` need the
original live handles and are published only in the retained foreground
session. The provider refuses lifecycle operations it does not implement.

Two providers can be composed here: the always-present ``local`` provider and an
``openshell`` provider built from an explicit ``<state>/openshell.json``. The
OpenShell plugin is imported lazily so the base CLI keeps working without that
distribution installed; a configured-but-unavailable gateway becomes a catalog
entry carrying its reason, never a silent absence or a Local fallback.
"""
from __future__ import annotations

from ordessa_environments import (
    EnvironmentManager, SQLiteEnvironmentStore,
)
from ordessa_environments.capability import EnvironmentCapabilityService, descriptor as environment_descriptor, factory
from ordessa_environments_local import LocalEnvironmentResourceProvider, probe_local
from ordessa_interfaces.system_access import CapabilityHost, build_registry
from ordessa_interfaces_contracts import Capability, CapabilityDescriptor, compute_descriptor_digest

from .identity import LocalForegroundAuthority
from .state import LocalState

ENVIRONMENT_ACTIONS = frozenset({
    'providers', 'list', 'inspect', 'create', 'register', 'exec', 'files', 'stop', 'delete',
    # Binds the evidence of an uncertain creation; it never creates again.
    'reconcile',
    # The thin native management entry: a bounded, read-only view over the
    # provider's own control plane.
    'native.describe', 'native.request', 'native.query', 'native.events',
    'acquire', 'release', 'launch', 'use-inspect', 'observe', 'communicate', 'terminate',
    'detach', 'export', 'resolve', 'export-endpoint', 'endpoint-inspect', 'process-release',
})
SESSION_ONLY = frozenset({
    'environments.acquire', 'environments.launch', 'environments.export-endpoint',
    'environments.process-release',
})


class EnvironmentDomain:
    def __init__(self, *, authority, manager, services, capability, host, openshell=None):
        self.authority = authority
        self.manager = manager
        self.services = services
        self.endpoints = services.endpoints
        self.uses = services.uses
        self.capability = capability
        self.host = host
        self.openshell = openshell

    def close(self):
        try:
            self.authority.revoke()
        finally:
            if self.openshell is not None:
                try:
                    self.openshell.provider._client.close()
                except Exception:
                    pass


def _filter(capability, unavailable):
    if not unavailable:
        return capability
    operations = tuple(operation for operation in capability.descriptor.operations
                       if operation.id not in unavailable)
    base = CapabilityDescriptor(capability.descriptor.id, capability.descriptor.version,
                                operations, '')
    declared = CapabilityDescriptor(base.id, base.version, base.operations,
                                    compute_descriptor_digest(base))
    handlers = {name: handler for name, handler in capability.handlers.items()
                if name not in unavailable}
    return Capability(declared, handlers)


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


def _openshell_entry(state: LocalState):
    """Build the OpenShell binding, or return its explicit unavailability entry.

    Absence of configuration is a normal state, not an error: the catalog then
    says why OpenShell is unavailable so ``environments providers`` never
    reports a provider it cannot address.
    """
    from ordessa_environments import EnvironmentRefused

    try:
        from ordessa_environments_openshell import build_binding, read_configuration
    except ModuleNotFoundError as error:
        return None, _unavailable_openshell(_openshell_missing_reason(error))
    try:
        config = read_configuration(state.openshell_config)
    except EnvironmentRefused as error:
        return None, _unavailable_openshell(str(error))
    if not config:
        return None, _unavailable_openshell(
            'no OpenShell configuration in this state directory')
    try:
        binding = build_binding(config)
    except EnvironmentRefused as error:
        return None, _unavailable_openshell(str(error))
    return binding, binding.catalog


def build_environment_domain(state: LocalState, *, session: bool = False) -> EnvironmentDomain:
    provider = LocalEnvironmentResourceProvider(default_root=str(state.work))
    binding, openshell_catalog = _openshell_entry(state)
    providers = {'local': provider}
    if binding is not None:
        providers['openshell'] = binding.provider
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(state.environments_store),
        providers=providers)
    authority = LocalForegroundAuthority(actions=ENVIRONMENT_ACTIONS)
    probe = probe_local(default_root=str(state.work))
    catalog = [
        {'id': 'local', 'available': bool(probe['available']), 'isolation': 'none',
         'capabilities': sorted(probe.get('capabilities', ())), 'endpointKind': 'local-directory',
         'operations': sorted(provider.operations)},
        openshell_catalog,
    ]
    services = EnvironmentCapabilityService(
        manager, authorize=authority.authorize, provider_catalog=catalog,
        aliases_path=state.aliases)
    capability = factory.build({'services': services, 'invocation_resolver': authority.resolve})
    capability = _filter(capability, set() if session else SESSION_ONLY)
    host = CapabilityHost(build_registry([capability]), ('environments',))
    return EnvironmentDomain(authority=authority, manager=manager, services=services,
                             capability=capability, host=host, openshell=binding)


__all__ = ['ENVIRONMENT_ACTIONS', 'SESSION_ONLY', 'EnvironmentDomain',
           'build_environment_domain', 'environment_descriptor']
