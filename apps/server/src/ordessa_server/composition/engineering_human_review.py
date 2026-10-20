"""Formal human review composed on the original Engineering authority.

The configured source port must authenticate actual Q&A and current selected
policy. Instance bearer authentication alone supplies no human disposition.
"""
from ordessa_engineering.application.contracts.errors import ApplicationError


def human_review_ports_factory(*, bindings, manual_authority_factory, proof_lookup=None):
    """Trusted host injection, never a callable or policy selected by wire input."""
    if bindings is None or not callable(manual_authority_factory):
        raise ApplicationError('HUMAN_REVIEW_AUTHORITY_UNAVAILABLE')

    def build(factory, access, scope):
        from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
        from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
        from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
        from ordessa_engineering.application.usecases.reviews.human import EngineeringHumanReviewAdmission
        from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
        from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
        methods = SQLiteMethodControl(factory, SQLiteSnapshotStore(factory.library))
        blobs = SQLiteBlobStore(factory.library)
        bound = bindings(factory, methods) if callable(bindings) else bindings
        authority = manual_authority_factory(factory, methods, blobs, access, scope)
        if authority is None or not callable(getattr(authority, 'guard_disposition', None)):
            raise ApplicationError('HUMAN_REVIEW_AUTHORITY_UNAVAILABLE')
        mechanical = MechanicalReviewCheckSource(factory, methods, blobs)
        admission = EngineeringHumanReviewAdmission(factory, methods, bound,
            authority, blobs=blobs, mechanical_source=mechanical)
        from .engineering_human_preparation import OriginalHumanReviewPresentation
        presentation = (OriginalHumanReviewPresentation(factory,admission,proof_lookup)
            if callable(proof_lookup) else None)
        return EngineeringApplicationPorts(blobs=blobs, review_admission=admission,
            review_presentation=presentation)

    return build
