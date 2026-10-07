"""Local evidence guarantees; runtime gateway/cleanup tests own HTTP gating."""
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from pacthold.decision.contracts.codec import digest
from pacthold.decision.contracts.ports import ReadContext
from pacthold.decision.evidence import EvidenceError, FileEvidenceSink, FileEvidenceReader, MemoryEvidenceSink

def run(awaitable): return asyncio.run(awaitable)

@pytest.fixture
def store(tmp_path):
    tmp_path.chmod(0o700)
    context = ReadContext(object(), 'test.scope')
    sink = FileEvidenceSink(tmp_path, read_context=context)
    yield tmp_path, context, sink
    run(sink.close())

def meta(run_id):
    return {'run_id':run_id, 'manifest_digest':digest('runmanifest', {'test':True}),
            'request_digest':digest('request', {'test':True}),
            'effective_policy_refs':[{'policy_id':'test', 'version':'1', 'digest':digest('policy', {})}]}

def terminal(run_id, status='failed'):
    result = {'run_id':run_id, 'status':status, 'error_code':'test_failure',
              'run_manifest_digest':meta(run_id)['manifest_digest']}
    return {'run_id':run_id, 'status':status, 'result':result, 'result_digest':digest('result', result)}

def test_t21_memory_ack_never_claims_durability():
    context = ReadContext(object(), 'test.scope')
    sink = MemoryEvidenceSink(read_context=context)
    ack = run(sink.start(meta(str(uuid.uuid4()))))
    assert sink.durable is False and ack.durability == 'memory'

def test_t21_started_persisted_and_permissions(store):
    root, context, sink = store
    run_id = str(uuid.uuid4())
    ack = run(sink.start(meta(run_id)))
    assert ack.seq == 1 and ack.durability == 'durable'
    assert run(sink.read(run_id, context))['status'] == 'running'
    assert (root/run_id).stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (root/run_id).iterdir())

def test_t21_started_io_failure_returns_no_ack(store, monkeypatch):
    _, context, sink = store
    run_id = str(uuid.uuid4())
    monkeypatch.setattr(os,'fsync',lambda fd: (_ for _ in ()).throw(OSError('controlled failure')))
    with pytest.raises(EvidenceError, match='evidence_start_failed'): run(sink.start(meta(run_id)))
    assert run(sink.read(run_id,context))['status'] != 'completed'

def test_t25_terminal_idempotence_conflict_and_lost_ack(store):
    _, context, sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    value = terminal(run_id)
    ack = run(sink.finish(value))
    assert run(sink.finish(value)) == ack
    changed = terminal(run_id, 'cancelled')
    with pytest.raises(EvidenceError, match='terminal_conflict'): run(sink.finish(changed))
    read = run(sink.read(run_id, context))
    assert read['status'] == 'completed' and read['terminal'] == value
    assert read['terminal']['status'] == 'failed'

def test_t26_append_io_failure_poisoned_no_ready(store, monkeypatch):
    _, context, sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    original = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('synthetic disk failure')))
    with pytest.raises(EvidenceError, match='evidence_append_failed'):
        run(sink.append_durable({'type':'call.response','run_id':run_id,'call_id':'call.1'}))
    monkeypatch.setattr(os, 'fsync', original)
    with pytest.raises(EvidenceError, match='evidence_writer'): run(sink.finish(terminal(run_id)))
    assert run(sink.read(run_id, context))['status'] != 'completed'

def test_t31_safe_summary_and_context_identity(store):
    root, context, sink = store
    run_id = str(uuid.uuid4())
    value = meta(run_id)
    value.update(prompt='SECRET_PROMPT', body='SECRET_BODY', headers={'Authorization':'SECRET_KEY'}, state=object())
    run(sink.start(value))
    run(sink.append_durable({'type':'call.intent','run_id':run_id,'call_id':'call.1',
                             'exception':RuntimeError('SECRET_EXCEPTION'),'raw_response':'SECRET_RESPONSE'}))
    assert b'SECRET' not in (root/run_id/'events.jsonl').read_bytes()
    assert run(sink.read(run_id, ReadContext(object(), context.scope_ref)))['status'] == 'refused'
    assert run(sink.read(run_id, ReadContext(context.authority, 'other.scope')))['status'] == 'refused'

def test_t31_terminal_exact_digest_free_text_and_sensitive_rejection(store):
    _, context, sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    result = {'run_id':run_id,'status':'failed','error_code':'test_failure',
              'run_manifest_digest':meta(run_id)['manifest_digest'],
              'validation_scope':'Checked configuration description only.',
              'checked_at':'2026-10-05T10:00:00+08:00',
              'configuration':{'label':'普通配置名称'}}
    value = {'run_id':run_id,'status':'failed','result':result,'result_digest':digest('result',result)}
    dangerous = dict(result, configuration={'api_key':'SECRET'})
    with pytest.raises(EvidenceError, match='evidence_terminal_sensitive'):
        run(sink.finish(dict(value,result=dangerous,result_digest=digest('result',dangerous))))
    run(sink.finish(value))
    assert run(sink.read(run_id,context))['terminal'] == value

def test_t31_reject_traversal_symlink_and_preexisting_run(store):
    root, context, sink = store
    with pytest.raises(EvidenceError): run(sink.start(meta('../escape')))
    run_id = str(uuid.uuid4())
    outside = root/'outside'; outside.mkdir(mode=0o700)
    (root/run_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(EvidenceError): run(sink.start(meta(run_id)))
    assert not list(outside.iterdir())
    assert run(sink.read(run_id, context))['status'] in ('refused','unavailable','unknown')

@pytest.mark.parametrize('corrupt', ['truncate','sequence','terminal','symlink'])
def test_t32_corruption_never_success(store, corrupt):
    root, context, sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    run(sink.finish(terminal(run_id)))
    log = root/run_id/'events.jsonl'
    if corrupt == 'truncate': log.write_bytes(log.read_bytes()[:-1])
    elif corrupt == 'sequence': log.write_bytes(log.read_bytes().replace(b'"seq":1',b'"seq":9'))
    elif corrupt == 'terminal': (root/run_id/'terminal.json').write_bytes(b'{')
    else:
        log.unlink(); log.symlink_to(root/'missing')
    assert run(sink.read(run_id, context))['status'] in ('unknown','refused','unavailable')
    assert run(sink.read(str(uuid.uuid4()), context))['status'] == 'not_found'

_CHILD = r'''
import asyncio, os, sys
from pacthold.decision.contracts.ports import ReadContext
from pacthold.decision.contracts.codec import digest
from pacthold.decision.evidence import FileEvidenceSink
root, run_id, window = sys.argv[1:]
async def main():
    sink = FileEvidenceSink(root, read_context=ReadContext(object(), 'test.scope'))
    await sink.start({'run_id':run_id,'manifest_digest':digest('runmanifest', {})})
    if window != 'started':
        await sink.append_durable({'type':'call.intent','run_id':run_id,'call_id':'call.1'})
    if window in ('response','terminal_staged','terminal_renamed','terminal_committed'):
        await sink.append_durable({'type':'call.response','run_id':run_id,'call_id':'call.1'})
    if window == 'terminal_staged':
        original = os.rename
        def pause(*args, **kwargs):
            print('ready', flush=True)
            sys.stdin.read(1)
            return original(*args, **kwargs)
        os.rename = pause
    if window == 'terminal_renamed':
        import stat
        original_fsync = os.fsync
        def pause_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode) and os.path.exists(os.path.join(root,run_id,'terminal.json')):
                print('ready',flush=True)
                sys.stdin.read(1)
            return original_fsync(fd)
        os.fsync = pause_fsync
    if window in ('terminal_staged','terminal_renamed','terminal_committed'):
        result = {'run_id':run_id,'status':'failed','error_code':'controlled_failure',
                  'run_manifest_digest':digest('runmanifest', {})}
        await sink.finish({'run_id':run_id,'status':'failed','result':result,'result_digest':digest('result', result)})
    print('ready', flush=True)
    sys.stdin.read(1)
asyncio.run(main())
'''

@pytest.mark.parametrize('window', ['started','intent','response','terminal_staged','terminal_renamed','terminal_committed'])
def test_t22_t24_t27_actual_process_kill_commit_windows(store, window):
    root, context, sink = store
    run_id = str(uuid.uuid4())
    child = subprocess.Popen([sys.executable, '-u', '-c', _CHILD, str(root), run_id, window],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
    try:
        import selectors
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(10), 'child did not reach controlled crash window'
        assert child.stdout.readline().strip() == 'ready'
        live = run(sink.read(run_id, context))
        assert live['status'] == ('completed' if window=='terminal_committed' else
                                 'unknown' if window=='terminal_renamed' else 'running')
        child.kill(); child.wait(timeout=10)
        assert child.returncode < 0
        dead = run(sink.read(run_id, context))
        assert dead['status'] == ('completed' if window=='terminal_committed' else
                                 'unknown' if window=='terminal_renamed' else 'interrupted')
        if window=='intent': assert dead['call_evidence'] == 'unknown'
        if window=='terminal_committed': assert dead['terminal']['status'] == 'failed'
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=10)
        for pipe in (child.stdin, child.stdout, child.stderr): pipe.close()

def test_t25_terminal_directory_fsync_failure_remains_unknown(store, monkeypatch):
    root, context, sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    writer = sink._writers[run_id]
    original = os.fsync
    def lose_ack(fd):
        if fd == writer['dir'] and (root/run_id/'terminal.json').exists():
            raise OSError('controlled directory fsync failure')
        return original(fd)
    monkeypatch.setattr(os, 'fsync', lose_ack)
    with pytest.raises(EvidenceError, match='evidence_terminal_unknown'): run(sink.finish(terminal(run_id)))
    monkeypatch.setattr(os, 'fsync', original)
    assert run(sink.read(run_id, context))['status'] == 'unknown'
    with pytest.raises(EvidenceError): run(sink.finish(terminal(run_id, 'cancelled')))
    run(sink.close())
    reader = FileEvidenceReader(root,read_context=context)
    try: assert run(reader.read(run_id,context))['status'] == 'unknown'
    finally: run(reader.close())

def test_t25_ack_lost_after_successful_fsync_and_release_preserves_committed(store,monkeypatch):
    _,context,sink = store
    run_id = str(uuid.uuid4()); run(sink.start(meta(run_id)))
    original = sink.finish
    async def lose_ack(value):
        await original(value)
        raise EvidenceError('controlled_ack_lost')
    monkeypatch.setattr(sink,'finish',lose_ack)
    with pytest.raises(EvidenceError,match='controlled_ack_lost'): run(sink.finish(terminal(run_id)))
    assert run_id not in sink._writers
    result = run(sink.read(run_id,context))
    assert result['status']=='completed' and result['events'][-1]['payload']['type']=='terminal.commit'
    monkeypatch.setattr(sink,'finish',original)
    assert run(sink.finish(terminal(run_id))).durability == 'durable'

def test_t25_completion_receipt_fsync_failure_live_writer_unknown(store,monkeypatch):
    _,context,sink = store
    run_id = str(uuid.uuid4()); run(sink.start(meta(run_id)))
    writer = sink._writers[run_id]
    original = os.fsync
    def fail_commit(fd):
        if fd==writer['log']: raise OSError('controlled receipt fsync failure')
        return original(fd)
    monkeypatch.setattr(os,'fsync',fail_commit)
    with pytest.raises(EvidenceError,match='evidence_terminal_unknown'): run(sink.finish(terminal(run_id)))
    assert run(sink.read(run_id,context))['status']=='unknown'
    with pytest.raises(EvidenceError): run(sink.finish(terminal(run_id,'cancelled')))

@pytest.mark.parametrize('credential',['apiKey','api-key','password','token','client_secret','privateKey'])
def test_t31_normalized_plaintext_credentials_never_recorded(store,credential):
    root,context,sink = store
    run_id = str(uuid.uuid4()); run(sink.start(meta(run_id)))
    run(sink.append_durable({'type':'call.intent','run_id':run_id,'call_id':'call.1',
        'evidence_refs':[{'environmentNamespace':'test',credential:'sk-SECRET'}]}))
    assert b'sk-SECRET' not in (root/run_id/'events.jsonl').read_bytes()
    result = {'run_id':run_id,'status':'failed','error_code':'test',
              'run_manifest_digest':meta(run_id)['manifest_digest'],
              'configuration':{credential:'sk-SECRET'}}
    with pytest.raises(EvidenceError,match='evidence_terminal_sensitive'):
        run(sink.finish({'run_id':run_id,'status':'failed','result':result,'result_digest':digest('result',result)}))
    assert not (root/run_id/'terminal.json').exists()

def test_t31_credential_secret_reference_is_preserved_exactly(store):
    _,context,sink = store
    run_id = str(uuid.uuid4()); run(sink.start(meta(run_id)))
    secret_ref = {'secretRef':{'ref':'credential.test','revision':'1','owner_namespace':'test',
                               'access_purpose':'decision.read'}}
    result = {'run_id':run_id,'status':'failed','error_code':'test',
              'run_manifest_digest':meta(run_id)['manifest_digest'],
              'configuration':{'apiKey':secret_ref,'password':secret_ref}}
    value = {'run_id':run_id,'status':'failed','result':result,'result_digest':digest('result',result)}
    run(sink.finish(value))
    assert run(sink.read(run_id,context))['terminal'] == value

def test_t25_reserved_completion_receipt_cannot_be_supplied_by_caller(store):
    _,context,sink = store
    run_id = str(uuid.uuid4()); run(sink.start(meta(run_id)))
    with pytest.raises(EvidenceError,match='evidence_reserved_event'):
        run(sink.append_durable({'type':'terminal.commit','run_id':run_id}))
    assert run(sink.read(run_id,context))['status']=='running'

def test_t25_completion_receipt_has_reserved_capacity(tmp_path):
    tmp_path.chmod(0o700)
    context=ReadContext(object(),'test.scope')
    sink=FileEvidenceSink(tmp_path,read_context=context,max_events=1)
    try:
        run_id=str(uuid.uuid4()); run(sink.start(meta(run_id)))
        ack=run(sink.finish(terminal(run_id)))
        assert ack.seq==2 and run(sink.read(run_id,context))['status']=='completed'
    finally: run(sink.close())

def test_t32_torn_completion_receipt_never_recovers_success(store):
    root,context,sink=store
    run_id=str(uuid.uuid4()); run(sink.start(meta(run_id))); run(sink.finish(terminal(run_id)))
    log=root/run_id/'events.jsonl'
    log.write_bytes(log.read_bytes()[:-4])
    assert run(sink.read(run_id,context))['status']=='unknown'
