"""One exact ChangeSet effect on the original UoW, journal and budget ledger."""
from dataclasses import asdict
from contextlib import contextmanager
from uuid import uuid4
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ChangeAuthorizationIntent
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.changes.application_plan import plan_change_application, ChangeApplicationReceipt
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ..approvals.service import ApprovalUseCases
from ..proposal_closure import resolve_record
from ...contracts.snapshots import EngineeringTargetBindings


class ChangeIntentAdmission:
    """Complete Change intent closure over original method and Proposal owners.

    Bindings are injected by trusted composition; no phase list is inferred from
    the caller's requirements. The method guard remains entered through the
    consuming original UoW COMMIT, including its BEGIN-time control fences.
    """
    def __init__(self, factory, method_control, bindings):
        from ...orchestration.method_bridge import MethodBridge
        if getattr(method_control, 'factory', None) is not factory:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.bindings = factory, method_control, bindings
        self.bridge = MethodBridge()

    @contextmanager
    def guard_intent(self, context, intent):
        if type(intent) is not ChangeAuthorizationIntent:
            raise ApplicationError('INTENT_OWNER_UNAVAILABLE')
        if intent.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        resolver = getattr(self.bindings, 'resolve_intent_bindings', None)
        if not callable(resolver):
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        with self.methods.guard_method(context, intent.method_ref) as snapshot:
            complete = []
            # No resolver callback runs inside the read transaction: it may
            # itself need original business reads on the same library.
            bindings_by_proposal = tuple((ref, resolver(context, intent.method_ref, ref))
                                         for ref in intent.change_set.proposal_refs)
            with self.factory.begin(context.scope, 'read') as uow:
                resolve_change_intent(uow, intent)
                budget = uow.proposals.validated_budget()
                for ref, phases in bindings_by_proposal:
                    if (type(phases) is not tuple or not phases
                            or any(type(b) is not EngineeringTargetBindings for b in phases)
                            or len({b.phase_key for b in phases}) != len(phases)):
                        raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                    for phase in phases:
                        self.bridge.require_workflow_phase(snapshot, phase)
                    proposal = uow.proposals.get_proposal(ref, budget=budget)
                    frozen = resolve_record(proposal, uow.proposals, budget)
                    roots = tuple(m.proposed_ref for m in proposal.mutations)
                    roots += tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)
                    roots += tuple(c.owner_revision_ref for c in proposal.claim_refs)
                    revisions = uow.proposals.resolve_revision_graph(roots, budget)
                    owners = tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
                    # Bridge uses the original proposal validator, which must
                    # read create as the original create request, not adoption.
                    from dataclasses import replace
                    owners = tuple(replace(o, head_revision_id=None) for o in owners)
                    if any(b.scope != context.scope for b in phases):
                        raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                    expected = self.bridge.proposal_review_requirements(snapshot, phases,
                        proposal=proposal, artifacts=owners, revisions=revisions)
                    if _canonical_requirements(expected) != _canonical_requirements(frozen):
                        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                    complete.extend(expected)
                if _canonical_requirements(complete) != _canonical_requirements(intent.required_review_requirements):
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            yield


def _canonical_requirements(requirements):
    return sorted(canonical_bytes(asdict(r)) for r in requirements)


def resolve_change_intent(uow, intent):
    """Resolve the actual full Proposal contract, never a client's subset."""
    if type(intent) is not ChangeAuthorizationIntent:
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    # This also requires explicit schema9 rather than silently storing a new
    # action branch in an old schema8 library.
    uow.authorization.require_apply_schema()
    budget = uow.proposals.validated_budget()
    proposals = tuple(uow.proposals.get_proposal(ref, budget=budget) for ref in intent.change_set.proposal_refs)
    controls = tuple(uow.proposals.get_control(p.ref, budget=budget) for p in proposals)
    if ChangeSet(tuple(p.ref for p in proposals)) != intent.change_set or any(p.method_ref != intent.method_ref for p in proposals):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    requirements = tuple(r for p in proposals for r in resolve_record(p, uow.proposals, budget))
    # Canonical full content compares identifiers, targets, criteria, roles and
    # check keys together. Equal IDs with substituted contents do not bind.
    if sorted(canonical_bytes(asdict(r)) for r in requirements) != sorted(
            canonical_bytes(asdict(r)) for r in intent.required_review_requirements):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    targets = tuple(m.proposed_ref for p in proposals for m in p.mutations)
    if set(targets) != set(intent.targets) or len(targets) != len(intent.targets):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    roots = targets + tuple(m.base_ref for p in proposals for m in p.mutations if m.base_ref is not None)
    roots += tuple(c.owner_revision_ref for p in proposals for c in p.claim_refs)
    revisions = uow.proposals.resolve_revision_graph(roots, budget)
    ids = sorted({m.artifact_id for p in proposals for m in p.mutations})
    owners = tuple(uow.engineering.get_artifact(identifier) for identifier in ids)
    try:
        return plan_change_application(proposals, controls, owners, revisions, intent.expected_heads)
    except ReferenceError as refusal:
        raise ApplicationError(refusal.code) from refusal


class ChangeApplyUseCases(ApprovalUseCases):
    def apply(self, parameters, context, *, read_set=None):
        op = 'engineering.changes.apply'
        value, reads, digest = self._input(op, parameters, context, read_set)
        try:
            ref = decode_approval_ref(value['approval_ref'])
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        with self.factory.begin(context.scope, 'read') as uow:
            grant = uow.authorization.get_grant(ref)
            control = uow.authorization.get_control(ref)
        intent = grant.intent
        if type(intent) is not ChangeAuthorizationIntent:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        if control['state'] != 'granted':
            raise ApplicationError('AUTHORIZATION_REVOKED')
        def mutate(uow):
            if uow.authorization.get_grant(ref) != grant or uow.authorization.get_control(ref) != control:
                raise ApplicationError('AUTHORIZATION_REVOKED')
            plan = self._resolve(uow, intent)
            self._check_gates(uow, decisions)
            action_id = str(uuid4())  # Original application generates the identity.
            uow.authorization.consume_action(ref, action='apply_change', action_instance_id=action_id,
                target_digest=intent.change_set.digest, now=context.received_at)
            uow.engineering.apply_head_plan(plan)
            receipt = ChangeApplicationReceipt(context.scope, str(uuid4()), action_id, ref, intent.digest,
                intent.change_set, plan.mutations,
                tuple(sorted({r for d in decisions for r in d.used_review_refs}, key=lambda r: canonical_bytes(asdict(r)))),
                control['version'], context.received_at)
            uow.authorization.put_apply(receipt)
            return {'state': 'APPLIED', 'apply_receipt': asdict(receipt),
                    'target_baseline_refs': [asdict(m.proposed_ref) for m in plan.mutations]}
        with self._admission().guard_intent(context, intent), self._gates(context, intent) as decisions:
            return self._run(op, context, reads, digest, mutate)
