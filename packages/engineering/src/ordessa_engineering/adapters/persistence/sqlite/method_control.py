"""Public method guards share the original library lock and UoW CAS.

The temporary thread-local expectations are fences, never another state store.
Every consuming original UoW rechecks them after BEGIN; BEGIN IMMEDIATE then
prevents another SQLite connection changing the state before its COMMIT.
"""
from contextlib import contextmanager
import threading
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef
from .unit_of_work import SQLiteUoWFactory
from .snapshot_store import SQLiteSnapshotStore


class SQLiteMethodControl:
    def __init__(self, factory, snapshots):
        if type(factory) is not SQLiteUoWFactory or type(snapshots) is not SQLiteSnapshotStore or snapshots.library is not factory.library:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory,self.snapshots=factory,snapshots
        with factory.library._lock:
            if not hasattr(factory.library,'_method_guard_fences'):
                factory.library._method_guard_fences=threading.local()

    @contextmanager
    def _guard(self, context, method, expected_version, selected):
        if type(context) is not CommandContext or (method is not None and type(method) is not MethodRef):
            raise ApplicationError('INVALID_INPUT')
        if expected_version is not None and (type(expected_version) is not int or not 0 <= expected_version <= (1<<63)-1):
            raise ApplicationError('INVALID_INPUT')
        library=self.factory.library
        with library._lock:
            with self.factory.begin(context.scope,'read') as uow:
                adoption=uow.methods.selected() if selected else None
                ref=adoption.method_ref if selected else method
                control=uow.methods.control(ref)
                if not control.enabled:
                    raise ApplicationError('METHOD_DISABLED')
                current=adoption.version if selected else control.version
                if expected_version is not None and expected_version != current:
                    raise ApplicationError('METHOD_SELECTION_CHANGED' if selected else 'METHOD_CONTROL_CHANGED')
            snapshot=self.snapshots.get(SnapshotRef(ref.method_id,ref.release_version,ref.schema_version,ref.snapshot_digest.hex))
            if adoption is not None:
                from ordessa_engineering.methods.compilation.encoding import program_plan_digest
                if program_plan_digest(snapshot.program).removeprefix('sha256:') != adoption.compiled_plan_digest.hex:
                    raise ApplicationError('METHOD_STATE_CORRUPT')
            fences=library._method_guard_fences
            previous=getattr(fences,'values',())
            fences.values=previous+((control,adoption),)
            try:
                yield snapshot
            finally:
                fences.values=previous

    def guard_method(self, context, method_ref, *, expected_version=None):
        """Historical work stays pinned: newer adoption does not disable M1."""
        return self._guard(context,method_ref,expected_version,False)

    def read_snapshot(self, method_ref):
        """Exact immutable definition only; caller admission is the service gate."""
        if type(method_ref) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        return self.snapshots.get(SnapshotRef(method_ref.method_id, method_ref.release_version,
            method_ref.schema_version, method_ref.snapshot_digest.hex))

    def guard_selected(self, context, *, expected_version=None):
        """Resolve the explicitly selected project method for new work."""
        return self._guard(context,None,expected_version,True)
