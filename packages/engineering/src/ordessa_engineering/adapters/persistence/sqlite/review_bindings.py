"""Read explicit review subjects/materials from the original Engineering library.

Selection is a normal method/work input. No latest-subject scan, identity
authority, workflow state or client-supplied ReviewPlan is introduced here.
"""
from dataclasses import dataclass
import threading

from ....application.contracts.errors import ApplicationError
from ....application.contracts.commands import CommandContext
from ....application.contracts.snapshots import EngineeringTargetBindings, ResolvedReviewMaterial
from ....application.orchestration.method_content import document_type_for_payload
from ....application.usecases.proposal_closure import resolve_record
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.changes.refs import ProposalRef
from ....domain.common.models.identity import Scope
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
        unbound = proposal_ref is None and phases is None
        if (getattr(method_control, 'factory', None) is not factory
                or type(scope) is not Scope
                or not (unbound or self._valid_selection(proposal_ref, phases, scope))):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        self._selection_lock = threading.RLock()
        self.factory, self.methods = factory, method_control
        self.scope = scope
        self._selection_value = None if unbound else (proposal_ref, phases)

    @property
    def proposal_ref(self):
        with self._selection_lock:
            selection = self._selection_value
            return None if selection is None else selection[0]

    @property
    def phases(self):
        with self._selection_lock:
            selection = self._selection_value
            return None if selection is None else selection[1]

    @staticmethod
    def _valid_selection(proposal_ref, phases, scope):
        return (type(proposal_ref) is ProposalRef
                and (proposal_ref.realm_id, proposal_ref.project_id) == (scope.realm_id, scope.project_id)
                and type(phases) is tuple and bool(phases)
                and all(type(p) is ConfiguredReviewPhase for p in phases)
                and all(type(p.phase_key) is str and p.phase_key for p in phases)
                and len({p.phase_key for p in phases}) == len(phases))

    def _selection(self):
        with self._selection_lock:
            selection = self._selection_value
            if selection is None:
                raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
            return selection

    def bind_selection(self, context, *, proposal_ref, phases):
        """Bind one explicit selection after validating it against original owners.

        The instance remains unbound on every failure. This performs reads only;
        it does not grant access, persist a selection, or infer a latest proposal.
        """
        if (type(context) is not CommandContext or context.scope != self.scope
                or not self._valid_selection(proposal_ref, phases, self.scope)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self._selection_lock:
            if self._selection_value is not None:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        # Never hold the selection mutex while acquiring the library or method
        # guard: review admission can hold an original owner guard while reading
        # this selection. Validate outside, then publish with a short CAS below.
        with self.factory.begin(context.scope, 'read') as uow:
            budget = uow.proposals.validated_budget()
            proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
            method_ref = proposal.method_ref
        self._resolve_selection(context, method_ref, proposal_ref, phases)
        with self._selection_lock:
            if self._selection_value is not None:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            self._selection_value = (proposal_ref, phases)

    def _resolve_selection(self, context, method_ref, proposal_ref, phases):
        if type(context) is not CommandContext or context.scope != self.scope:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self.methods.guard_method(context, method_ref) as snapshot:
            with self.factory.begin(context.scope, 'read') as uow:
                budget = uow.proposals.validated_budget()
                proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
                if proposal.method_ref != method_ref:
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                resolve_record(proposal, uow.proposals, budget)
                return tuple(self._bind(context, snapshot, proposal, phase, uow) for phase in phases)

    def _phase(self, phase_key):
        _, phases = self._selection()
        matches = tuple(p for p in phases if p.phase_key == phase_key)
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
        proposal_ref, phases = self._selection()
        return self._resolve_selection(context, method_ref, proposal_ref, phases)

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        selected, _ = self._selection()
        if proposal_ref != selected:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        return tuple(b for b in self._resolve(context, method_ref)
                     if self._phase(b.phase_key).submission_ref is None)

    def resolve_bindings(self, context, method_ref, phase_key):
        self._phase(phase_key)
        return next(b for b in self._resolve(context, method_ref) if b.phase_key == phase_key)

    def resolve_review_proposal(self, context, method_ref, phase_key):
        self.resolve_bindings(context, method_ref, phase_key)
        proposal_ref, _ = self._selection()
        return None if self._phase(phase_key).submission_ref is not None else proposal_ref

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
        proposal_ref, phases = self._selection()
        if context.scope!=self.scope or intent.scope!=self.scope:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        selected={phase.submission_ref for phase in phases
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

    def resolve_plan_bindings(self, context, plan):
        """Resolve the exact configured phase through its original selection.

        This is the plan-aware delivery port, not a persisted Work selector.
        The admission owner independently checks the full Proposal closure.
        """
        from ....domain.reviews.models import ReviewPlan
        if type(plan) is not ReviewPlan or plan.scope != context.scope:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        return self.resolve_bindings(context, plan.requirement.method_ref,
                                     plan.requirement.phase_key)

    def material_inputs_for_plan(self, context, plan):
        """Project configured immutable artifacts into typed named materials."""
        from ....domain.artifacts.models import InlinePayload, MethodPayload
        from ordessa_infrastructure.encoding import canonical_bytes
        self.resolve_plan_bindings(context, plan)
        result = []
        for name, revision in self.material_inputs(
                context, plan.requirement.method_ref, plan.requirement.phase_key):
            if type(revision.payload) is MethodPayload:
                value = revision.payload.content.value
            elif type(revision.payload) is InlinePayload:
                value = revision.payload.value
            else:
                raise ApplicationError('DECISION_INPUT_BINDING_UNAVAILABLE')
            result.append(ResolvedReviewMaterial(name, revision.ref, 'method_content',
                                                canonical_bytes(value)))
        return tuple(result)


__all__ = ['ConfiguredReviewPhase', 'SQLiteReviewBindings']
