"""Narrow adapters/descriptors for original mechanical source-review checks.

These describe evidence adapters that already exist. They are not a registry,
method activation, execution router, semantic evaluator, or permission source.
"""
from contextlib import contextmanager

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import (
    CheckSourceAdmission,
    FrozenCheckRequest,
    VerifiedCheckResponse,
)
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.reviews.models import CheckKey, ReviewPlan
from ordessa_engineering.methods.definitions.models.capabilities import (
    CapabilityDescriptor,
    CompilationCapabilities,
)
from ordessa_engineering.methods.definitions.models.identity import method_digest


_SOURCE_INTEGRITY = "ordessa.sources.integrity"
_CLAIMS_COVERAGE = "ordessa.claims.coverage"
_INTERFACE = "1.0.0"
_MAX_CHECK_KEYS = 4096


class MechanicalCheckCapabilityAdapter:
    """Route only the two named checks to the original source implementation.

    This adapter preserves the complete plan and frozen source request. It
    never synthesizes a disposition or reviewer identity; the returned answer
    statuses are the source owner's original CriterionAnswer values.
    """

    def __init__(self, source):
        if type(source) is not MechanicalReviewCheckSource:
            raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
        factory = getattr(source, "factory", None)
        methods = getattr(source, "methods", None)
        blobs = getattr(source, "blobs", None)
        if (factory is None or getattr(methods, "factory", None) is not factory
                or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)):
            raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
        self.source = source
        self.factory = factory

    @staticmethod
    def _validate(capability_id, context, full_plan, request, *, standard, check_keys):
        if capability_id not in (_SOURCE_INTEGRITY, _CLAIMS_COVERAGE):
            raise ApplicationError("REVIEW_CHECK_EXECUTION_UNAVAILABLE")
        if (type(full_plan) is not ReviewPlan or type(request) is not FrozenCheckRequest
                or full_plan.scope != context.scope
                or request.plan_digest != full_plan.plan_digest
                or type(request.request_version) is not int
                or not 0 <= request.request_version <= 9007199254740991
                or type(request.fence) is not int or not 1 <= request.fence <= 9007199254740991
                or type(check_keys) is not tuple or not check_keys
                or len(check_keys) > _MAX_CHECK_KEYS
                or any(type(key) is not CheckKey for key in check_keys)
                or len(set(check_keys)) != len(check_keys)
                or not set(check_keys) <= set(full_plan.check_keys)):
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        criteria = {item.criterion_id: item for item in getattr(standard, "criteria", ())}
        for key in check_keys:
            criterion = criteria.get(key.criterion_id)
            checks = getattr(criterion, "checks", ()) if criterion is not None else ()
            if (len(checks) != 1 or checks[0].capability_id != capability_id
                    or checks[0].interface_version != _INTERFACE):
                raise ApplicationError("REVIEW_CHECK_EXECUTION_UNAVAILABLE")

    def execute(self, capability_id, context, full_plan, request, *, standard, check_keys):
        """Capture then verify via the original owner; return its BlobRef/answers."""
        self._validate(capability_id, context, full_plan, request,
            standard=standard, check_keys=check_keys)
        proof_ref = self.source.capture_proof(context, full_plan, request,
            standard=standard, check_keys=check_keys)
        if type(proof_ref) is not BlobRef:
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        response = self.source.verify_checks(context, full_plan, request, proof_ref,
            standard=standard, check_keys=check_keys)
        if type(response) is not VerifiedCheckResponse:
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        return proof_ref, response

    @contextmanager
    def guard_checks(self, capability_id, context, full_plan, request, *, standard,
                     check_keys, raw_response_ref, response):
        """Revalidate adapter scope then hold the original source guard."""
        self._validate(capability_id, context, full_plan, request,
            standard=standard, check_keys=check_keys)
        if type(raw_response_ref) is not BlobRef or type(response) is not VerifiedCheckResponse:
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        admission = CheckSourceAdmission(full_plan, request, raw_response_ref, check_keys, response)
        with self.source.guard_checks(context, (admission,)):
            yield


def mechanical_review_check_capabilities() -> CompilationCapabilities:
    """Describe only the two checks implemented by MechanicalReviewCheckSource.

    The frozen standard and full ReviewPlan remain caller inputs which the
    existing source owner verifies against its method snapshot. No generic
    dispatch adapter or independent pass rule is introduced here.
    """
    shared = {
        "owner": "Engineering.application.usecases.reviews.mechanical.MechanicalReviewCheckSource",
        "context": "method-declared Artifact provenance checks",
        "standard_binding": "exact original method snapshot standard and criterion identity; enforced by source owner",
        "route": "MechanicalCheckCapabilityAdapter.execute and guard_checks",
        "request": {
            "type": "FrozenCheckRequest",
            "fields": ["plan_digest", "request_version", "fence"],
            "coverage": "requested check keys must be a unique subset of the unchanged full plan",
        },
        "subject": "scope-matched schema-2 ArtifactRevisionRef in the original EngineeringLibrary",
        "facts": [
            "canonical revision bytes and digest",
            "verified material/schema closure",
            "original BlobStore bytes, digest and selector validation",
            "source capture and claim/evidence-link structure",
        ],
        "bounds": {"proof_bytes_max": 2097152, "check_keys_max": 4096},
        "guard": "reverify exact proof and current method/source bytes through original Review COMMIT",
        "semantic_authority": False,
    }
    contracts = (
        (_SOURCE_INTEGRITY, {
            **shared,
            "result": {
                "captured_source_bytes_and_selectors_valid": "satisfied",
                "no_captured_source_bytes": "insufficient",
            },
            "does_not_establish": ["source authenticity", "claim support", "source completeness"],
        }),
        (_CLAIMS_COVERAGE, {
            **shared,
            "result": {
                "claims_and_evidence_link_chain_complete": "unknown",
                "claim_set_empty_or_link_missing": "insufficient",
            },
            "does_not_establish": ["semantic claim support", "decision completeness", "review pass"],
            "complete_chain_is_never_satisfied": True,
        }),
    )
    descriptors = tuple(
        CapabilityDescriptor(
            capability_id=capability_id,
            kind="check",
            interface_version=_INTERFACE,
            contract_digest=method_digest("capability-contract", contract),
            contract=contract,
        )
        for capability_id, contract in contracts
    )
    return CompilationCapabilities(descriptors, trust_class="host")


class InvariantCheckCapabilityAdapter:
    """Expose actual content/schema and original Submission correlation owners."""
    def __init__(self,source):
        from ..usecases.reviews.invariants import DeclaredInvariantReviewCheckSource
        if type(source) is not DeclaredInvariantReviewCheckSource:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.source,self.factory=source,source.factory

    @staticmethod
    def _validate(capability_id,context,plan,request,standard,keys):
        from ..usecases.reviews.invariants import DeclaredInvariantReviewCheckSource
        if capability_id not in ('ordessa.schema.validate','ordessa.submission.binding'):
            raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
        if plan.scope!=context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        DeclaredInvariantReviewCheckSource._validate_request(plan,request,standard,keys)
        if any(next(c for c in standard.criteria if c.criterion_id==key.criterion_id)
               .checks[0].capability_id!=capability_id for key in keys):
            raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')

    def execute(self,capability_id,context,full_plan,request,*,standard,check_keys):
        self._validate(capability_id,context,full_plan,request,standard,check_keys)
        proof=self.source.capture_proof(context,full_plan,request,standard=standard,check_keys=check_keys)
        response=self.source.verify_checks(context,full_plan,request,proof,standard=standard,check_keys=check_keys)
        return proof,response

    @contextmanager
    def guard_checks(self,capability_id,context,full_plan,request,*,standard,
                     check_keys,raw_response_ref,response):
        self._validate(capability_id,context,full_plan,request,standard,check_keys)
        admission=CheckSourceAdmission(full_plan,request,raw_response_ref,check_keys,response)
        with self.source.guard_checks(context,(admission,)):
            yield


def invariant_review_check_capabilities():
    """Detached descriptions of2 real deterministic checks; no policy decisions."""
    shared={
        'owner':'DeclaredInvariantReviewCheckSource',
        'route':'InvariantCheckCapabilityAdapter.execute / guard_checks',
        'input':'unchanged original ReviewPlan/FrozenCheckRequest, exact subset of CheckKeys, fixed method standard',
        'proof':'same-authority original BlobStore, exact subject/source bytes and request identity revalidated through Review COMMIT',
        'semantic_authority':False,'acceptance_authority':False,
        'bounds':{'proof_bytes_max':2097152,'check_keys_max':4096},
    }
    contracts=(
        ('ordessa.schema.validate',{**shared,
         'subject':'exact ArtifactRevision or Submission MethodContent',
         'binding':'frozen standard schema/schema_by_document_type plus exact method/resource identity',
         'mechanism':'existing validate_document_content on actual immutable content value',
         'results':'valid body satisfied; invalid body violated; no MethodContent insufficient; unknown schema/source refuses',
         'does_not_establish':['semantic sufficiency','human permission','review acceptance']}),
        ('ordessa.submission.binding',{**shared,
         'subject':'original immutable Submission/package/Grant/baselines/output revisions and dispatch correlation',
         'mechanism':'existing validate_submission_graph and original same-UoW reference resolution',
         'results':'exact original graph correlation satisfied; missing or mismatched original owner facts refuse',
         'does_not_establish':['executor code or Git correctness','test or effect truth','current permission','acceptance']}),
    )
    return CompilationCapabilities(tuple(CapabilityDescriptor(capability,'check','1.0.0',
        method_digest('capability-contract',contract),contract) for capability,contract in contracts),trust_class='host')


def bound_review_check_capabilities(admission, *, expected_factory, expected_access, expected_scope):
    """Read only the real source routes on original review admission.

    Product registration still owns publication and the resulting catalog.
    This helper cannot convert dictionaries or detached descriptors into routes.
    """
    from ..usecases.reviews.admission import EngineeringReviewAdmission
    from ..usecases.reviews.mixed import MixedReviewerSource
    from ..usecases.reviews.mechanical import MechanicalReviewCheckSource
    from ..usecases.reviews.invariants import DeclaredInvariantReviewCheckSource
    from .decision_checks import GenericDecisionCheckSource,generic_decision_check_capability
    from .unit_review import UnitReviewCheckSource
    from ...domain.common.models.identity import Scope
    from ...domain.common.models.values import RealmId, ProjectId, validate_id
    if type(admission) is not EngineeringReviewAdmission:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    if expected_factory is None or expected_access is None or expected_scope is None:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    try:
        expected_scope = Scope(RealmId(expected_scope.realm_id), ProjectId(expected_scope.project_id))
    except (AttributeError, TypeError, ValueError):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH') from None
    expected_authority_id = getattr(expected_factory, 'authority_id', None)
    if type(expected_authority_id) is not str or not expected_authority_id:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    if admission.factory is not expected_factory:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    source=admission.source
    if type(source) is not MixedReviewerSource or source.authority is None:
        raise ApplicationError('MIXED_REVIEWER_AUTHORITY_UNAVAILABLE')
    authority = source.authority
    selected_authority = getattr(expected_access, 'authority', None)
    selected_principal = getattr(selected_authority, 'principal_id', None)
    actual_scope = getattr(authority, 'scope', None)
    try:
        validate_id(selected_principal)
    except (TypeError, ValueError):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH') from None
    if (source.factory is not expected_factory
            or getattr(admission.methods, 'factory', None) is not expected_factory
            or getattr(source.methods,'factory',None) is not expected_factory
            or getattr(source.blobs,'authority_id',None)!=expected_authority_id
            or getattr(authority, 'access', None) is not expected_access
            or getattr(authority, 'principal_id', None) != selected_principal
            or not callable(getattr(authority, 'guard_verification', None))
            or actual_scope is None):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    try:
        actual_scope = Scope(RealmId(actual_scope.realm_id), ProjectId(actual_scope.project_id))
    except (AttributeError, TypeError, ValueError):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH') from None
    if actual_scope != expected_scope:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    descriptions=[]
    for kind,descriptors in (
            (MechanicalReviewCheckSource,mechanical_review_check_capabilities().capabilities),
            (DeclaredInvariantReviewCheckSource,invariant_review_check_capabilities().capabilities),
            (GenericDecisionCheckSource,(generic_decision_check_capability(),))):
        for descriptor in descriptors:
            sid=source.mapping.get((descriptor.capability_id,descriptor.interface_version))
            target=source.sources.get(sid)
            if type(target) is kind:
                if (target.factory is not expected_factory
                        or getattr(target.methods, 'factory', None) is not expected_factory
                        or getattr(target.blobs, 'authority_id', None) != expected_authority_id):
                    raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
                if kind is GenericDecisionCheckSource:
                    unit = target.source
                    if (type(unit) is not UnitReviewCheckSource
                            or unit.factory is not expected_factory
                            or getattr(unit.methods, 'factory', None) is not expected_factory
                            or getattr(unit.blobs, 'authority_id', None) != expected_authority_id
                            or unit.authority is None
                            or any(not callable(getattr(unit.records, name, None)) for name in
                                   ('acp_turn_query_digest', 'query_acp_turn'))
                            or any(not callable(getattr(unit.bindings, name, None)) for name in
                                   ('resolve_unit_review', 'decode_response', 'resolve_record_request'))
                            or not callable(getattr(unit.authority, 'guard_unit_reviewer', None))):
                        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
                descriptions.append(descriptor)
    return CompilationCapabilities(tuple(descriptions),trust_class='host')
