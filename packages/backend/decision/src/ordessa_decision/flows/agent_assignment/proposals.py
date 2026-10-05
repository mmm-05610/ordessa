"""Pure proposal validation and local noDelegation rule receipts."""
from datetime import datetime, timezone
from ordessa_decision.contracts import (
    ProposalDraft, ValidationObligation, ObligationResult, ValidationReceipt,
    ExternalRef, Precondition, BusinessOutcome, validate_ready, digest, ContractError,
)


def main_agent_proposal(task, policy_ref):
    """Called only after reviewed policy and explicit task boundary agree.

    This receipt attests one local boundary rule, not any external owner capability.
    """
    subject = ExternalRef('task', {'id': task.task_id, 'revision': task.task_revision})
    proposal = ProposalDraft('main-agent', 'agent.assignment/1',
        {'action': 'noDelegation', 'task_ref': subject.to_dict()},
        preconditions=(Precondition('task_revision', 'task_revision', subject,
            task.task_revision, digest('request', task), 'must', 'task_revision', '1'),),
        required_validation_obligations=(ValidationObligation('main_handling_boundary', subject,
            'must', 'local.main_handling_boundary', '1'),))
    receipt = ValidationReceipt('local.main_handling_boundary', '1', proposal.proposal_digest,
        'valid', (ObligationResult('main_handling_boundary', 'passed',
            'local.main_handling_boundary', '1', {'task_revision': task.task_revision},
            (digest('request', task), policy_ref.content_digest)),),
        datetime.now(timezone.utc).isoformat(), 'explicit_task_boundary_only')
    validate_ready(proposal, receipt, policy_refs=(policy_ref,))
    return BusinessOutcome('ready', (proposal,), (receipt,))


def ready_outcome(proposal, receipt, policy_refs):
    """Never reuse a receipt for a different payload or incomplete obligation set."""
    validate_ready(proposal, receipt, policy_refs=policy_refs)
    return BusinessOutcome('ready', (proposal,), (receipt,))


def check_proposal_basis(proposal, candidate, task, required_checks=()):
    """Decision-time hard facts also remain versioned application preconditions."""
    action = candidate.capability_claims.get('action')
    if proposal.payload.get('action') != action or not proposal.required_validation_obligations:
        raise ContractError('proposal_basis_invalid')
    if candidate.observation.observation_id not in proposal.basis_observation_ids:
        raise ContractError('proposal_basis_invalid')
    source = candidate.observation
    matched = [c for c in proposal.preconditions if c.requirement == 'must'
        and c.subject_ref == source.subject_ref and c.expected_version == source.source_version]
    if not matched:
        raise ContractError('proposal_basis_invalid')
    task_conditions = [c for c in proposal.preconditions if c.requirement == 'must'
        and c.kind == 'task_revision' and c.expected_version == task.task_revision
        and c.subject_ref.source_namespace == 'task'
        and c.subject_ref.identity.get('id') == task.task_id]
    if not task_conditions:
        raise ContractError('proposal_basis_invalid')

    conditions={c.condition_id:c for c in proposal.preconditions if c.requirement=='must'}
    for key in required_checks:
        check=candidate.capability_claims['hard_checks'][key]
        condition=conditions.get(key)
        if condition is None or condition.expected_version!=check['source_version'] or not condition.checker_id:
            raise ContractError('proposal_precondition_missing')
