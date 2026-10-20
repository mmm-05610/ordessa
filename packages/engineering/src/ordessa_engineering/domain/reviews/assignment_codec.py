"""Closed Agent assignment v2 and exact read-only historical Unit bytes."""
from dataclasses import asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import canonical_value,decode_scope,decode_digest,require_object
from ..common.outcomes.diagnostics import ReferenceError
from ..artifacts.method_codec import decode_method_ref
from .assignments import ReviewerAssignment,HistoricalReviewerAssignment

COMMON={'scope','assignment_id','review_id','plan_digest','request_version','fence','method_ref',
        'roles','issuer_principal_id','issuer_credential_epoch','assigned_at','digest'}


def encode_reviewer_assignment(record):
    if type(record) is not ReviewerAssignment:raise ReferenceError('AGENT_REVIEWER_ASSIGNMENT_REQUIRED')
    raw=canonical_bytes({**record.hash_payload(),'digest':asdict(record.digest)})
    if len(raw)>262144:raise ReferenceError('REVIEWER_ASSIGNMENT_BOUND_EXCEEDED')
    return raw


def encode_historical_reviewer_assignment(record):
    if type(record) is not HistoricalReviewerAssignment:raise ReferenceError('HISTORICAL_ASSIGNMENT_REQUIRED')
    return canonical_bytes({**record.hash_payload(),'digest':asdict(record.digest)})


def decode_reviewer_assignment(raw):
    value=canonical_value(raw,maximum=262144)
    if type(value) is not dict:raise ReferenceError('INVALID_REVIEWER_ASSIGNMENT')
    current='schemaVersion' in value
    if current:
        require_object(value,COMMON|{'schemaVersion','reviewer_agent_ref','author_agent_ref'},'INVALID_REVIEWER_ASSIGNMENT')
        if value['schemaVersion']!='engineering-agent-reviewer-assignment/2':raise ReferenceError('INVALID_REVIEWER_ASSIGNMENT_VERSION')
        kind=ReviewerAssignment;reviewer=value['reviewer_agent_ref'];author=value['author_agent_ref']
    else:
        require_object(value,COMMON|{'reviewer_unit_ref','author_unit_ref'},'INVALID_REVIEWER_ASSIGNMENT')
        kind=HistoricalReviewerAssignment;reviewer=value['reviewer_unit_ref'];author=value['author_unit_ref']
    if type(value['roles']) is not list:raise ReferenceError('INVALID_REVIEWER_ASSIGNMENT')
    record=kind(decode_scope(value['scope']),value['assignment_id'],value['review_id'],decode_digest(value['plan_digest']),
        value['request_version'],value['fence'],decode_method_ref(value['method_ref']),canonical_bytes(reviewer),
        None if author is None else canonical_bytes(author),tuple(value['roles']),value['issuer_principal_id'],
        value['issuer_credential_epoch'],value['assigned_at'])
    encoded=encode_reviewer_assignment(record) if current else encode_historical_reviewer_assignment(record)
    if record.digest!=decode_digest(value['digest']) or encoded!=raw:raise ReferenceError('INVALID_REVIEWER_ASSIGNMENT')
    return record
