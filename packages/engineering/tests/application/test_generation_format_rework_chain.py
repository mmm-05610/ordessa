"""Real Library/Work registration with a labelled native-transport double."""
import asyncio
from dataclasses import asdict, replace
import hashlib
from types import SimpleNamespace

import pytest
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import decode_package_ref
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.package_document_materials import PackageDocumentMaterials

from test_declarative_work import start_params
from test_real_source_chain import SCOPE, context, close_chain
from test_work_invoke_generation import (
    _Transport, _generation_env, _invoke_generation, _prepared_output,
    _command_payload, _command_status)
from work_step_access_fixture import enable_controlled_work_steps


NEW_WORK = 'format-rework-new-work'


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)


def _digest(value):
    return 'sha256:' + hashlib.sha256(canonical_bytes({'value': value})).hexdigest()


class _NativeTransport(_Transport):
    """No network or Unit process; emits the complete native receipt shape."""
    def freeze_input(self, unit_ref, params):
        frozen = dict(params, sessionId='session-' + unit_ref['unitId'])
        raw = canonical_bytes(frozen)
        return raw, Digest('sha256', _digest({'unitRef': unit_ref, 'params': frozen})[7:])

    def capture(self, binding):
        output = self.blobs.read_verified(self.blob_ref).decode()
        unit = decode_json(binding.unit_ref_bytes)
        params = decode_json(self.blobs.read_verified(binding.prompt_ref))
        inputs = {'unitRef': unit, 'params': params}
        request = {'jsonrpc': '2.0', 'id': binding.execution_operation_ref,
                   'method': 'session/prompt', 'params': params}
        frame = canonical_bytes(request) + b'\n'
        response = {'jsonrpc': '2.0', 'id': request['id'], 'result': {'stopReason': 'end_turn'}}
        chunk = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': params['sessionId'], 'update': {'sessionUpdate': 'agent_message_chunk',
                'content': {'type': 'text', 'text': output}}}}
        events = [{'raw': chunk, 'sequence': 1, 'sessionMatched': True},
                  {'raw': response, 'sequence': 2, 'sessionMatched': False}]
        receipt = {'contractVersion': 'unit-acp-turn/1', 'unitRef': unit,
            'operationRef': binding.execution_operation_ref, 'input': inputs,
            'inputDigest': _digest(inputs), 'state': 'completed', 'revision': 5,
            'nativeBinding': {'sessionId': params['sessionId']},
            'request': {'raw': request, 'frameUtf8': frame.decode(),
                        'frameDigest': 'sha256:' + hashlib.sha256(frame).hexdigest()},
            'response': response, 'events': events, 'eventsDigest': _digest(events),
            'responseDigest': _digest(response), 'summary': {'text': output,
                'textDigest': _digest(output), 'successfulRpcResponse': True,
                'modelQualityVerified': False, 'knownRemoteFailure': False,
                'stopReason': 'end_turn', 'eventCount': len(events)}}
        raw = canonical_bytes(receipt)
        blob = self.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                      'application/json')
        return SimpleNamespace(blob_ref=blob, state=getattr(self, 'captured_state', 'completed'))


def _attach(env, transport, *, selector=None):
    env.service.attach_declared_generation_handles(
        blobs=env.blobs, execution=transport, format_rework=selector,
        unit_ref_resolver=lambda ctx, binding, profile: {
            'environmentNamespace': 'env', 'unitId': binding.work_id,
            'ownerProviderRef': {'provider': 'controlled-local'}, 'sourceRevision': 'rev-1'})


def _prior_case(tmp_path, *, native_unknown=False):
    malformed = _prepared_output() + b'}'
    env, chain, _ = _generation_env(tmp_path, malformed)
    blob = env.blobs.put_verified(malformed, Digest('sha256', hashlib.sha256(malformed).hexdigest()),
                                  'application/json')
    transport = _NativeTransport(blob, blobs=env.blobs)
    if native_unknown:
        transport.captured_state = 'unknown'
    _attach(env, transport)
    code = ('WORK_ACTION_GENERATION_RESULT_UNCONFIRMED' if native_unknown
            else 'WORK_ACTION_GENERATION_OUTPUT_INVALID')
    with pytest.raises(ApplicationError, match=code):
        _invoke_generation(env, chain, transport)
    with env.library._read_connection() as connection:
        operation = connection.execute('SELECT execution_operation_ref FROM work_step_log '
            'WHERE binding_digest IS NOT NULL').fetchone()[0]
        before = connection.execute('SELECT * FROM work_step_log WHERE execution_operation_ref=?',
                                     (operation,)).fetchone()
    selector = {'target_work_id': NEW_WORK, 'prior_operation_ref': operation,
                'raw_text_digest': 'sha256:' + hashlib.sha256(malformed).hexdigest()}
    return env, chain, transport, selector, before


def _new_work(env, chain):
    result = asyncio.run(env.service.execute('engineering.work.start',
        start_params(env, work_id=NEW_WORK, associations=(('proposal', chain.successor),)),
        context('start-format-rework')))
    assert _command_status(result) == 'completed'


def _new_invoke(env, chain):
    return asyncio.run(env.service.execute('engineering.work.invoke', {
        'work_id': NEW_WORK, 'action_id': 'incremental.prepare-packages', 'inputs': {
            'baseline': asdict(env.baseline), 'candidate': asdict(env.candidate),
            'scope': asdict(SCOPE), 'review': asdict(chain.review_ref),
            'method': asdict(env.method), 'profile': {'test_double': 'fixed-profile-revision'}}},
        context('invoke-format-rework')))


def test_new_format_work_registers_exact_bodies_and_preserves_prior_result(tmp_path):
    env, chain, transport, selector, before = _prior_case(tmp_path)
    try:
        _attach(env, transport, selector=selector)
        _new_work(env, chain)
        raw = _prepared_output()
        transport.blob_ref = env.blobs.put_verified(raw,
            Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
        result = _new_invoke(env, chain)
        assert _command_status(result) == 'completed', _command_payload(result)
        generated = next(s['business'] for s in _command_payload(result)['steps']
                         if s.get('business', {}).get('package_ref'))
        ref = decode_package_ref(generated['package_ref'])
        with env.library._read_connection() as connection:
            assert connection.execute('SELECT * FROM work_step_log WHERE execution_operation_ref=?',
                                      (selector['prior_operation_ref'],)).fetchone() == before
        assert transport.sends == 2
        path = env.library.path
        env.library.close()
        reopened = EngineeringLibrary.open(path, library_id='local-source-chain')
        try:
            factory, blobs = SQLiteUoWFactory(reopened), SQLiteBlobStore(reopened)
            with factory.begin(SCOPE, 'read') as uow:
                package = uow.implementation.resolve_package(ref)
            reader = PackageDocumentMaterials(factory, blobs, scope=SCOPE, package_ref=ref)
            expected = decode_json(raw)['document_contents']
            for doc in package.payload.documents:
                assert reader.read(context('read-format-package'), doc.source_ref) == expected[doc.role].encode()
            with factory.begin(SCOPE, 'read') as uow:
                row = uow.work_dispatch.get(generated['run_association']['dispatch_key'], 'draft', 1, SCOPE)
            from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
            binding = decode_dispatch(row['binding_bytes'])
            prompt = decode_json(blobs.read_verified(binding.prompt_ref))['prompt'][0]['text']
            material = decode_json(prompt)['format_rework']
            assert material['prior']['operation_ref'] == selector['prior_operation_ref']
            assert material['raw_text_digest'] == selector['raw_text_digest']
            assert material['raw_text'] == (_prepared_output() + b'}').decode()
        finally:
            reopened.close()
    finally:
        close_chain(env)


@pytest.mark.parametrize('corruption', ['native_unknown', 'wrong_review', 'wrong_target', 'wrong_digest'])
def test_prior_refusal_has_no_new_send_or_package(tmp_path, corruption):
    env, chain, transport, selector, _ = _prior_case(
        tmp_path, native_unknown=corruption == 'native_unknown')
    try:
        _new_work(env, chain)
        if corruption == 'wrong_target':
            selector = dict(selector, target_work_id='different-work')
        elif corruption == 'wrong_digest':
            selector = dict(selector, raw_text_digest='sha256:' + '0' * 64)
        _attach(env, transport, selector=selector)
        with pytest.raises(ApplicationError):
            if corruption == 'wrong_review':
                env.service.declared_generation_dispatch.read_completed_generation(
                    selector['prior_operation_ref'], context('wrong-prior-review'),
                    current_work_id=NEW_WORK, change_ref=chain.successor,
                    review_ref=replace(chain.review_ref, review_id='another-review'),
                    method_ref=env.method, baseline=env.baseline, candidate=env.candidate)
            else:
                _new_invoke(env, chain)
        assert transport.sends == 1
        with env.library._read_connection() as connection:
            assert connection.execute('SELECT count(*) FROM eng_packages WHERE package_id=?',
                                      ('generated-package-1',)).fetchone()[0] == 0
    finally:
        close_chain(env)


def test_new_response_body_change_refuses_before_document_archive(tmp_path, monkeypatch):
    env, chain, transport, selector, before = _prior_case(tmp_path)
    try:
        _attach(env, transport, selector=selector);_new_work(env, chain)
        output = decode_json(_prepared_output());output['document_contents']['spec'] += 'Changed.\n'
        raw = canonical_bytes(output)
        transport.blob_ref = env.blobs.put_verified(raw,
            Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
        archives = []
        original = env.blobs.put_verified
        def observe(raw, digest, media_type):
            if media_type == 'text/markdown': archives.append(raw)
            return original(raw, digest, media_type)
        monkeypatch.setattr(env.blobs, 'put_verified', observe)
        with pytest.raises(ApplicationError, match='WORK_ACTION_GENERATION_REWORK_CONTENT_CHANGED'):
            _new_invoke(env, chain)
        assert archives == [] and transport.sends == 2
        with env.library._read_connection() as connection:
            assert connection.execute('SELECT count(*) FROM eng_packages WHERE package_id=?',
                                      ('generated-package-1',)).fetchone()[0] == 0
            assert connection.execute('SELECT * FROM work_step_log WHERE execution_operation_ref=?',
                                      (selector['prior_operation_ref'],)).fetchone() == before
    finally:
        close_chain(env)
