"""Read explicit review subjects/materials from the original Engineering library.

Selection is a normal method/work input. No latest-subject scan, identity
authority, workflow state or client-supplied ReviewPlan is introduced here.
"""
from dataclasses import dataclass

from ....application.contracts.errors import ApplicationError
from ....application.contracts.snapshots import EngineeringTargetBindings
from ....application.orchestration.method_content import document_type_for_payload
from ....application.usecases.proposal_closure import resolve_record
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.changes.refs import ProposalRef
from ....domain.reviews.refs import SubmissionRef
from ....domain.reviews.targets import Target, TargetSet


@dataclass(frozen=True)
class ConfiguredReviewPhase:
    phase_key: str
    eligible_reviewer_roles: tuple[str, ...]
    material_inputs: tuple[tuple[str, ArtifactRevisionRef], ...] = ()
    workflow_node_id: str | None = None
    targets: TargetSet | None = None
    submission_ref: SubmissionRef | None = None
    review_purpose: str | None = None


class SQLiteReviewBindings:
    def __init__(self, factory, method_control, *, scope, proposal_ref, phases):
        if (getattr(method_control, 'factory', None) is not factory
                or type(proposal_ref) is not ProposalRef
                or (proposal_ref.realm_id, proposal_ref.project_id) != (scope.realm_id, scope.project_id)
                or type(phases) is not tuple or not phases
                or any(type(p) is not ConfiguredReviewPhase for p in phases)
                or len({p.phase_key for p in phases}) != len(phases)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        self.factory, self.methods = factory, method_control
        self.scope, self.proposal_ref, self.phases = scope, proposal_ref, phases

    def _phase(self, phase_key):
        matches = tuple(p for p in self.phases if p.phase_key == phase_key)
        if len(matches) != 1:
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        return matches[0]

    def _bind(self, context, snapshot, proposal, phase, uow):
        nodes = tuple(n for n in snapshot.program.workflow.steps if n.id == phase.phase_key)
        if (len(nodes) != 1 or getattr(nodes[0], 'operation', None) != 'engineering.reviews.request'
                or phase.workflow_node_id != phase.phase_key):
            raise ApplicationError('METHOD_PHASE_BINDING_MISMATCH')
        if (type(phase.material_inputs) is not tuple or any(type(pair) is not tuple
                or len(pair) != 2 or type(pair[0]) is not str
                or type(pair[1]) is not ArtifactRevisionRef for pair in phase.material_inputs)):
            raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
        names = ('proposal_ref',) + tuple(name for name, _ in phase.material_inputs)
        if len(set(names)) != len(names):
            raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
        for _, ref in phase.material_inputs:
            uow.engineering.resolve_revision(ref)
        targets = phase.targets
        if targets is None:
            if phase.submission_ref is None:
                targets = TargetSet(tuple(Target('proposed', m.proposed_ref) for m in proposal.mutations))
            else:
                submission = uow.submissions.resolve(phase.submission_ref)
                if proposal.ref not in submission.change_set.proposal_refs:
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                targets = TargetSet(tuple(Target('output', ref) for ref in submission.output_refs
                                          if type(ref) is ArtifactRevisionRef))
        if type(targets) is not TargetSet:
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        labels = []
        for target in targets.targets:
            if type(target.ref) is not ArtifactRevisionRef:
                raise ApplicationError('METHOD_SUBJECT_OWNER_UNAVAILABLE')
            revision = uow.engineering.resolve_revision(target.ref)
            labels.append((target, document_type_for_payload(snapshot, revision.payload)))
        return EngineeringTargetBindings(context.scope, targets, tuple(labels), names,
            phase.eligible_reviewer_roles, phase.phase_key,
            workflow_node_id=phase.workflow_node_id, review_purpose=phase.review_purpose)

    def _resolve(self, context, method_ref):
        if context.scope != self.scope:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self.methods.guard_method(context, method_ref) as snapshot:
            with self.factory.begin(context.scope, 'read') as uow:
                budget = uow.proposals.validated_budget()
                proposal = uow.proposals.get_proposal(self.proposal_ref, budget=budget)
                if proposal.method_ref != method_ref:
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                resolve_record(proposal, uow.proposals, budget)
                return tuple(self._bind(context, snapshot, proposal, phase, uow) for phase in self.phases)

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        if proposal_ref != self.proposal_ref:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        return tuple(b for b in self._resolve(context, method_ref)
                     if self._phase(b.phase_key).submission_ref is None)

    def resolve_bindings(self, context, method_ref, phase_key):
        self._phase(phase_key)
        return next(b for b in self._resolve(context, method_ref) if b.phase_key == phase_key)

    def resolve_review_proposal(self, context, method_ref, phase_key):
        self.resolve_bindings(context, method_ref, phase_key)
        return None if self._phase(phase_key).submission_ref is not None else self.proposal_ref

    def resolve_review_submission(self, context, method_ref, phase_key):
        self.resolve_bindings(context, method_ref, phase_key)
        return self._phase(phase_key).submission_ref

    def resolve_submission_bindings(self, context, method_ref, submission_ref):
        matches = tuple(b for b in self._resolve(context, method_ref)
            if self._phase(b.phase_key).submission_ref == submission_ref)
        if not matches or any(b.review_purpose != 'acceptance' for b in matches):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        return matches

    def resolve_acceptance_submission(self, context, intent):
        """Select the one explicit configured acceptance subject, never latest."""
        if context.scope!=self.scope or intent.scope!=self.scope:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        selected={phase.submission_ref for phase in self.phases
                  if phase.submission_ref is not None and phase.review_purpose=='acceptance'}
        if len(selected)!=1:
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        ref=next(iter(selected))
        self.resolve_submission_bindings(context,intent.method_ref,ref)
        with self.factory.begin(context.scope,'read') as uow:
            submission=uow.submissions.resolve(ref)
            package=uow.implementation.resolve_package(submission.package_ref)
            if (package.payload.method_ref!=intent.method_ref
                    or set(intent.targets)!=set(submission.output_refs)
                    or len(intent.targets)!=len(submission.output_refs)):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        return ref

    def material_inputs(self, context, method_ref, phase_key):
        """Exact named immutable inputs; no slot label is treated as a value."""
        self.resolve_bindings(context, method_ref, phase_key)
        phase = self._phase(phase_key)
        with self.factory.begin(context.scope, 'read') as uow:
            return tuple((name, uow.engineering.resolve_revision(ref))
                         for name, ref in phase.material_inputs)


__all__ = ['ConfiguredReviewPhase', 'SQLiteReviewBindings']
