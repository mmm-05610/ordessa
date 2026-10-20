"""Explicit Agent report review facts; no role, send or approval authority.

Historical Artifact delivery contracts retain their original shape and bytes.
Locators identify evidence to reread through the original owners; a caller's
well-formed locator does not authenticate either author or reviewer.
"""
from dataclasses import dataclass

from ordessa_infrastructure.encoding import canonical_bytes
from ...domain.artifacts.method_binding import MethodRef
from ...domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ...domain.common.mechanisms.codec import (decode_blob_ref, decode_digest,
    decode_scope, projection, require_object)
from ...domain.common.models.execution_refs import agent_instance_identity, read_agent_instance_ref
from ...domain.common.models.identity import Scope
from ...domain.common.models.refs import BlobRef
from ...domain.common.models.values import Digest, validate_version
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.reviews.assignments import ReviewerAssignmentRef
from ...domain.reviews.refs import SubmissionRef

AUTHORSHIP_CONTRACT = 'engineering-agent-report-authorship/1'
LOCATOR_CONTRACT = 'ordessa.declared-agent-report-review-source/1'
CAPABILITY = 'engineering.reviewer.agent'
INTERFACE_VERSION = '1'
RESPONSE_SCHEMA = {'type':'object','additionalProperties':False,
    'required':['verdict','rationale','findings'], 'properties':{
        'verdict':{'enum':['passed','rejected','cancelled','unknown']},
        'rationale':{'type':'string','minLength':1},
        'findings':{'type':'array','items':{'type':'string'}}}}
AGENT_REPORT_REVIEW_CONTRACT = {
    'schemaVersion':'ordessa.agent-report-review-contract/1',
    'capabilityId':CAPABILITY, 'interfaceVersion':INTERFACE_VERSION,
    'authorshipContract':AUTHORSHIP_CONTRACT, 'locatorContract':LOCATOR_CONTRACT,
    'submissionContract':'engineering-agent-submission-report/1',
    'executionContract':'engineering-agent-execution-ref/2',
    'targetKind':'persisted-submission', 'criterionResourceId':'implementation-review-criteria',
    'promptResourceId':'independent-review-prompt',
    'profileSelectionResourceId':'profile-selection-prompt',
    'identityConstraint':'original_author_agent_identity_must_differ_from_original_reviewer_agent_identity',
    'requiredTerminalState':'completed', 'requiredStopReason':'end_turn',
    'readOnly':True, 'responseSchema':RESPONSE_SCHEMA,
}


def _scope_ref(scope, ref):
    if type(scope) is not Scope or type(ref) is not SubmissionRef or (
            ref.realm_id, ref.project_id) != (scope.realm_id, scope.project_id):
        raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')


def _blob(ref):
    if type(ref) is not BlobRef or ref.media_type != 'application/json' or ref.byte_length > 2*1024*1024:
        raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')


def _execution(value):
    required={'schemaVersion','agent_ref_bytes','turn_ref_bytes','source_revision',
        'operation_ref','engineering_attempt_ref','prompt_input_digest','query_digest','captured_observation_ref'}
    require_object(value, required, 'INVALID_AGENT_REPORT_REVIEW')
    if value['schemaVersion'] != 'engineering-agent-execution-ref/2':
        raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')
    return AgentExecutionRecordRef(canonical_bytes(value['agent_ref_bytes']),canonical_bytes(value['turn_ref_bytes']),
        value['source_revision'],value['operation_ref'],value['engineering_attempt_ref'],
        decode_digest(value['prompt_input_digest']),value['query_digest'],decode_blob_ref(value['captured_observation_ref']))


@dataclass(frozen=True)
class AgentReportAuthorship:
    scope: Scope
    method_ref: MethodRef
    submission_ref: SubmissionRef
    author_execution_ref: AgentExecutionRecordRef
    report_blob_ref: BlobRef

    def __post_init__(self):
        _scope_ref(self.scope,self.submission_ref); _blob(self.report_blob_ref)
        if type(self.method_ref) is not MethodRef or type(self.author_execution_ref) is not AgentExecutionRecordRef:
            raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')

    def projection(self):
        return {'schemaVersion':AUTHORSHIP_CONTRACT, 'scope':projection(self.scope),
            'method_ref':projection(self.method_ref), 'submission_ref':projection(self.submission_ref),
            'author_execution_ref':self.author_execution_ref.projection(),
            'report_blob_ref':projection(self.report_blob_ref)}


@dataclass(frozen=True)
class AgentReportReviewLocator:
    scope: Scope
    plan_digest: Digest
    request_version: int
    fence: int
    assignment_ref: ReviewerAssignmentRef
    submission_ref: SubmissionRef
    author_execution_ref: AgentExecutionRecordRef
    report_blob_ref: BlobRef
    reviewer_execution_ref: AgentExecutionRecordRef
    params_ref: BlobRef

    def __post_init__(self):
        _scope_ref(self.scope,self.submission_ref); _blob(self.report_blob_ref); _blob(self.params_ref)
        validate_version(self.request_version); validate_version(self.fence,positive=True)
        if (type(self.plan_digest) is not Digest or type(self.assignment_ref) is not ReviewerAssignmentRef
                or self.assignment_ref.scope != self.scope
                or type(self.author_execution_ref) is not AgentExecutionRecordRef
                or type(self.reviewer_execution_ref) is not AgentExecutionRecordRef):
            raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')
        author=read_agent_instance_ref(self.author_execution_ref.agent_ref_bytes)
        reviewer=read_agent_instance_ref(self.reviewer_execution_ref.agent_ref_bytes)
        if agent_instance_identity(author)==agent_instance_identity(reviewer):
            raise ReferenceError('UNTRUSTED_REVIEWER')

    def projection(self):
        value={name:projection(getattr(self,name)) for name in (
            'scope','plan_digest','request_version','fence','assignment_ref','submission_ref','report_blob_ref','params_ref')}
        return {'schemaVersion':LOCATOR_CONTRACT, **value,
            'author_execution_ref':self.author_execution_ref.projection(),
            'reviewer_execution_ref':self.reviewer_execution_ref.projection()}

    @classmethod
    def from_projection(cls,value):
        keys={'schemaVersion','scope','plan_digest','request_version','fence','assignment_ref','submission_ref',
            'report_blob_ref','params_ref','author_execution_ref','reviewer_execution_ref'}
        require_object(value,keys,'INVALID_AGENT_REPORT_REVIEW')
        if value['schemaVersion'] != LOCATOR_CONTRACT or len(canonical_bytes(value))>65536:
            raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')
        assignment=value['assignment_ref']
        require_object(assignment,{'scope','assignment_id','digest'},'INVALID_AGENT_REPORT_REVIEW')
        ref=ReviewerAssignmentRef(decode_scope(assignment['scope']),assignment['assignment_id'],decode_digest(assignment['digest']))
        submission=value['submission_ref']
        require_object(submission,{'realm_id','project_id','submission_id','digest','kind'},'INVALID_AGENT_REPORT_REVIEW')
        if submission['kind'] != 'submission':raise ReferenceError('INVALID_AGENT_REPORT_REVIEW')
        submission_ref=SubmissionRef(submission['realm_id'],submission['project_id'],submission['submission_id'],decode_digest(submission['digest']))
        return cls(decode_scope(value['scope']),decode_digest(value['plan_digest']),value['request_version'],value['fence'],
            ref,submission_ref,_execution(value['author_execution_ref']),
            decode_blob_ref(value['report_blob_ref']),_execution(value['reviewer_execution_ref']),decode_blob_ref(value['params_ref']))
