"""Internal method management under an explicitly granted instance capability."""
from contextlib import contextmanager
from dataclasses import asdict

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest


class OriginalMethodManagement:
    def __init__(self, access, scope):
        self.access, self.scope = access, scope

    @contextmanager
    def guard_management(self, context, operation, method_ref, parameters):
        if operation not in ('engineering.methods.adopt', 'engineering.methods.control'):
            raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
        self.access.require(context, operation)
        with self.access.guard_current_capability(context, self.scope, operation) as caller:
            # The original permission lock is held through the consuming UoW
            # COMMIT. This digest captures that event; it does not grant access.
            yield record_digest('product-method-management-event', {
                'scope':asdict(context.scope), 'principal_id':caller.principal_id,
                'credential_epoch':caller.credential_epoch,
                'request_id':context.request_id, 'operation':operation,
                'method_ref':asdict(method_ref), 'parameters':parameters})


class RegisteredMethodPublication:
    """Explicit trusted root publication; no fixture catalog or implicit adopt.

    The deployment selects actual registered readers on this same Library.
    Source loading, compatibility, byte freezing and release uniqueness stay
    in the original Engineering owners. A failed compiler never reaches SQL.
    Calling publish is an explicit deployment action, not a wire capability.
    """
    def __init__(self, factory, access, scope, catalog):
        from .engineering_capability_catalog import RegisteredHostCapabilityCatalog
        if (type(catalog) is not RegisteredHostCapabilityCatalog
                or any(getattr(reader.plugin, '_factory', None) is not factory
                       for reader in catalog.readers)):
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
        from ordessa_engineering.application.assembly import build_method_management
        self.factory, self.catalog = factory, catalog
        self.snapshots = SQLiteSnapshotStore(factory.library)
        self.methods = build_method_management(
            factory, access=access, snapshots=self.snapshots,
            management=OriginalMethodManagement(access, scope))

    def publish(self, source, *, compiler_version):
        from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
        from ordessa_engineering.methods.loading.loader import load_method
        from ordessa_engineering.methods import compile_method
        from ordessa_engineering.methods.definitions.models import MethodSource
        from ordessa_engineering.application.api.method_publication import publish_method
        if type(source) is not MethodSource:
            raise ApplicationError('INVALID_METHOD_SOURCE')
        loaded = load_method(source, FileResourceReader())
        if not loaded.ok:
            return loaded
        compiled = compile_method(loaded.value, self.catalog.read_current(), compiler_version)
        if not compiled.ok:
            return compiled
        return publish_method(compiled.value, self.snapshots,
            capability_catalog=self.catalog)

    def select(self, method_ref, context, *, expected_version):
        """Exact published ref under original management guard/journal CAS."""
        return self.methods.adopt(method_ref, context, expected_version=expected_version)
