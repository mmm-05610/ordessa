"""Implementation intent closure on the original Proposal/baseline/method owners."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ...contracts.snapshots import EngineeringTargetBindings
from ....domain.approvals.implementation import (
    ImplementationAuthorizationIntent, WorkPackageAuthorization,
    WorkPackageAuthorizationIntent,
)
from ....domain.changes.models import ChangeSet
from ...orchestration.method_bridge import MethodBridge
from ..proposal_closure import resolve_record


def _requirements(values):
    return sorted(canonical_bytes(asdict(value)) for value in values)


@dataclass(frozen=True)
class WorkPackageAuthorizationFacts:
    work: object
    package: object
    requirements: tuple
    review_refs: tuple
    reviews: tuple
    method_control: object


def resolve_work_package_authorization(uow, authorization):
    """Re-read the exact v2 subject; this resolves facts, never grants access.

    The Work is frozen before the notice, so its full digest does not include
    the later Grant. A dispatch selects that Grant from its original authority,
    rather than revising this Work and invalidating its own authorization.
    """
    from ...contracts.work_context import (
        WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding,
    )
    from ....domain.packages.models import PreparedPackagePayload
    from ...orchestration.declared_prepare_packages import verify_reviewed_change
    if (type(authorization) is not WorkPackageAuthorization
            or authorization.scope != uow.scope):
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    # The existing schema17 relation is required; no alternate table or run is
    # fabricated when a deployment has not selected declared Work storage.
    uow.work_dispatch
    head = uow.workflow.head_ref(
        WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + authorization.work_id)
    if (head is None or head.revision != authorization.work_revision
            or head.digest != 'sha256:' + authorization.work_digest.hex):
        raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_WORK_CHANGED')
    work = decode_work_binding(uow.workflow.read(head))
    packages = tuple(item.ref for item in work.associations if item.kind == 'package')
    if (work.scope != authorization.scope or work.method_ref != authorization.method_ref
            or work.revision != authorization.work_revision
            or packages != (authorization.package_ref,)):
        raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
    package = uow.implementation.resolve_package(authorization.package_ref)
    payload = package.payload
    if (type(payload) is not PreparedPackagePayload
            or package.scope != work.scope or payload.method_ref != work.method_ref):
        raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
    proposals = tuple(item.ref for item in work.associations if item.kind == 'proposal')
    if proposals and proposals != (payload.change_ref,):
        raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
    control = uow.methods.control(authorization.method_ref)
    if not control.enabled:
        raise ApplicationError('METHOD_DISABLED')
    records = []
    for ref in payload.review_refs:
        # This resolver only reads context.scope; the transaction is the source
        # of that scope. No caller DTO is being treated as authentication.
        proposal, _, record = verify_reviewed_change(
            uow, uow, proposal_ref=payload.change_ref, review_ref=ref,
            method_ref=payload.method_ref, baseline=payload.baseline,
            candidate=payload.candidate)
        if (set(payload.review_refs) != set(proposal.source_change.review_refs)
                or payload.method_resource_refs != proposal.source_change.method_resource_refs):
            raise ApplicationError('WORK_PACKAGE_AUTHORIZATION_BINDING_MISMATCH')
        records.append(record)
    requirements = tuple(record.plan.requirement for record in records)
    if (not requirements or len(set((r.requirement_id, r.requirement_version)
                                   for r in requirements)) != len(requirements)):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    return WorkPackageAuthorizationFacts(work, package, requirements,
                                         payload.review_refs, tuple(records), control)


def resolve_implementation_intent(uow, intent):
    """No captured intent or caller requirement list is itself permission."""
    if type(intent) is WorkPackageAuthorizationIntent:
        return resolve_work_package_authorization(uow, intent.authorization)
    if type(intent) is not ImplementationAuthorizationIntent or intent.scope != uow.scope:
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    uow.authorization.require_implementation_authorization_schema()
    budget = uow.proposals.validated_budget()
    proposals = tuple(uow.proposals.get_proposal(ref, budget=budget) for ref in intent.change_set.proposal_refs)
    controls = tuple(uow.proposals.get_control(p.ref, budget=budget) for p in proposals)
    if (ChangeSet(tuple(p.ref for p in proposals)) != intent.change_set
            or any(c.disposition != 'available' for c in controls)
            or any(p.method_ref != intent.method_ref or p.implementation_intent != intent.implementation_spec
                   for p in proposals)):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    targets = tuple(m.proposed_ref for p in proposals for m in p.mutations)
    if len(targets) != len(set(targets)) or set(targets) != set(intent.targets):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    requirements = tuple(r for p in proposals for r in resolve_record(p, uow.proposals, budget))
    if _requirements(requirements) != _requirements(intent.required_review_requirements):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    for ref in intent.implementation_spec.expected_baselines:
        uow.proposals.resolve_repository_baseline(ref, budget)
    for ref in intent.supporting_review_refs:
        controlled = uow.reviews.get_review(ref)
        if controlled.control.state != 'active' or controlled.record.plan.requirement not in requirements:
            raise ApplicationError('REVIEW_STALE')
    return proposals, controls, requirements


class ImplementationIntentAdmission:
    """Configured original business bindings and current method guard span COMMIT.

    Conversation admission still attests the actual configured user Q&A. This
    guard neither manufactures that Q&A nor upgrades a DID/apply grant.
    """
    def __init__(self, factory, method_control, bindings):
        if getattr(method_control, 'factory', None) is not factory:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.bindings = factory, method_control, bindings
        self.bridge = MethodBridge()

    @contextmanager
    def guard_intent(self, context, intent):
        if type(intent) is WorkPackageAuthorizationIntent:
            if intent.scope != context.scope:
                raise ApplicationError('SCOPE_MISMATCH')
            guard = getattr(self.methods, 'guard', None)
            if not callable(guard):
                raise ApplicationError('METHOD_AUTHORITY_UNAVAILABLE')
            with guard(context, intent.method_ref) as declaration:
                authorization = intent.authorization
                actions = tuple(action for action in declaration.actions
                                if action.action_id == authorization.action_id)
                steps = (() if len(actions) != 1 else tuple(
                    step for step in actions[0].steps
                    if step.step_id == authorization.step_id))
                if (len(steps) != 1 or steps[0].kind != 'invoke'
                        or steps[0].name != 'implement-approved-package'):
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                with self.factory.begin(context.scope, 'read') as uow:
                    resolve_implementation_intent(uow, intent)
                yield
            return
        if type(intent) is not ImplementationAuthorizationIntent or intent.scope != context.scope:
            raise ApplicationError('INTENT_OWNER_UNAVAILABLE')
        resolver = getattr(self.bindings, 'resolve_intent_bindings', None)
        if not callable(resolver):
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        with self.methods.guard_method(context, intent.method_ref) as snapshot:
            resolved = tuple((ref, resolver(context, intent.method_ref, ref))
                             for ref in intent.change_set.proposal_refs)
            complete = []
            with self.factory.begin(context.scope, 'read') as uow:
                resolve_implementation_intent(uow, intent)
                budget = uow.proposals.validated_budget()
                for ref, phases in resolved:
                    if (type(phases) is not tuple or not phases
                            or any(type(b) is not EngineeringTargetBindings or b.scope != context.scope for b in phases)
                            or len({b.phase_key for b in phases}) != len(phases)):
                        raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                    for phase in phases:
                        self.bridge.require_workflow_phase(snapshot, phase)
                    proposal = uow.proposals.get_proposal(ref, budget=budget)
                    roots = tuple(m.proposed_ref for m in proposal.mutations)
                    roots += tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)
                    roots += tuple(c.owner_revision_ref for c in proposal.claim_refs)
                    from ..proposal_closure import proposal_review_revision_refs
                    roots += proposal_review_revision_refs(proposal)
                    revisions = uow.proposals.resolve_revision_graph(roots, budget)
                    owners = tuple(replace(uow.engineering.get_artifact(m.artifact_id), head_revision_id=None)
                                   for m in proposal.mutations)
                    complete.extend(self.bridge.proposal_review_requirements(snapshot, phases,
                        proposal=proposal, artifacts=owners, revisions=revisions))
                if _requirements(complete) != _requirements(intent.required_review_requirements):
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            yield
