"""Explicit digest and absent schema branches must not silently pass."""
from dataclasses import replace

import pytest
from ordessa_decision.definitions import (
    CandidateOffer, ContractError, ExternalRef, Precondition, ProposalDraft,
    TaskBrief, ValidationObligation, VersionedObservation, digest, plain,
)
from assignment_source.proposals import check_proposal_basis
from assignment_source.composition import check_schema


def basis():
    task = TaskBrief('task', '1', 'one synthetic result')
    subject = ExternalRef('candidate', {'id': 'c'})
    content_digest = digest('descriptor', {'capability': 'read_only'})
    observation = VersionedObservation('observation', subject, '1', content_digest,
        '2026-10-05T00:00:00Z', {'capability': 'read_only'}, 'current', evidence_refs=('source',))
    candidate = CandidateOffer(subject, 'unit', observation, {'action': 'reuse'})
    task_subject = ExternalRef('task', {'id': task.task_id, 'revision': task.task_revision})
    proposal = ProposalDraft('proposal', 'agent.assignment/1', {'action': 'reuse'},
        basis_observation_ids=('observation',),
        preconditions=(
            Precondition('task', 'task_revision', task_subject, '1', digest('request', task), 'must', 'task_revision', '1'),
            Precondition('source', 'observation_version', subject, '1', content_digest, 'must', 'observation_version', '1')),
        required_validation_obligations=(ValidationObligation('owner', subject, 'must', 'owner.read', '1'),))
    return task, candidate, proposal


@pytest.mark.parametrize('index', [0, 1])
def test_explicit_wrong_task_or_source_digest_is_rejected(index):
    task, candidate, proposal = basis()
    conditions = list(proposal.preconditions)
    conditions[index] = replace(conditions[index], expected_digest=digest('descriptor', {'wrong': 'content'}))
    with pytest.raises(ContractError):
        check_proposal_basis(replace(proposal, preconditions=tuple(conditions)), candidate, task)


def test_correct_explicit_digests_and_optional_null_are_preserved():
    task, candidate, proposal = basis()
    check_proposal_basis(proposal, candidate, task)
    check_proposal_basis(replace(proposal, preconditions=tuple(replace(c, expected_digest=None) for c in proposal.preconditions)), candidate, task)


@pytest.mark.parametrize('digest_field', ['content_digest', 'expected_digest'])
def test_hard_check_explicit_source_digest_must_match(digest_field):
    task, candidate, proposal = basis()
    subject = ExternalRef('permissions', {'id': 'read-scope'})
    check_digest = digest('descriptor', {'permission': 'read_only'})
    check = {'status': 'passed', 'subject_ref': plain(subject), 'source_version': '3',
        'checker_id': 'owner.permission', 'checker_version': '1', 'evidence_refs': ['permission-source'],
        digest_field: check_digest}
    candidate = replace(candidate, capability_claims={'action': 'reuse', 'hard_checks': {'permission': check}})
    condition = Precondition('permission', 'permission', subject, '3', check_digest, 'must', 'owner.permission', '1')
    proposal = replace(proposal, preconditions=proposal.preconditions + (condition,))
    check_proposal_basis(proposal, candidate, task, ('permission',))
    bad = replace(proposal, preconditions=proposal.preconditions[:-1] + (replace(condition, expected_digest=digest('descriptor', {'permission': 'write'})),))
    with pytest.raises(ContractError): check_proposal_basis(bad, candidate, task, ('permission',))


@pytest.mark.parametrize('value,schema', [
    ({}, {'type': 'object', 'properties': {'absent': {'type': 'string', 'pattern': '^x$'}}}),
    ([], {'type': 'array', 'items': {'type': 'number', 'multipleOf': 0.1}}),
    ({}, {'type': 'object', 'properties': {'absent': {'$schema': 'unknown', 'type': 'string'}}}),
    ([], {'type': 'array', 'items': {'type': 'unknown'}}),
    ({}, {'type': 'object', 'properties': {'absent': 7}}),
    ({}, {'type': 'object', 'required': 'absent'}),
])
def test_absent_or_empty_schema_branches_cannot_hide_unsupported_declarations(value, schema):
    assert check_schema(value, schema) == 'unverifiable'


def test_schema_cycles_and_excessive_depth_are_unverifiable():
    cycle = {'type': 'array'}; cycle['items'] = cycle
    assert check_schema([], cycle) == 'unverifiable'
    deep = {'type': 'number'}
    for _ in range(100): deep = {'type': 'array', 'items': deep}
    assert check_schema([], deep) == 'unverifiable'


def test_external_fractional_schema_and_arbitrary_field_names_remain_supported():
    schema = {'type': 'object', 'properties': {'external_ratio': {'type': 'number', 'minimum': 0.1, 'maximum': 0.9}},
        'required': ['external_ratio'], 'additionalProperties': False}
    assert check_schema({'external_ratio': 0.7}, schema) == 'valid'
    assert check_schema({'external_ratio': 0.95}, schema) == 'invalid'
    assert check_schema({}, {'type': 'object', 'properties': {'optional': {'type': 'number'}}}) == 'valid'


def test_T66_task_reference_revision_cannot_conflict_with_expected_version():
    task, candidate, proposal=basis()
    condition=replace(proposal.preconditions[0],subject_ref=ExternalRef('task',{'id':'task','revision':'999'}))
    with pytest.raises(ContractError):
        check_proposal_basis(replace(proposal,preconditions=(condition,proposal.preconditions[1])),candidate,task)


def test_T62_huge_number_in_absent_schema_branch_is_unverifiable():
    assert check_schema({}, {'type':'object','properties':{'optional':{'type':'number','minimum':10**1000}}})=='unverifiable'
