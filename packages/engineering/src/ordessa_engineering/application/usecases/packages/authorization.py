"""Implementation intent closure on the original Proposal/baseline/method owners."""
from contextlib import contextmanager
from dataclasses import asdict, replace
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ...contracts.snapshots import EngineeringTargetBindings
from ....domain.approvals.implementation import ImplementationAuthorizationIntent
from ....domain.changes.models import ChangeSet
from ...orchestration.method_bridge import MethodBridge
from ..proposal_closure import resolve_record


def _requirements(values):
    return sorted(canonical_bytes(asdict(value)) for value in values)


def resolve_implementation_intent(uow, intent):
    """No captured intent or caller requirement list is itself permission."""
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
                    revisions = uow.proposals.resolve_revision_graph(roots, budget)
                    owners = tuple(replace(uow.engineering.get_artifact(m.artifact_id), head_revision_id=None)
                                   for m in proposal.mutations)
                    complete.extend(self.bridge.proposal_review_requirements(snapshot, phases,
                        proposal=proposal, artifacts=owners, revisions=revisions))
                if _requirements(complete) != _requirements(intent.required_review_requirements):
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            yield
