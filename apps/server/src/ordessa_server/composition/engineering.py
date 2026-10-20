"""Select the Engineering plugin for one original library and Server runtime.

Opening never migrates a database. Library creation requires an explicit choice
and a nonexistent path. This selects no Harness/consent fallback.
"""
from collections.abc import Callable
from pathlib import Path

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api import EXECUTION_DISPATCH
from ordessa_system_access_bindings.engineering_wire import (
    EngineeringWireBinding, SUPPORTED_METHODS, REVIEW_REQUEST_QUERY,
)
from ordessa_system_access_bindings.engineering_dispatch import DISPATCH_COMMANDS, DISPATCH_QUERIES
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.contracts.transport import AccessError
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_units.assembly import LocalUnitOwner, UnitRunPermission
from server_plugin_api import ServerPluginDescriptor, ServerPluginRegistration
from server_plugin_api.wire_errors import WireError

# Explicit deployment-only grants; these operations remain absent from wire.
INTERNAL_OWNER_CAPABILITIES = ('engineering.methods.adopt', 'engineering.methods.control',
    'engineering.reviewer.jev', 'engineering.reviewer.composite', 'engineering.reviewer.unit',
    'engineering.conversation.attest')
DEFAULT_MACHINE_CAPABILITIES = tuple(name for name in SUPPORTED_METHODS
    if name not in (*DISPATCH_COMMANDS,*DISPATCH_QUERIES,REVIEW_REQUEST_QUERY,
        "engineering.reviews.record", "engineering.acceptance.adopt", "engineering.runs.resume",
        "engineering.executions.dispatch", "engineering.reviews.assign_reviewer",
        "engineering.reviews.revoke_reviewer"))


def _verify_bound_unit_permission(permission, authority, scope, capabilities):
    """Require the original Unit identity to already carry Engineering access."""
    if (type(permission) is not UnitRunPermission
            or permission.access_authority is not authority):
        raise ValueError("Bound Unit owner does not use the runtime's original access authority")
    try:
        authority.verify(permission.principal)
    except AccessError as exc:
        raise ValueError("Bound Unit owner principal is stale for the runtime authority") from exc
    grant = next((item for item in permission.principal.grants if item.scope == scope), None)
    if grant is None or not set(capabilities).issubset(grant.capabilities):
        raise ValueError("Bound Unit owner principal lacks the selected Engineering scope/capabilities")


class EngineeringServerPlugin:
    def __init__(self, *, path, library_id, scope, authority_resolver, application_ports_factory=None):
        self.path, self.library_id, self.scope = path, library_id, scope
        self._authority_resolver = authority_resolver
        self._application_ports_factory = application_ports_factory
        self.library = None
        self._binding = None

    def descriptor(self):
        return ServerPluginDescriptor("ordessa.engineering", "Engineering application", "1")

    def build(self, context):
        if self.library is not None or getattr(self, '_registration', None) is not None:
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        authority = self._authority_resolver()
        if authority is None:
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        library = EngineeringLibrary.open(self.path, library_id=self.library_id)
        self.library = library
        try:
            factory = SQLiteUoWFactory(library)
            self._factory = factory
            binding = self._binding_for(authority)
            methods = binding.methods()

            def dispose():
                self._registration = None
                self._factory = None
                self._binding = None
                self.library = None
                library.close()

            self._registration = ServerPluginRegistration(methods=methods, disposal=dispose)
            return self._registration
        except BaseException as build_failure:
            self._registration = None
            self._factory = None
            self._binding = None
            self.library = None
            try:
                library.close()
            except BaseException as cleanup_failure:
                build_failure.add_note(
                    f"Engineering library cleanup also failed: {cleanup_failure!r}")
            raise

    def _binding_for(self, authority):
        """One service gate per library/runtime round, with its original access."""
        factory = getattr(self, '_factory', None)
        if factory is None or authority is None:
            raise WireError('UNAVAILABLE', 'Engineering service authority is unavailable')
        if self._binding is None:
            self._binding = EngineeringWireBinding(factory, authority, scope=self.scope,
                application_ports_factory=self._application_ports_factory)
        elif self._binding.access.authority is not authority:
            raise WireError('UNAVAILABLE', 'Engineering service authority changed')
        return self._binding

    def capability_catalog(self):
        from .engineering_capability_catalog import RegisteredEngineeringCommandCatalog
        return RegisteredEngineeringCommandCatalog(self)


_SUPPORTED_LIBRARY_SCHEMAS = (7, 8, 10, 13, 14, 15, 16, 17)
_ENGINEERING_OPTION_KEYS = frozenset({
    "library_path", "library_id", "scope", "realm", "project",
    "create_library", "machine_capabilities", "schema_version",
    "application_ports_factory",
})


def _engineering_selection(options: dict[str, object]) -> tuple[Path, str, Scope, bool, tuple[str, ...], int, Callable | None]:
    """Validate trusted app configuration without building a Server runtime."""
    if type(options) is not dict:
        raise ValueError("Engineering options must be a trusted configuration dictionary")
    unknown = set(options) - _ENGINEERING_OPTION_KEYS
    if unknown:
        raise ValueError("Unknown Engineering configuration fields")
    if "library_path" not in options or "library_id" not in options:
        raise ValueError("Engineering library path and id are required together")
    path = Path(options["library_path"])
    if not path.is_absolute():
        raise ValueError("Explicit absolute library path required")

    if "scope" in options:
        if "realm" in options or "project" in options:
            raise ValueError("Specify Engineering scope or realm/project, not both")
        scope = options["scope"]
        if type(scope) is not Scope:
            raise ValueError("Explicit Engineering scope required")
    else:
        if "realm" not in options or "project" not in options:
            raise ValueError("Engineering realm and project are required together")
        realm, project = options["realm"], options["project"]
        if type(realm) is not str or type(project) is not str:
            raise ValueError("Engineering realm and project must be strings")
        try:
            scope = Scope(realm, project)
        except (TypeError, ValueError) as exc:
            raise ValueError("Explicit Engineering scope required") from exc

    create_library = options.get("create_library", False)
    if type(create_library) is not bool:
        raise ValueError("create_library must be an explicit boolean")
    machine_capabilities = options.get("machine_capabilities", DEFAULT_MACHINE_CAPABILITIES)
    if (type(machine_capabilities) is not tuple
            or any(name not in (*SUPPORTED_METHODS, *INTERNAL_OWNER_CAPABILITIES,
                                EXECUTION_DISPATCH)
                   for name in machine_capabilities)):
        raise ValueError("Only implemented Engineering capabilities may be selected")
    schema_version = options.get("schema_version", 8)
    if type(schema_version) is not int or schema_version not in _SUPPORTED_LIBRARY_SCHEMAS:
        raise ValueError("Explicit supported Engineering schema required")
    application_ports_factory = options.get("application_ports_factory")
    if application_ports_factory is not None and not callable(application_ports_factory):
        raise ValueError("application_ports_factory must be callable")
    library_id = options["library_id"]
    if type(library_id) is not str or not library_id:
        raise ValueError("Explicit Engineering library id required")
    return (path, library_id, scope, create_library, machine_capabilities,
            schema_version, application_ports_factory)


def select_engineering(
    options: dict[str, object],
    authority_resolver: Callable[[], object | None],
) -> tuple[EngineeringServerPlugin, Callable[[object], None]]:
    """Select the Engineering plugin and a callback for one already-built runtime.

    Selection validates the original library and creates it only when explicitly
    requested. It does not open the library or build a Server runtime. The
    callback grants only the configured machine capabilities on the same
    InstanceAccessAuthority already owned by the supplied runtime.
    """
    if not callable(authority_resolver):
        raise ValueError("An existing runtime authority resolver is required")
    (path, library_id, scope, create_library, machine_capabilities,
     schema_version, application_ports_factory) = _engineering_selection(options)
    if create_library:
        if path.exists():
            raise ValueError("Engineering library creation requires a nonexistent path")
        library = EngineeringLibrary.create(
            path, library_id=library_id, schema_version=schema_version)
        library.close()
    elif not path.is_file():
        raise ValueError("Engineering library missing; explicit creation required")

    plugin = EngineeringServerPlugin(path=path, library_id=library_id, scope=scope,
        authority_resolver=authority_resolver,
        application_ports_factory=application_ports_factory)
    configured_runtime = None

    def configure_runtime(runtime):
        nonlocal configured_runtime
        if getattr(runtime, "started", False):
            raise ValueError("Engineering must be configured before the runtime starts")
        if configured_runtime is runtime:
            raise ValueError("Engineering runtime configuration is already applied")
        wire = getattr(runtime, "wire", None)
        runtime_authority = getattr(wire, "identity_authority", None)
        selected_authority = authority_resolver()
        if runtime_authority is None or selected_authority is not runtime_authority:
            raise ValueError("Engineering must use the runtime's existing instance authority")
        if EXECUTION_DISPATCH in machine_capabilities:
            binding = plugin._binding_for(runtime_authority)
            if binding.ports.declared_generation_binder is not None:
                generation = binding.declared_generation_dispatch
                installed = {method.method_id for method in plugin._registration.methods
                             if method.owner == 'ordessa.engineering' and callable(method.handler)}
                if (generation is None or generation is not binding.service.declared_generation_dispatch
                        or not binding.service.declared_generation_ready
                        or getattr(generation, 'factory', None) is not plugin._factory
                        or getattr(generation, 'access', None) is not binding.access
                        or 'engineering.work.invoke' not in installed):
                    raise ValueError("Declared generation is not bound to the selected Work and Unit owners")
            else:
                catalog = plugin.capability_catalog().read_current()
                if not any(item.capability_id == EXECUTION_DISPATCH
                           for item in catalog.capabilities):
                    raise ValueError("Native Engineering dispatch is not bound by the selected original owners")
        execution_owner = getattr(runtime, "unit_execution_owner", None)
        if execution_owner is None:
            runtime_authority.replace_grants((AccessGrant(scope, machine_capabilities),))
        else:
            if type(execution_owner) is not LocalUnitOwner:
                raise ValueError("Runtime Unit owner is not the selected original LocalUnitOwner")
            permission = getattr(execution_owner, "permission", None)
            _verify_bound_unit_permission(permission, runtime_authority, scope, machine_capabilities)
        configured_runtime = runtime

    return plugin, configure_runtime
