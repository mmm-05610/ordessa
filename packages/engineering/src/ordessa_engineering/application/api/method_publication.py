"""Public snapshot publication using the original immutable store mechanism.

Publication returns the original business MethodRef. Project selection/control
is a separate authorized command built by application.assembly. This entry
does not supply a catalogue, management permission or project selection.
"""
from ..usecases.publish_snapshot import freeze_method
from ...domain.artifacts.method_binding import MethodRef
from ...domain.common.models.values import Digest
from ...methods.definitions.errors import MethodResult
from ...methods.definitions.errors import MethodFailure, MethodError
from ...methods.definitions.models import LoadedMethod


def publish_method(compiled, snapshots, *, capability_catalog):
    """Publish captured bytes and return their computed exact MethodRef.

    ``snapshots`` is the same original SnapshotStore/ReleasedIdentityIndex.
    The original publisher checks the current host catalogue and atomically
    enforces immutable release identity. Missing/unqualified capabilities and
    conflicting existing release bytes retain its original failures.
    """
    result = freeze_method(compiled, snapshots, snapshots,
                           capability_catalog=capability_catalog)
    if not result.ok:
        return MethodResult.failure(result.error)
    ref = result.value.ref
    return MethodResult.success(MethodRef(ref.method_id, ref.release_version,
                                         ref.schema_version,
                                         Digest('sha256', ref.snapshot_digest)))


def publish_method_declaration(loaded: LoadedMethod, snapshots):
    """Publish exact schema-2 source in the original immutable release store.

    A declaration has no compiled execution program or capability activation.
    Publication does not create project control, select a method, or grant any
    source/reviewer permission. The store reconstructs and validates the source
    before writing; caller-supplied projections are not publication evidence.
    """
    try:
        ref = snapshots.publish_declaration(loaded)
        return MethodResult.success(MethodRef(
            ref.method_id, ref.release_version, ref.schema_version,
            Digest('sha256', ref.snapshot_digest)))
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, TypeError, ValueError):
        return MethodResult.failure(MethodError(
            'METHOD_DECLARATION_PUBLICATION_INVALID',
            'an exact declaration and original publication store are required'))


__all__ = ['publish_method', 'publish_method_declaration']
