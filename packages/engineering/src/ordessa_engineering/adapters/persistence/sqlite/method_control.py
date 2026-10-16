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
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
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
            if not hasattr(factory.library,'_method_declaration_fences'):
                factory.library._method_declaration_fences=threading.local()
            if not hasattr(factory.library,'_method_declaration_sources'):
                factory.library._method_declaration_sources=threading.local()

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

    def read_declaration(self, context, method_ref, *, expected_version=None):
        """Declaration read for declarative Work; no program, no live grant.

        The release must be under current method control: a missing control, a
        disabled method, or a control version other than the caller's expectation
        is refused before any declaration is handed out. Nothing here compiles,
        materializes a program, or advances a run.
        """
        if type(context) is not CommandContext or type(method_ref) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        if expected_version is not None and (type(expected_version) is not int
                or not 0 <= expected_version <= (1<<63)-1):
            raise ApplicationError('INVALID_INPUT')
        with self.factory.library._lock:
            with self.factory.begin(context.scope,'read') as uow:
                control=uow.methods.control(method_ref)
                if not control.enabled:
                    raise ApplicationError('METHOD_DISABLED')
                if expected_version is not None and expected_version != control.version:
                    raise ApplicationError('METHOD_CONTROL_CHANGED')
        from ordessa_engineering.methods.definitions.models.identity import MethodRef as _DeclarationRef
        declaration_ref=_DeclarationRef(method_ref.method_id,method_ref.release_version,
            method_ref.schema_version,method_ref.snapshot_digest.hex)
        return self.snapshots.get_declaration(declaration_ref), control.version

    def guard_selected(self, context, *, expected_version=None):
        """Resolve the explicitly selected project method for new work."""
        return self._guard(context,None,expected_version,True)

    @staticmethod
    def _snapshot_ref(method_ref):
        return SnapshotRef(method_ref.method_id, method_ref.release_version,
                           method_ref.schema_version, method_ref.snapshot_digest.hex)

    @contextmanager
    def guard(self, context, method_ref):
        """Yield the exact published schema-2 declaration under original control.

        The existing method-control fence remains active through the consuming
        UoW commit. This is declaration admission, not a workflow compiler.
        """
        if type(context) is not CommandContext or type(method_ref) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        if method_ref.schema_version != 2:
            raise ApplicationError('METHOD_DECLARATION_SCHEMA_UNSUPPORTED')
        library = self.factory.library
        with library._lock:
            with self.factory.begin(context.scope, 'read') as uow:
                control = uow.methods.control(method_ref)
                if not control.enabled:
                    raise ApplicationError('METHOD_DISABLED')
            # Load and verify the published declaration and its captured source
            # exactly once while holding the original library lock. Resource
            # lookups below use this same verified bundle for this guard only.
            definition, loaded = self.snapshots._load_declaration(
                self._snapshot_ref(method_ref))
            if definition.method_ref.snapshot_digest != method_ref.snapshot_digest.hex:
                raise ApplicationError('METHOD_STATE_CORRUPT')
            controls = library._method_guard_fences
            previous_controls = getattr(controls, 'values', ())
            controls.values = previous_controls + ((control, None),)
            declarations = library._method_declaration_fences
            previous_declarations = getattr(declarations, 'values', ())
            declarations.values = previous_declarations + ((context, method_ref, definition),)
            sources = library._method_declaration_sources
            previous_sources = getattr(sources, 'values', ())
            sources.values = previous_sources + ((context, method_ref, loaded),)
            try:
                yield definition
            finally:
                declarations.values = previous_declarations
                sources.values = previous_sources
                controls.values = previous_controls

    def _guarded_source(self, context, method_ref):
        """Return source bytes only from this thread's exact active guard."""
        active = getattr(self.factory.library._method_declaration_sources, 'values', ())
        return next((loaded for bound_context, bound_method, loaded in reversed(active)
                     if bound_context == context and bound_method == method_ref), None)

    def read_resource(self, context, ref: ExactMethodResourceRef) -> bytes:
        """Return exact captured bytes only while this context guards the pin."""
        if type(context) is not CommandContext or type(ref) is not ExactMethodResourceRef:
            raise ApplicationError('INVALID_INPUT')
        active = getattr(self.factory.library._method_declaration_fences, 'values', ())
        definition_entry = next((item for item in reversed(active)
                                 if item[0] == context and item[1] == ref.method_ref), None)
        loaded = self._guarded_source(context, ref.method_ref)
        if definition_entry is None or loaded is None:
            raise ApplicationError('METHOD_DECLARATION_GUARD_REQUIRED')
        _, _, definition = definition_entry
        if definition.method_ref.snapshot_digest != ref.method_ref.snapshot_digest.hex:
            raise ApplicationError('METHOD_STATE_CORRUPT')
        capture = next((item.captured for item in loaded.source_bundle.resources
                        if item.resource_id == ref.resource_id), None)
        if (capture is None or capture.logical_path != ref.logical_path
                or capture.digest != ref.resource_digest.hex):
            raise ApplicationError('METHOD_RESOURCE_REF_MISMATCH')
        return capture.data

    def resource_ref(self, context, method_ref, resource_id):
        """Resolve one exact published resource ID under this caller's guard."""
        if (type(context) is not CommandContext or type(method_ref) is not MethodRef
                or type(resource_id) is not str):
            raise ApplicationError('INVALID_INPUT')
        active = getattr(self.factory.library._method_declaration_fences, 'values', ())
        if (not any(item[0] == context and item[1] == method_ref for item in active)
                or (loaded := self._guarded_source(context, method_ref)) is None):
            raise ApplicationError('METHOD_DECLARATION_GUARD_REQUIRED')
        from ordessa_engineering.domain.common.models.values import Digest
        capture = next((item.captured for item in loaded.source_bundle.resources
                        if item.resource_id == resource_id), None)
        if capture is None:
            raise ApplicationError('METHOD_RESOURCE_REF_MISMATCH')
        return ExactMethodResourceRef(method_ref, capture.logical_path,
                                      Digest('sha256', capture.digest), resource_id)

    def preparation_roles(self, context, definition, resource_refs):
        """Resolve finite roles from the exact guarded method declaration."""
        if type(context) is not CommandContext or type(resource_refs) is not tuple:
            raise ApplicationError('INVALID_INPUT')
        active = getattr(self.factory.library._method_declaration_fences, 'values', ())
        guard = next((item for item in reversed(active)
                      if item[0] == context and item[2] is definition), None)
        if guard is None:
            raise ApplicationError('METHOD_DECLARATION_GUARD_REQUIRED')
        _, method_ref, _ = guard
        loaded = self._guarded_source(context, method_ref)
        if loaded is None:
            raise ApplicationError('METHOD_DECLARATION_GUARD_REQUIRED')
        documents = [item for action in definition.actions
                     for item in action.preparation_documents]
        if not documents:
            raise ApplicationError('METHOD_PREPARATION_ROLES_UNAVAILABLE')
        captures = {item.resource_id: item.captured
                    for item in loaded.source_bundle.resources}
        refs = {}
        for ref in resource_refs:
            if type(ref) is not ExactMethodResourceRef or ref.method_ref != method_ref:
                raise ApplicationError('METHOD_RESOURCE_REF_MISMATCH')
            capture = captures.get(ref.resource_id)
            if (capture is None or capture.logical_path != ref.logical_path
                    or capture.digest != ref.resource_digest.hex):
                raise ApplicationError('METHOD_RESOURCE_REF_MISMATCH')
            if ref.resource_id in refs:
                raise ApplicationError('INVALID_INPUT')
            refs[ref.resource_id] = ref
        for document in documents:
            capture = captures.get(document.template_resource_id)
            if capture is None or document.template_resource_id not in refs:
                raise ApplicationError('METHOD_PREPARATION_TEMPLATE_UNAVAILABLE')
            if (capture.logical_path != refs[document.template_resource_id].logical_path
                    or capture.digest != refs[document.template_resource_id].resource_digest.hex):
                raise ApplicationError('METHOD_RESOURCE_REF_MISMATCH')
        return tuple(item.role for item in documents)
