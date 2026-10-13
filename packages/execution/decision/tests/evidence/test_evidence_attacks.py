"""Evidence attack regressions submitted before fixes; run only by main.

No models, credentials, services or global directories are used. Close-fault
injection follows POSIX semantics: a reported close error may mean that the
descriptor has already been released and must never be closed a second time.
"""
import asyncio
import errno
import os
import uuid

import pytest

from decision_runtime.definitions.values import canonical, digest
from decision_runtime.evidence.codec import record
from decision_runtime.definitions.ports import ReadContext
from decision_runtime.evidence import EvidenceError, FileEvidenceReader, FileEvidenceSink, MemoryEvidenceSink


def run(awaitable):
    return asyncio.run(awaitable)


def meta(run_id):
    return {'run_id':run_id, 'request_digest':digest('request',{'test':'attacks'}),
            'flow_digest':digest('flow',{'test':'attacks'}),
            'manifest_digest':digest('runmanifest',{'test':'attacks'})}


def terminal(run_id, *, result_run_id=None, result_status='failed',
             wrapper_status='failed', manifest_digest=None):
    result = {'run_id':run_id if result_run_id is None else result_run_id,
              'status':result_status, 'error_code':'controlled_failure',
              'run_manifest_digest':meta(run_id)['manifest_digest'] if manifest_digest is None else manifest_digest}
    return {'run_id':run_id, 'status':wrapper_status, 'result':result,
            'terminal_digest':digest('result',result)}


@pytest.fixture
def store(tmp_path):
    tmp_path.chmod(0o700)
    context = ReadContext(object(),'test.attacks')
    sink = FileEvidenceSink(tmp_path,read_context=context)
    try:
        yield tmp_path,context,sink
    finally:
        run(sink.close())


def read_again(root,context,run_id):
    reader = FileEvidenceReader(root,read_context=context)
    try:
        return run(reader.read(run_id,context))
    finally:
        run(reader.close())


def test_duplicate_start_preserves_original_writer_and_releases_original_lock(store):
    root,context,sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    original = sink._writers[run_id]
    released = False
    try:
        with pytest.raises(EvidenceError):
            run(sink.start(meta(run_id)))
        ack = run(sink.append_durable({'type':'call.intent','run_id':run_id,'call_id':'original.call'}))
        assert ack.seq == 2
        live = run(sink.read(run_id,context))
        assert live['status'] == 'running'
        assert live['events'][-1]['payload']['call_id'] == 'original.call'
        run(sink.close()); released = True
        assert read_again(root,context,run_id)['status'] == 'interrupted'
    finally:
        # Duplicate-start RED loses management of these still-open fds. No new
        # descriptors have been opened on that failing path before this cleanup.
        if not released and run_id not in sink._writers:
            for key in ('log','lock','dir'):
                os.close(original[key])


def test_replaced_lock_path_never_proves_original_writer_exited(store):
    root,context,sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    directory = root/run_id
    (directory/'writer.lock').rename(directory/'original.lock')
    fd = os.open(directory/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    try:
        os.write(fd,str(uuid.uuid4()).encode('ascii'))
        os.fsync(fd)
    finally:
        os.close(fd)
    observation = read_again(root,context,run_id)
    assert observation['status'] == 'unknown'
    # The writer really is alive: its held descriptor and original journal are
    # still available. Only lock-path authority has become unprovable.
    assert run_id in sink._writers
    assert sink._writers[run_id]['seq'] == 1


def test_legacy_started_without_writer_identity_never_infers_interrupted(store):
    root,context,_ = store
    run_id = str(uuid.uuid4())
    directory = root/run_id
    directory.mkdir(mode=0o700)
    started = record(dict(meta(run_id),type='run.started'),1,None,65536)
    for filename,data in (('writer.lock',str(uuid.uuid4()).encode('ascii')),
                          ('events.jsonl',canonical(started)+b'\n')):
        fd = os.open(directory/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            assert os.write(fd,data)==len(data)
            os.fsync(fd)
        finally:
            os.close(fd)
    assert read_again(root,context,run_id)['status'] == 'unknown'


@pytest.mark.parametrize('backend',['file','memory'])
@pytest.mark.parametrize('mismatch',['run','status','manifest','missing_result'])
def test_terminal_rejects_cross_run_status_manifest_and_missing_result(store,backend,mismatch):
    _,context,file_sink = store
    sink = file_sink if backend=='file' else MemoryEvidenceSink(read_context=context)
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    value = terminal(run_id)
    if mismatch=='run':
        value = terminal(run_id,result_run_id=str(uuid.uuid4()))
    elif mismatch=='status':
        value = terminal(run_id,wrapper_status='completed',result_status='failed')
    elif mismatch=='manifest':
        value = terminal(run_id,manifest_digest=digest('runmanifest',{'test':'foreign'}))
    else:
        value.pop('result')
    try:
        with pytest.raises(EvidenceError):
            run(sink.finish(value))
        assert run(sink.read(run_id,context))['status'] == 'running'
        # A rejected envelope must not poison an otherwise valid live writer.
        run(sink.finish(terminal(run_id)))
        assert run(sink.read(run_id,context))['status'] == 'completed'
    finally:
        if backend=='memory': run(sink.close())


def test_close_eio_attempts_every_descriptor_once_and_raises_only_safe_code(store,monkeypatch):
    _,_,sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    writer = sink._writers[run_id]
    expected = (writer['log'],writer['lock'],writer['dir'],sink._root_fd)
    real_close = os.close
    calls = []

    def report_eio_after_release(fd):
        calls.append(fd)
        real_close(fd)
        if fd==expected[0]:
            raise OSError(errno.EIO,'SECRET_NATIVE_PATH')

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(os,'close',report_eio_after_release)
            with pytest.raises(EvidenceError) as caught:
                run(sink.close())
            assert 'SECRET_NATIVE_PATH' not in str(caught.value)
            assert all(calls.count(fd)==1 for fd in expected)
            assert not sink._writers
            assert sink._root_fd is None
    finally:
        # The RED baseline leaks the later descriptors. Release ONLY descriptors
        # that close never attempted; never retry an EIO-reported descriptor.
        for fd in expected:
            if fd not in calls:
                try: real_close(fd)
                except OSError: pass
        sink._writers.clear()
        sink._root_fd = None


def test_committed_terminal_survives_release_eio_and_never_reverses(store,monkeypatch):
    root,context,sink = store
    run_id = str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    writer = sink._writers[run_id]
    descriptors = (writer['log'],writer['lock'],writer['dir'])
    real_close = os.close
    calls = []
    def close_with_reported_eio(fd):
        calls.append(fd)
        real_close(fd)
        if fd==descriptors[0]: raise OSError(errno.EIO,'SECRET_RELEASE_FAILURE')
    with monkeypatch.context() as scoped:
        scoped.setattr(os,'close',close_with_reported_eio)
        with pytest.raises(EvidenceError) as caught:
            run(sink.finish(terminal(run_id)))
        assert 'SECRET_RELEASE_FAILURE' not in str(caught.value)
        assert all(calls.count(fd)==1 for fd in descriptors)
    result = read_again(root,context,run_id)
    assert result['status']=='completed'
    assert result['terminal']==terminal(run_id)
    assert run(sink.finish(terminal(run_id))).durability=='durable'
    with pytest.raises(EvidenceError):
        run(sink.finish(terminal(run_id,result_status='cancelled',wrapper_status='cancelled')))


def test_T24_T25_committed_archive_copy_retains_terminal_proof(store,tmp_path):
    import shutil
    root,context,sink=store
    run_id=str(uuid.uuid4())
    run(sink.start(meta(run_id)))
    value=terminal(run_id)
    run(sink.finish(value))
    archive=tmp_path/'archive';archive.mkdir(mode=0o700)
    shutil.copytree(root/run_id,archive/run_id)
    original=os.stat(root/run_id/'writer.lock')
    copied=os.stat(archive/run_id/'writer.lock')
    assert copied.st_ino!=original.st_ino
    observation=read_again(archive,context,run_id)
    assert observation['status']=='completed'
    assert observation['terminal']['terminal_digest']==value['terminal_digest']
