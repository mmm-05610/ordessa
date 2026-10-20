"""Read one trusted work selection from the original Engineering authority.

The exact ProposalRef and complete phase configuration are deployment/work
inputs. This port has no head table, SQL scan, client-plan inference or method
selection fallback. Material labels come only from released method schemas.
"""
from dataclasses import dataclass

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_content import document_type_for_payload
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet


@dataclass(frozen=True)
class ConfiguredReviewPhase:
    phase_key: str
    eligible_reviewer_roles: tuple[str, ...]
    material_inputs: tuple[tuple[str, ArtifactRevisionRef], ...] = ()
    workflow_node_id: str | None = None


class OriginalProposalBindings:
    def __init__(self, factory, methods, *, scope, proposal_ref, phases):
        if (getattr(methods, 'factory', None) is not factory
                or type(proposal_ref) is not ProposalRef
                or (proposal_ref.realm_id, proposal_ref.project_id) != (scope.realm_id, scope.project_id)
                or type(phases) is not tuple or not phases
                or any(type(p) is not ConfiguredReviewPhase for p in phases)
                or len({p.phase_key for p in phases}) != len(phases)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        self.factory, self.methods = factory, methods
        self.scope, self.proposal_ref, self.phases = scope, proposal_ref, phases

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        if context.scope != self.scope or proposal_ref != self.proposal_ref:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self.methods.guard_method(context, method_ref) as snapshot:
            with self.factory.begin(context.scope, 'read') as uow:
                budget = uow.proposals.validated_budget()
                proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
                if proposal.method_ref != method_ref:
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                resolve_record(proposal, uow.proposals, budget)
                targets = TargetSet(tuple(Target('proposed', m.proposed_ref) for m in proposal.mutations))
                labels = tuple((t, document_type_for_payload(snapshot,
                    uow.engineering.resolve_revision(t.ref).payload)) for t in targets.targets)
                result = []
                for phase in self.phases:
                    if (phase.workflow_node_id is not None
                            and (type(phase.workflow_node_id) is not str
                                or phase.phase_key != phase.workflow_node_id)):
                        raise ApplicationError('METHOD_PHASE_BINDING_MISMATCH')
                    if 'workflow_node_id' not in EngineeringTargetBindings.__dataclass_fields__:
                        raise ApplicationError('METHOD_PHASE_AUTHORITY_UNAVAILABLE')
                    # Every configured input must resolve in the original scope.
                    # A string slot declaration alone never establishes a value.
                    inputs = ('proposal_ref',)
                    if (type(phase.material_inputs) is not tuple
                            or any(type(pair) is not tuple or len(pair) != 2
                                or type(pair[0]) is not str or type(pair[1]) is not ArtifactRevisionRef
                                for pair in phase.material_inputs)):
                        raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
                    for name, ref in phase.material_inputs:
                        uow.engineering.resolve_revision(ref)
                        inputs += (name,)
                    if len(set(inputs)) != len(inputs):
                        raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
                    result.append(EngineeringTargetBindings(context.scope, targets, labels,
                        inputs, phase.eligible_reviewer_roles, phase.phase_key,
                        workflow_node_id=phase.workflow_node_id))
                return tuple(result)

    def resolve_bindings(self, context, method_ref, phase_key):
        matches = tuple(b for b in self.resolve_intent_bindings(context, method_ref, self.proposal_ref)
            if b.phase_key == phase_key)
        if len(matches) != 1:
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        return matches[0]

    def resolve_review_proposal(self, context, method_ref, phase_key):
        # Independent trusted work selection; never parse an expanded ID or
        # infer its owner from a submitted ReviewRequirement.
        self.resolve_bindings(context, method_ref, phase_key)
        return self.proposal_ref
