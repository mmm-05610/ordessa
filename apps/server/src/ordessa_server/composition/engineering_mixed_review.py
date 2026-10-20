"""Mixed reviews admitted by the existing explicitly selected service identity.

This adapter grants nothing. A trusted deployment must select the composite
review capability in the original instance authority. Its reviewer stays a
service, and nominal/manual checks never become human approval or a Grant.
"""
from contextlib import contextmanager
from dataclasses import asdict

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_interfaces.system_access.contracts.refs import Scope

COMPOSITE_REVIEW_CAPABILITY = 'engineering.reviewer.composite'


class OriginalCompositeReviewerAuthority:
    def __init__(self, access, *, scope, principal_id, roles):
        # v1 admits this service role only. Human/manual role policies belong
        # to the independent human source owner, not this machine principal.
        if (type(scope) is not Scope or principal_id != access.authority.principal_id
                or roles != ('reviewer',)):
            raise ApplicationError('MIXED_REVIEWER_AUTHORITY_UNAVAILABLE')
        self.access, self.scope, self.principal_id, self.roles = access, scope, principal_id, roles

    @contextmanager
    def guard_verification(self, context, plan, raw_ref, observations_digest,
            provenance_digest, *, expected=None):
        if (context.principal_id != self.principal_id or plan.scope != context.scope
                or (context.scope.realm_id, context.scope.project_id)
                    != (self.scope.realm_id, self.scope.project_id)
                or type(observations_digest) is not Digest or type(provenance_digest) is not Digest
                or not set(plan.reviewer_requirements) <= set(self.roles)
                or not set(self.roles) <= set(plan.requirement.eligible_reviewer_roles)):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        with self.access.guard_current_capability(context, self.scope, COMPOSITE_REVIEW_CAPABILITY) as caller:
            actor = ActorRef(caller.principal_id, 'service', 'instance-bearer')
            if caller.kind != 'machine' or caller.principal_id != self.principal_id or context.authenticated_actor != actor:
                raise ApplicationError('UNTRUSTED_REVIEWER')
            capability = record_digest('product-composite-review-capability', {
                'scope':asdict(context.scope), 'principal_id':caller.principal_id,
                'kind':caller.kind, 'credential_epoch':caller.credential_epoch,
                'capability':COMPOSITE_REVIEW_CAPABILITY, 'roles':self.roles,
                'plan_digest':asdict(plan.plan_digest),
                'source_provenance_digest':asdict(provenance_digest)})
            evidence = VerifiedReviewerEvidence(context.scope, actor, self.roles,
                'ordessa.instance-composite-reviewer', '1', caller.credential_epoch,
                plan.request_digest, raw_ref.digest, observations_digest, capability)
            if expected is not None and expected != evidence:
                raise ApplicationError('UNTRUSTED_REVIEWER')
            yield evidence


def mixed_review_ports_factory(*, bindings, jev_source_factory, roles):
    """Trusted root composition, never a wire callable or a default grant.

    The JEV factory receives the same original method/blob owners. Business
    bindings stay the Engineering binding port; this function invents no plan,
    check disposition, trust store, human answer, or confirmation port.
    """
    if bindings is None or not callable(jev_source_factory) or roles != ('reviewer',):
        raise ApplicationError('MIXED_REVIEWER_AUTHORITY_UNAVAILABLE')

    def build(factory, access, scope):
        from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
        from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
        from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
        from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
        from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
        from ordessa_engineering.application.usecases.reviews.mixed import MixedReviewerSource
        from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
        methods = SQLiteMethodControl(factory, SQLiteSnapshotStore(factory.library))
        blobs = SQLiteBlobStore(factory.library)
        jev = jev_source_factory(methods, blobs, access, scope)
        if (getattr(jev, 'method_control', None) is not methods
                or getattr(jev, 'blobs', None) is not blobs or getattr(jev, 'access', None) is not access
                or getattr(jev, 'scope', None) != scope):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        composite = OriginalCompositeReviewerAuthority(access, scope=scope,
            principal_id=access.authority.principal_id, roles=roles)
        mixed = MixedReviewerSource(factory, methods, blobs,
            sources={'original-jev':jev, 'original-mechanical':MechanicalReviewCheckSource(factory, methods, blobs)},
            source_for_capability={('ordessa.decision.evaluate','1.0.0'):'original-jev',
                ('ordessa.sources.integrity','1.0.0'):'original-mechanical',
                ('ordessa.claims.coverage','1.0.0'):'original-mechanical'},
            reviewer_authority=composite)
        return EngineeringApplicationPorts(blobs=blobs,
            review_admission=EngineeringReviewAdmission(factory, methods, bindings, mixed))

    return build
