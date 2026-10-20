"""Closed canonical Submission codec; recomputes rather than trusts record identity."""
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..common.mechanisms.codec import (canonical_value, require_object, decode_digest,
    decode_scope, decode_actor, decode_blob_ref, decode_tuple, projection)
from ..common.models.refs import BlobRef
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.ref_codec import decode_approval_ref
from ..artifacts.ref_codec import decode_artifact_ref
from ..artifacts.method_codec import decode_exact_method_resource
from ..artifacts.models import MethodContent
from ..artifacts.provenance_codec import decode_source
from ..changes.ref_codec import decode_proposal_ref
from ..changes.baseline_codec import decode_repository_ref
from ..changes.models import ChangeSet
from ..packages.codec import decode_package_ref
from .submission import (Submission, ExecutionRecordRef, CommitRef, FileChange,
    TestEvidence, EffectTargetRef, EffectObservation, SubmissionCoverage)
from .agent_execution_ref import AgentExecutionRecordRef
from .agent_submission_report import AgentSubmissionReport, AGENT_SUBMISSION_REPORT_VERSION

MAX_SUBMISSION_BYTES = 2 * 1024 * 1024
_CODE = 'INVALID_SUBMISSION'


def _execution_projection(value):
    result = projection(value)
    result['owner_provider_ref_bytes'] = decode_json(value.owner_provider_ref_bytes)
    return result


def _output_projection(value):
    if type(value) is BlobRef:
        return {'kind':'blob', **asdict(value)}
    return asdict(value)


def _coverage_projection(value):
    result = projection(value)
    result['output_refs'] = [_output_projection(x) for x in value.output_refs]
    result['evidence_refs'] = [_output_projection(x) for x in value.evidence_refs]
    return result


def _test_projection(value):
    result = projection(value)
    result['execution_ref'] = _execution_projection(value.execution_ref)
    return result


def submission_projection(value):
    if type(value) is AgentSubmissionReport:
        body = value.hash_payload()
        body.update({name: projection(getattr(value, name)) for name in (
            'authorization_refs', 'package_ref', 'source_refs', 'checkpoint_ref')})
        body['execution_ref'] = value.execution_ref.projection()
        body['output_refs'] = [_output_projection(x) for x in value.output_refs]
        body['coverage'] = [_coverage_projection(x) for x in value.coverage]
        body['change_set'] = {'proposal_refs': [asdict(x) for x in value.change_set.proposal_refs],
                              'digest': asdict(value.change_set.digest)}
        body['method_content'] = value.method_content.projection()
        body['digest'] = asdict(value.digest)
        return body
    if type(value) is not Submission:
        raise ReferenceError(_CODE)
    body = value.hash_payload()
    # Persist exact opaque blob locations alongside identity digest semantics.
    body.update({name: projection(getattr(value, name)) for name in (
        'authorization_refs','package_ref','execution_ref','baseline_snapshots','resulting_snapshots',
        'commit_refs','file_changes','effect_observations','source_refs','checkpoint_ref')})
    body['test_evidence'] = [_test_projection(x) for x in value.test_evidence]
    body['output_refs'] = [_output_projection(x) for x in value.output_refs]
    body['coverage'] = [_coverage_projection(x) for x in value.coverage]
    body['change_set'] = {'proposal_refs':[asdict(x) for x in value.change_set.proposal_refs], 'digest':asdict(value.change_set.digest)}
    if value.execution_ref is not None:
        body['execution_ref'] = _execution_projection(value.execution_ref)
    if value.method_content is not None:
        body['method_content'] = value.method_content.projection()
    body['digest'] = asdict(value.digest)
    return body


def encode_submission(value: Submission | AgentSubmissionReport) -> bytes:
    raw = canonical_bytes(submission_projection(value))
    if len(raw) > MAX_SUBMISSION_BYTES:
        raise ReferenceError('SUBMISSION_TOO_LARGE')
    return raw


def _tuple(v, parser):
    return decode_tuple(v, parser, _CODE)


def _execution(v):
    require_object(v, {'environment_namespace','unit_id','owner_provider_ref_bytes','source_revision','operation_ref','prompt_input_digest','captured_observation_ref'}, _CODE)
    owner_bytes = canonical_bytes(v['owner_provider_ref_bytes'])
    return ExecutionRecordRef(v['environment_namespace'],v['unit_id'],owner_bytes,v['source_revision'],v['operation_ref'],decode_digest(v['prompt_input_digest']),decode_blob_ref(v['captured_observation_ref']))


def _changeset(v):
    require_object(v, {'proposal_refs','digest'}, _CODE)
    value = ChangeSet(_tuple(v['proposal_refs'],decode_proposal_ref))
    if value.digest != decode_digest(v['digest']): raise ReferenceError(_CODE)
    return value


def _commit(v):
    require_object(v, {'repository_id','commit_id','tree_digest'}, _CODE)
    return CommitRef(v['repository_id'],v['commit_id'],decode_digest(v['tree_digest']))


def _file_change(v):
    require_object(v, {'change_id','repository_id','normalized_path','operation','before_blob_digest','after_blob_digest','rename_from','proposal_refs'}, _CODE)
    return FileChange(v['change_id'],v['repository_id'],v['normalized_path'],v['operation'],None if v['before_blob_digest'] is None else decode_digest(v['before_blob_digest']),None if v['after_blob_digest'] is None else decode_digest(v['after_blob_digest']),v['rename_from'],_tuple(v['proposal_refs'],decode_proposal_ref))


def _test(v):
    require_object(v, {'check_id','requirement_id','subject_snapshot','execution_ref','result','observation_ref','tool_version','measured_at'}, _CODE)
    return TestEvidence(v['check_id'],v['requirement_id'],decode_repository_ref(v['subject_snapshot']),_execution(v['execution_ref']),v['result'],decode_blob_ref(v['observation_ref']),v['tool_version'],v['measured_at'])


def _effect(v):
    require_object(v, {'effect_id','action','target_ref','observed_state','evidence_refs','reversible','compensation_ref'}, _CODE)
    require_object(v['target_ref'], {'target_id','constraint_digest'}, _CODE)
    target = EffectTargetRef(v['target_ref']['target_id'],decode_digest(v['target_ref']['constraint_digest']))
    return EffectObservation(v['effect_id'],v['action'],target,v['observed_state'],_tuple(v['evidence_refs'],decode_blob_ref),v['reversible'],None if v['compensation_ref'] is None else decode_blob_ref(v['compensation_ref']))


def _output(v):
    if type(v) is not dict: raise ReferenceError(_CODE)
    if v.get('kind') == 'blob':
        require_object(v, {'kind','digest','byte_length','media_type','storage_object_id'}, _CODE)
        return decode_blob_ref({k:v[k] for k in ('digest','byte_length','media_type','storage_object_id')})
    return decode_artifact_ref(v)


def _coverage(v):
    require_object(v, {'proposal_ref','output_refs','file_change_ids','evidence_refs','disposition','reason'}, _CODE)
    return SubmissionCoverage(decode_proposal_ref(v['proposal_ref']),_tuple(v['output_refs'],_output),_tuple(v['file_change_ids'], lambda item: item),_tuple(v['evidence_refs'],_output),v['disposition'],v['reason'])


def _content(v):
    if v is None: return None
    require_object(v, {'schema_ref','value','rendered_body_ref'}, _CODE)
    return MethodContent.from_value(decode_exact_method_resource(v['schema_ref']),v['value'],None if v['rendered_body_ref'] is None else decode_blob_ref(v['rendered_body_ref']))


def _agent_execution(v):
    require_object(v, {'schemaVersion','agent_ref_bytes','turn_ref_bytes','source_revision',
        'operation_ref','engineering_attempt_ref','prompt_input_digest','query_digest',
        'captured_observation_ref'}, _CODE)
    if v['schemaVersion'] != 'engineering-agent-execution-ref/2':
        raise ReferenceError(_CODE)
    return AgentExecutionRecordRef(canonical_bytes(v['agent_ref_bytes']), canonical_bytes(v['turn_ref_bytes']),
        v['source_revision'], v['operation_ref'], v['engineering_attempt_ref'],
        decode_digest(v['prompt_input_digest']), v['query_digest'], decode_blob_ref(v['captured_observation_ref']))


def _agent_report(v):
    require_object(v, {'schemaVersion','realm_id','project_id','submission_id','created_at',
        'created_by','change_set','authorization_refs','package_ref','execution_ref','output_refs',
        'coverage','source_refs','method_content','checkpoint_ref','digest'}, _CODE)
    if v['schemaVersion'] != AGENT_SUBMISSION_REPORT_VERSION:
        raise ReferenceError(_CODE)
    return AgentSubmissionReport(
        decode_scope({'realm_id': v['realm_id'], 'project_id': v['project_id']}),
        v['submission_id'], v['created_at'], decode_actor(v['created_by']), _changeset(v['change_set']),
        _tuple(v['authorization_refs'], decode_approval_ref), decode_package_ref(v['package_ref']),
        _agent_execution(v['execution_ref']), _tuple(v['output_refs'], _output),
        _tuple(v['coverage'], _coverage), _tuple(v['source_refs'], decode_source), _content(v['method_content']),
        None if v['checkpoint_ref'] is None else decode_blob_ref(v['checkpoint_ref']))


def decode_submission(raw: bytes) -> Submission | AgentSubmissionReport:
    try:
        v = canonical_value(raw, maximum=MAX_SUBMISSION_BYTES)
        if type(v) is dict and 'schemaVersion' in v:
            record = _agent_report(v)
            if record.digest != decode_digest(v['digest']) or encode_submission(record) != raw:
                raise ReferenceError(_CODE)
            return record
        version = v.get('schema_version', 1)
        if type(version) is not int or version not in (1, 2) or 'schema_version' in v and version != 2:
            raise ReferenceError(_CODE)
        fields = {'realm_id','project_id','submission_id','created_at','created_by','change_set','authorization_refs','package_ref','execution_ref','baseline_snapshots','resulting_snapshots','commit_refs','file_changes','output_refs','test_evidence','effect_observations','coverage','source_refs','method_content','checkpoint_ref','digest'}
        require_object(v, fields | ({'schema_version'} if version == 2 else set()), _CODE)
        record = Submission(
            decode_scope({'realm_id':v['realm_id'],'project_id':v['project_id']}),
            v['submission_id'],v['created_at'],decode_actor(v['created_by']),_changeset(v['change_set']),
            _tuple(v['authorization_refs'],decode_approval_ref),decode_package_ref(v['package_ref']),
            _execution(v['execution_ref']),_tuple(v['baseline_snapshots'],decode_repository_ref),
            _tuple(v['resulting_snapshots'],decode_repository_ref),_tuple(v['commit_refs'],_commit),
            _tuple(v['file_changes'],_file_change),_tuple(v['output_refs'],_output),
            _tuple(v['test_evidence'],_test),_tuple(v['effect_observations'],_effect),
            _tuple(v['coverage'],_coverage),_tuple(v['source_refs'],decode_source),_content(v['method_content']),
            None if v['checkpoint_ref'] is None else decode_blob_ref(v['checkpoint_ref']),
            schema_version=version)
        if record.digest != decode_digest(v['digest']) or encode_submission(record) != raw:
            raise ReferenceError(_CODE)
        return record
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError):
        raise ReferenceError(_CODE) from None


__all__ = ['submission_projection','encode_submission','decode_submission','MAX_SUBMISSION_BYTES']
