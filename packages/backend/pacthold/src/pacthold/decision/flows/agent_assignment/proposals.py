"""Pure proposal validation and local noDelegation rule receipts."""
from datetime import datetime, timezone
from pacthold.decision.contracts import (
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


def check_proposal_basis(proposal, candidate, task, required_checks=(), required_validation=()):
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

    # A declared content digest is evidence, not an unchecked display field.
    # Null remains permitted where the frozen source only supplies a revision.
    task_digest = digest('request', task)
    for condition in task_conditions:
        if 'revision' in condition.subject_ref.identity and condition.subject_ref.identity['revision'] != task.task_revision:
            raise ContractError('proposal_task_revision_mismatch')
        if condition.expected_digest is not None and condition.expected_digest != task_digest:
            raise ContractError('proposal_task_digest_mismatch')
    for condition in matched:
        if condition.expected_digest is not None and condition.expected_digest != source.content_digest:
            raise ContractError('proposal_source_digest_mismatch')

    if len({c.condition_id for c in proposal.preconditions}) != len(proposal.preconditions):
        raise ContractError('duplicate_precondition')
    for required in required_validation:
        covered=any(o.requirement=='must' and o.subject_ref==source.subject_ref
            and o.validator_kind==required['validator_kind']
            and o.version_constraint==required['version_constraint']
            for o in proposal.required_validation_obligations)
        if not covered:
            raise ContractError('mandatory_semantic_obligation_missing')
    conditions={c.condition_id:c for c in proposal.preconditions if c.requirement=='must'}
    digest_bound = {c.condition_id for c in task_conditions + matched}
    for key in required_checks:
        check=candidate.capability_claims['hard_checks'][key]
        condition=conditions.get(key)
        subject=ExternalRef.from_dict(check['subject_ref'])
        if (condition is None or condition.expected_version!=check['source_version']
                or condition.subject_ref!=subject or condition.checker_id!=check['checker_id']
                or condition.checker_version!=check['checker_version']):
            raise ContractError('proposal_precondition_missing')
        declared = [check[field] for field in ('content_digest', 'expected_digest') if check.get(field) is not None]
        if declared:
            if any(type(value) is not str or not value for value in declared) or len(set(declared)) != 1 or condition.expected_digest != declared[0]:
                raise ContractError('proposal_check_digest_mismatch')
            digest_bound.add(condition.condition_id)
    if any(c.expected_digest is not None and c.condition_id not in digest_bound for c in conditions.values()):
        # No contract here defines the content behind an arbitrary checker.
        raise ContractError('proposal_digest_source_unknown')
