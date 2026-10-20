"""RC1 correction assembly: contract gating and single-shot behaviour.

The Engineering service and the Unit assembly are *controlled peers* here: the
frozen RC1 methods are owned by Sol and the real composition is Sol's serial run,
so this file proves the assembly's own refusals and call discipline, not a real
correction.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest


def _content_resume_fixture(tmp_path):
    import sqlite3
    from local_library_report_correction import validate_content_resume_receipt
    receipt = {'contract': 'ordessa.registered-report-content-rework/1',
        'work_id': 'fixture-work', 'state': 'report_unit_created',
        'unit_created': True, 'submitted': False, 'source_manifest_sha256': 'a' * 64,
        'candidate_sha256': 'b' * 64,
        **{k: {'digest': {'algorithm': 'sha256', 'hex': ch * 64}, 'byte_length': 10,
            'media_type': 'application/json', 'storage_object_id': 'fixture:' + k}
            for k, ch in [('plan_ref', 'c'), ('approval_ref', 'd'), ('checkpoint_ref', 'e')]}}
    validate_content_resume_receipt(receipt)
    claim = dict(realm_id='r', principal_id='p', request_id='claim', project_id='j',
        operation='engineering.report_content_rework.claim', operation_id='claim-op',
        request_digest='digest', state='pending', version=0)
    connection = sqlite3.connect(tmp_path / 'engineering.sqlite')
    try:
        connection.execute('CREATE TABLE eng_commands (realm_id,principal_id,request_id,'
            'project_id,operation,operation_id,request_digest,state,version,result_bytes)')
        connection.execute('INSERT INTO eng_commands VALUES (?,?,?,?,?,?,?,?,?,NULL)', tuple(claim.values()))
        connection.execute('CREATE TABLE eng_submissions (realm_id,project_id,submission_id)')
        connection.execute('CREATE TABLE eng_review_requests (realm_id,project_id,review_id)')
        connection.commit()
    finally:
        connection.close()
    return receipt, claim


def test_content_resume_preflight_is_read_only_and_keeps_pending(tmp_path):
    from local_library_report_correction import verify_content_resume_journal
    receipt, claim = _content_resume_fixture(tmp_path)
    before = (tmp_path / 'engineering.sqlite').read_bytes()
    verify_content_resume_journal(tmp_path, claim, receipt)
    assert (tmp_path / 'engineering.sqlite').read_bytes() == before


@pytest.mark.parametrize('partial', ['claim_changed', 'unknown', 'record', 'tail', 'submission', 'review'])
def test_content_resume_refuses_partial_or_unknown_instead_of_replaying(tmp_path, partial):
    import sqlite3
    from local_library_report_correction import verify_content_resume_journal
    receipt, claim = _content_resume_fixture(tmp_path)
    suffix = hashlib.sha256(canonical_bytes({k: receipt[k] for k in ('plan_ref', 'approval_ref')})).hexdigest()
    connection = sqlite3.connect(tmp_path / 'engineering.sqlite')
    try:
        if partial == 'claim_changed':
            connection.execute('UPDATE eng_commands SET version=1')
        elif partial == 'unknown':
            connection.execute("UPDATE eng_commands SET state='unknown'")
        elif partial in {'record', 'tail'}:
            request = ('rework-record-' + 'c' * 48 if partial == 'record'
                else 'report-content-rework-tail-' + suffix[:48])
            connection.execute('INSERT INTO eng_commands VALUES (?,?,?,?,?,?,?,?,?,NULL)',
                ('r', 'p', request, 'j', partial, 'op2', 'd2', 'pending', 0))
        elif partial == 'submission':
            connection.execute('INSERT INTO eng_submissions VALUES (?,?,?)',
                ('r', 'j', 'content-rework-' + 'c' * 40))
        else:
            connection.execute('INSERT INTO eng_review_requests VALUES (?,?,?)',
                ('r', 'j', 'report-content-rework-review-' + suffix))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(CorrectionRefused):
        verify_content_resume_journal(tmp_path, claim, receipt)


@pytest.mark.parametrize('field,value', [('submitted', True), ('unit_created', False),
    ('state', 'unknown'), ('checkpoint_ref', None)])
def test_content_resume_refuses_noncheckpoint_receipt(tmp_path, field, value):
    from local_library_report_correction import validate_content_resume_receipt
    receipt, _ = _content_resume_fixture(tmp_path)
    receipt[field] = value
    with pytest.raises(CorrectionRefused):
        validate_content_resume_receipt(receipt)

from local_library_report_correction import (
    Capture, CorrectionRefused, _completion_payload, expected_operation_ref, run, validate_capture,
    validate_prepare_result, validate_review_successor_selector, validate_sources_config,
)
from ordessa_infrastructure.encoding import canonical_bytes

DIGEST = {'algorithm': 'sha256', 'hex': 'a' * 64}
PLAN_REF = {'digest': DIGEST, 'byte_length': 120, 'media_type': 'application/json',
            'storage_object_id': 'plan-blob'}
BLOB_REF = {'digest': DIGEST, 'byte_length': 120, 'media_type': 'application/json',
            'storage_object_id': 'fixture-blob'}
ORIGINAL = b'{"type":"schema","report":"rejected original"}'
ALLOWED_PATHS = ('/repo/a.py', '/repo/b.py', '/repo/c.py', '/repo/d.py')


def _blob_ref(raw, name='fixture-output'):
    return {'digest': {'algorithm': 'sha256', 'hex': hashlib.sha256(raw).hexdigest()},
            'byte_length': len(raw), 'media_type': 'application/json',
            'storage_object_id': name}


def _service(prepare, correction_payload=None, method_result=None, status='completed'):
    class Result:
        operation_id = 'parent-op-1'

        def __init__(self):
            self.status = status
            self.result = {'method_result': (method_result if method_result is not None else
                               {'accepted': False, 'disposition': 'pending_review'})}

    class Service:
        def __init__(self):
            self.prepare_calls = []
            self.complete_calls = []
            self.awaited = 0
            self.correction_payload = correction_payload

        def prepare_report_correction(self, parameters, context):
            self.prepare_calls.append(parameters)
            return prepare

        async def complete_report_correction(self, parameters, context):
            self.complete_calls.append(parameters)
            self.awaited += 1
            payload = self.correction_payload
            if callable(payload):
                payload = payload(parameters)
            result = Result()
            result.result['report_correction'] = payload or {}
            return result
    return Service()


class _Blobs:
    """Graph BlobStore peer: stores the canonical checkpoint bytes."""

    def __init__(self):
        self.puts = []

    def put_verified(self, raw, digest, media_type):
        from ordessa_engineering.domain.common.models.refs import BlobRef
        self.puts.append((raw, digest, media_type))
        return BlobRef(digest=digest, byte_length=len(raw), media_type=media_type,
                       storage_object_id='blob-%d' % len(self.puts))


class _Assembly:
    def __init__(self):
        self.created = []
        self.captured = []
        self.closed = []
        self.forbidden = []

    def create_read_only_unit(self, params, operation_ref):
        self.created.append((params, operation_ref))
        return {'unit_ref': {'unitId': 'unit-new'}, 'operation_ref': operation_ref}

    def capture_unit_output(self, unit, operation_ref):
        self.captured.append((unit, operation_ref))
        output = b'{"corrected": true}'
        return Capture(unit_ref=unit['unit_ref'], operation_ref=operation_ref,
                       output_bytes=output,
                       prompt_input_digest=DIGEST, observation_ref=BLOB_REF,
                       observation_revision=3)

    def confirm_unit_closed(self, unit):
        self.closed.append(unit)
        return {'stop_confirmed': True, 'release_confirmed': True,
                'output_ref': _blob_ref(b'{"corrected": true}'), 'stop_record_digest': DIGEST,
                'release_record_digest': DIGEST}

    def create_with_edit(self, *args, **kwargs):
        self.forbidden.append('edit')


class _Materials:
    def __init__(self, payload=ORIGINAL):
        self.payload = payload
        self.calls = []

    def read_material(self, kind, locator):
        self.calls.append((kind, locator))
        return self.payload


_DEFAULT = object()


def _prepared(created=True, state='ready', params=_DEFAULT, submission_ref=None):
    prompt_body = {'instruction': 'Return only the original report with top-level type removed.',
        'report_correction_plan': {}, 'plan_ref': PLAN_REF,
        'rejected_report_utf8': ORIGINAL.decode('utf-8'),
        'implementation_report_schema': {}, 'allowed_read_paths': list(ALLOWED_PATHS)}
    return {'plan_ref': PLAN_REF, 'operation_ref': expected_operation_ref(PLAN_REF),
            'created': created, 'state': state,
            'params': ({'prompt': [{'type': 'text',
                       'text': canonical_bytes(prompt_body).decode('utf-8')}]}
                       if params is _DEFAULT else params),
            'submission_ref': submission_ref}


def _run(service, assembly=None, blobs=None, **overrides):
    paths = ALLOWED_PATHS
    values = dict(context=object(), invoke_parameters={'work_id': 'w', 'action_id': 'act',
                  'expected_revision': 1, 'inputs': {}}, allowed_paths=paths,
                  origin={'parent_operation_id': 'op', 'execution_operation_ref': 'native',
                          'expected_parent_version': 1, 'expected_dispatch_version': 2,
                          'expected_observation_revision': 3},
                  evidence={'files': [{'path': path, 'blob_ref': BLOB_REF} for path in paths],
                            'check': {'origin_operation_ref': 'native',
                                      'journal_ref': BLOB_REF,
                                      'excerpt_ref': BLOB_REF,
                                      'tool_call_id': 'tool-1', 'command_digest': DIGEST,
                                      'limitation': ('selected original Pi journal observation; '
                                          'not independently authenticated execution proof')}},
                  preserved_report={'bytes': ORIGINAL, 'length': len(ORIGINAL)})
    values.update(overrides)
    preserved = dict(values['preserved_report'])
    preserved.setdefault('digest', hashlib.sha256(preserved['bytes']).hexdigest())
    values['preserved_report'] = preserved
    return asyncio.run(run(service, assembly or _Assembly(), blobs or _Blobs(), **values))


def test_operation_ref_is_derived_from_the_plan_digest_only():
    assert expected_operation_ref(PLAN_REF) == 'report-format-rework/' + 'a' * 64
    with pytest.raises(CorrectionRefused):
        expected_operation_ref({'digest': {'algorithm': 'sha256', 'hex': 'b' * 63}})
    with pytest.raises(CorrectionRefused):
        expected_operation_ref({'digest': {'algorithm': 'md5', 'hex': 'b' * 64}})


def test_review_successor_selector_is_closed_and_requires_native_refs():
    value = {'checkpoint_ref': BLOB_REF,
        'predecessor_review': {'review_id': 'review-old', 'operation_ref': 'review-op-old',
            'expected_observation_revision': 3, 'observation_ref': BLOB_REF}}
    assert validate_review_successor_selector(value) is value
    for invalid in (
        {**value, 'extra': True},
        {**value, 'checkpoint_ref': {'digest': DIGEST}},
        {**value, 'predecessor_review': {**value['predecessor_review'], 'extra': 1}},
        {**value, 'predecessor_review': {**value['predecessor_review'],
                                         'expected_observation_revision': True}},
    ):
        with pytest.raises(CorrectionRefused):
            validate_review_successor_selector(invalid)


def test_prepare_projection_is_closed_and_state_gated():
    validate_prepare_result(_prepared())
    with pytest.raises(CorrectionRefused, match='unknown shape'):
        validate_prepare_result({**_prepared(), 'extra': 1})
    with pytest.raises(CorrectionRefused, match='does not derive'):
        validate_prepare_result({**_prepared(), 'operation_ref': 'report-format-rework/' + 'b' * 64})
    with pytest.raises(CorrectionRefused, match='no native capture'):
        validate_prepare_result(_prepared(params={}))
    with pytest.raises(CorrectionRefused, match='no native capture'):
        validate_prepare_result(_prepared(params={'prompt': [{'type': 'text', 'text': 'x'}],
                                           'sessionId': 'must-not-be-supplied'}))
    with pytest.raises(CorrectionRefused, match='created flag'):
        validate_prepare_result(_prepared(created=False, state='ready'))
    with pytest.raises(CorrectionRefused, match='already carries'):
        validate_prepare_result(_prepared(submission_ref={'kind': 'submission'}))
    for state in ('pending_query_only', 'report_registered'):
        with pytest.raises(CorrectionRefused, match='must not carry'):
            validate_prepare_result(_prepared(created=False, state=state))
        submission = None if state == 'pending_query_only' else {
            'realm_id': 'realm', 'project_id': 'project', 'submission_id': 'submission',
            'digest': DIGEST, 'kind': 'submission'}
        assert validate_prepare_result(_prepared(created=False, state=state, params=None,
            submission_ref=submission))['state'] == state


def test_ready_plan_creates_exactly_one_unit_and_one_completion():
    from dataclasses import asdict
    service, assembly, blobs = _service(_prepared(), correction_payload={
        'checkpoint_ref': {'digest': DIGEST}, 'plan_ref': PLAN_REF,
        'submission_ref': {'kind': 'submission'}}), _Assembly(), _Blobs()
    service.correction_payload = lambda parameters: {
        'checkpoint_ref': parameters['checkpoint_ref'], 'plan_ref': PLAN_REF,
        'submission_ref': {'kind': 'submission'}}
    outcome = _run(service, assembly, blobs)
    assert len(service.prepare_calls) == 1
    assert len(assembly.created) == 1
    assert assembly.created[0][1] == expected_operation_ref(PLAN_REF)
    assert len(assembly.captured) == 1 and len(assembly.closed) == 1
    assert len(service.complete_calls) == 1
    assert service.awaited == 1, 'complete_report_correction must be awaited'
    # The checkpoint envelope is stored in this graph's BlobStore and only its
    # BlobRef projection reaches complete; the rejected original is never sent.
    assert len(blobs.puts) == 1 and blobs.puts[0][2] == 'application/json'
    assert set(service.complete_calls[0]) == {'invoke_parameters', 'checkpoint_ref'}
    checkpoint = json.loads(blobs.puts[0][0])
    assert set(checkpoint) == {'contract', 'plan_ref', 'correction'}
    assert checkpoint['contract'] == 'ordessa.declared-report-format-rework/1'
    assert set(checkpoint['correction']) == {
        'unit_ref', 'operation_ref', 'prompt_input_digest', 'observation_ref',
        'observation_revision', 'output_ref', 'stop_record_digest', 'release_record_digest'}
    passed_ref = service.complete_calls[0]['checkpoint_ref']
    assert passed_ref['digest']['hex'] == hashlib.sha256(blobs.puts[0][0]).hexdigest()
    assert outcome['submitted'] is True
    assert outcome['submission_ref'] == {'kind': 'submission'}
    assert outcome['parent_operation_id'] == 'parent-op-1'


def test_pending_claim_or_registered_report_never_creates_a_unit():
    for state in ('pending_query_only', 'report_registered'):
        submission = None if state == 'pending_query_only' else {
            'realm_id': 'realm', 'project_id': 'project', 'submission_id': 'submission',
            'digest': DIGEST, 'kind': 'submission'}
        service = _service(_prepared(created=False, state=state, params=None,
                                     submission_ref=submission))
        assembly = _Assembly()
        outcome = _run(service, assembly)
        assert outcome['submitted'] is False
        assert outcome['state'] == state
        assert assembly.created == [] and assembly.captured == []
        assert service.complete_calls == []
        assert len(service.prepare_calls) == 1


def test_ready_plan_body_is_revalidated_before_any_unit_create():
    service = _service(_prepared(params={'prompt': [{'type': 'text', 'text': '{}'}]}))
    assembly = _Assembly()
    with pytest.raises(CorrectionRefused, match='native prompt'):
        _run(service, assembly)
    assert len(service.prepare_calls) == 1
    assert assembly.created == [] and assembly.captured == []
    assert service.complete_calls == []


def test_changed_original_bytes_refuse_before_prepare():
    service = _service(_prepared())
    with pytest.raises(CorrectionRefused, match='does not match its own digest'):
        _run(service, preserved_report={'bytes': b'{"different": true}',
                                        'length': len(ORIGINAL),
                                        'digest': hashlib.sha256(ORIGINAL).hexdigest()})
    assert service.prepare_calls == []


def test_unconfirmed_termination_refuses_and_never_completes():
    service = _service(_prepared())

    class Unconfirmed(_Assembly):
        def confirm_unit_closed(self, unit):
            return {'stop_confirmed': True, 'release_confirmed': False}

    with pytest.raises(CorrectionRefused, match='termination is not confirmed'):
        _run(service, Unconfirmed())
    assert service.complete_calls == []


def test_termination_projection_is_closed_and_capture_bytes_match_output_ref():
    from local_library_report_correction import build_checkpoint
    capture = Capture(unit_ref={'unitId': 'unit-new'},
        operation_ref=expected_operation_ref(PLAN_REF), output_bytes=b'{"capture":true}',
        prompt_input_digest=DIGEST, observation_ref=BLOB_REF, observation_revision=1)
    closed = {'stop_confirmed': True, 'release_confirmed': True,
        'output_ref': _blob_ref(b'{"different":true}'),
        'stop_record_digest': DIGEST, 'release_record_digest': DIGEST}
    with pytest.raises(CorrectionRefused, match='output reference'):
        build_checkpoint(plan_ref=PLAN_REF, capture=capture, closed=closed)
    closed['output_ref'] = _blob_ref(capture.output_bytes)
    with pytest.raises(CorrectionRefused, match='termination is not confirmed'):
        build_checkpoint(plan_ref=PLAN_REF, capture=capture,
                         closed={**closed, 'unexpected': 'field'})


def test_capture_must_match_the_plan_operation():
    service = _service(_prepared())

    class WrongOperation(_Assembly):
        def capture_unit_output(self, unit, operation_ref):
            return Capture(unit_ref=unit['unit_ref'], operation_ref='report-format-rework/' + 'c' * 64,
                           output_bytes=b'{}', prompt_input_digest=DIGEST,
                           observation_ref=BLOB_REF, observation_revision=1)

    with pytest.raises(CorrectionRefused, match='capture projection is invalid'):
        _run(service, WrongOperation())
    assert service.complete_calls == []


def test_server_capture_mapping_is_accepted_and_exact():
    capture = {'unit_ref': {'unitId': 'unit-new'},
        'operation_ref': expected_operation_ref(PLAN_REF), 'output_bytes': b'{"ok":true}',
        'prompt_input_digest': DIGEST, 'observation_ref': BLOB_REF,
        'observation_revision': 3}
    mapped = validate_capture(capture, operation_ref=expected_operation_ref(PLAN_REF))
    assert isinstance(mapped, Capture)
    with pytest.raises(CorrectionRefused, match='capture projection is invalid'):
        validate_capture({**capture, 'untrusted': True},
                         operation_ref=expected_operation_ref(PLAN_REF))


def test_source_config_is_closed_finite_and_operation_bound(tmp_path):
    from local_library_report_correction import validate_sources_config
    journal, excerpt = tmp_path / 'selected.jsonl', tmp_path / 'excerpt.txt'
    journal.write_bytes(b'{"native":"selected"}\n')
    excerpt.write_bytes(b'selected tool call excerpt')
    selected = {'origin_operation_ref': 'native-op',
        'original_journal': {'path': str(journal), 'digest': _blob_ref(journal.read_bytes())['digest']},
        'original_check_excerpt': {'path': str(excerpt), 'digest': _blob_ref(excerpt.read_bytes())['digest']}}
    result = validate_sources_config(selected, origin_operation_ref='native-op',
        allowed_paths=('/repo/a', '/repo/b', '/repo/c', '/repo/d'))
    assert result == selected
    with pytest.raises(CorrectionRefused, match='source selector'):
        validate_sources_config({**selected, 'untrusted': True},
            origin_operation_ref='native-op', allowed_paths=())
    with pytest.raises(CorrectionRefused, match='source selector'):
        validate_sources_config(selected, origin_operation_ref='other-op', allowed_paths=())


def test_run_report_is_required_before_any_graph_open(tmp_path):
    from local_library_report_correction import recover_registered_graph
    with pytest.raises(CorrectionRefused, match='explicit --run-report'):
        recover_registered_graph(registration_path=tmp_path / 'absent-registration.json',
            registration_sha256='0' * 64, candidate_path=tmp_path / 'absent-candidate.json',
            candidate_sha256='0' * 64, sources_config={}, output=tmp_path / 'output',
            source_manifest_path=tmp_path / 'absent-manifest.json',
            source_manifest_sha256='0' * 64, run_report=False)


def test_malformed_selector_or_evidence_refuses_before_prepare_or_unit():
    service, assembly = _service(_prepared()), _Assembly()
    with pytest.raises(CorrectionRefused, match='origin version selectors'):
        _run(service, assembly, origin={'parent_operation_id': 'op',
            'execution_operation_ref': 'native', 'expected_parent_version': True,
            'expected_dispatch_version': 2, 'expected_observation_revision': 3})
    assert service.prepare_calls == [] and assembly.created == []

    service = _service(_prepared())
    with pytest.raises(CorrectionRefused, match='evidence file projection'):
        _run(service, _Assembly(), evidence={'files': [{'path': 'relative.py',
             'blob_ref': BLOB_REF}], 'check': {
                'origin_operation_ref': 'native', 'journal_ref': BLOB_REF,
                'excerpt_ref': BLOB_REF, 'tool_call_id': 'tool-1',
                'command_digest': DIGEST, 'limitation': ('selected original Pi journal observation; '
                    'not independently authenticated execution proof')}})
    assert service.prepare_calls == []


def test_created_unit_is_closed_once_when_capture_validation_fails():
    service = _service(_prepared())

    class InvalidCapture(_Assembly):
        def capture_unit_output(self, unit, operation_ref):
            self.captured.append((unit, operation_ref))
            return {'bad': 'shape'}

    assembly = InvalidCapture()
    with pytest.raises(CorrectionRefused, match='capture projection is invalid'):
        _run(service, assembly)
    assert len(assembly.created) == 1 and len(assembly.closed) == 1
    assert service.complete_calls == []


def test_missing_report_correction_projection_is_refused_not_marked_submitted():
    service = _service(_prepared())
    outcome = _run(service)
    assert outcome['submitted'] is False
    assert outcome['refused'] == 'completion result carries no closed report_correction projection'


def test_status_completed_is_not_acceptance():
    service = _service(_prepared(), correction_payload={
        'checkpoint_ref': {'digest': DIGEST}, 'plan_ref': PLAN_REF,
        'submission_ref': {'kind': 'submission'}},
        method_result={'accepted': False, 'disposition': 'pending_review'})
    service.correction_payload = lambda parameters: {
        'checkpoint_ref': parameters['checkpoint_ref'], 'plan_ref': PLAN_REF,
        'submission_ref': {'kind': 'submission'}}
    outcome = _run(service)
    assert outcome['submitted'] is True and outcome['accepted'] is False
    assert outcome['disposition'] == 'pending_review'


def test_native_command_result_bytes_are_decoded_as_the_completion_projection():
    class NativeResult:
        status = 'completed'
        result_bytes = b'{"method_result":{"accepted":false},"report_correction":{}}'

    assert _completion_payload(NativeResult())['method_result'] == {'accepted': False}

    class PendingResult:
        status = 'pending'
        result_bytes = None

    with pytest.raises(CorrectionRefused, match='not terminal'):
        _completion_payload(PendingResult())


def test_assembly_has_no_edit_or_execute_surface_in_this_driver():
    service, assembly = _service(_prepared()), _Assembly()
    _run(service, assembly)
    # The driver only ever uses the three read-only assembly entry points.
    assert assembly.forbidden == []
    assert all(hasattr(_Assembly, name) for name in
               ('create_read_only_unit', 'capture_unit_output', 'confirm_unit_closed'))


def test_registered_manifest_leaves_original_instance_secret_unread(tmp_path, monkeypatch):
    from local_library_report_correction import _safe_graph_manifest

    graph = tmp_path / 'runtime'
    token = graph / 'product/secrets/http-token'
    token.parent.mkdir(parents=True)
    token.write_text('fixture-instance-credential')
    auth = graph / 'local-environment/unit-fixture/profile/auth.json'
    auth.parent.mkdir(parents=True)
    auth.write_text('{"fixture":"credential"}')
    public = graph / 'engineering.sqlite'
    public.write_bytes(b'fixture-owner-state')
    original_read = Path.read_bytes

    def read(path):
        assert path not in (token, auth), 'recovery must not read owner credentials'
        return original_read(path)

    monkeypatch.setattr(Path, 'read_bytes', read)
    manifest = _safe_graph_manifest(graph, None)
    assert manifest == {'engineering.sqlite': hashlib.sha256(b'fixture-owner-state').hexdigest()}
    assert token.is_file() and auth.is_file()

    unexpected = graph / 'unrelated/secrets/key'
    unexpected.parent.mkdir(parents=True)
    unexpected.write_text('fixture-unexpected')
    with pytest.raises(CorrectionRefused, match='unexpected credential'):
        _safe_graph_manifest(graph, None)
