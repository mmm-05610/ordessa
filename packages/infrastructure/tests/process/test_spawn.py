"""Real, test-owned subprocesses only; no product services or model calls."""
import os
import select
import signal
import subprocess
import sys

import pytest

from ordessa_infrastructure.process import SubprocessHandle, spawn_process


def ready(handle):
    assert select.select([handle.stdout], [], [], 5)[0], 'test process readiness timeout'
    assert handle.stdout.readline() == b'ready\n'


@pytest.fixture
def start(tmp_path):
    handles = []

    def launch(code, *, env=None):
        handle = spawn_process([sys.executable, '-I', '-c', code], cwd=str(tmp_path), env=env or {})
        handles.append(handle)
        return handle

    yield launch
    for handle in handles:
        if handle.poll() is None:
            handle.kill()
        handle.wait(timeout=5)
        handle.close_streams()


def test_real_byte_streams_pid_environment_and_working_directory(start, tmp_path):
    handle = start("import os,sys; "
                   "sys.stdout.buffer.write(os.getcwd().encode()+b'\\n'+os.environ['MARK'].encode()+b'\\n'+sys.stdin.buffer.read()); "
                   "sys.stderr.buffer.write(b'error\\x00')", env={'MARK': 'exact'})
    assert isinstance(handle, SubprocessHandle)
    assert handle.pid == handle.popen.pid > 0
    assert handle.stdin is handle.popen.stdin
    assert handle.stdout is handle.popen.stdout
    assert handle.stderr is handle.popen.stderr
    out, err = handle.popen.communicate(b'\x00\xffbytes', timeout=5)
    assert out == str(tmp_path).encode() + b'\nexact\n\x00\xffbytes'
    assert err == b'error\x00'
    assert handle.returncode == handle.poll() == handle.wait(timeout=5) == 0


def test_argv_is_not_interpreted_by_shell(tmp_path):
    target = tmp_path / 'must-not-exist'
    arg = f'; touch {target}'
    handle = spawn_process([sys.executable, '-I', '-c', 'import sys;print(sys.argv[1])', arg],
                           cwd=str(tmp_path), env={})
    try:
        out, err = handle.popen.communicate(timeout=5)
        assert out == (arg + '\n').encode()
        assert not target.exists()
        assert err == b''
    finally:
        if handle.poll() is None:
            handle.kill()
        handle.wait(timeout=5)
        handle.close_streams()


def test_wait_timeout_does_not_terminate_or_close_streams(start):
    handle = start('import sys,time; print("ready",flush=True); time.sleep(30)')
    ready(handle)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        handle.wait(timeout=0.01)
    assert caught.value.timeout == 0.01
    assert handle.poll() is None
    assert all(not stream.closed for stream in (handle.stdin, handle.stdout, handle.stderr))
    handle.terminate()
    assert handle.wait(timeout=5) == -signal.SIGTERM


def test_owner_can_escalate_ignored_terminate_to_kill(start):
    handle = start('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                   'print("ready",flush=True); time.sleep(30)')
    ready(handle)
    handle.terminate()
    with pytest.raises(subprocess.TimeoutExpired):
        handle.wait(timeout=0.05)
    handle.kill()
    assert handle.wait(timeout=5) == -signal.SIGKILL


def test_send_signal_and_close_only_owned_streams(start):
    first = start('import time; print("ready",flush=True); time.sleep(30)')
    second = start('import time; print("ready",flush=True); time.sleep(30)')
    ready(first)
    ready(second)
    first.close_streams()
    first.close_streams()
    assert first.poll() is None  # closing pipes is not process cancellation
    assert all(s.closed for s in (first.stdin, first.stdout, first.stderr))
    assert all(not s.closed for s in (second.stdin, second.stdout, second.stderr))
    first.send_signal(signal.SIGTERM)
    assert first.wait(timeout=5) == -signal.SIGTERM
    assert second.poll() is None


def test_nonzero_exit_is_native_outcome(start):
    handle = start('import sys; sys.exit(23)')
    assert handle.wait(timeout=5) == handle.returncode == 23


def test_failed_start_does_not_provision_directories_or_leak_pipes(tmp_path):
    # Linux fd inventory detects leaked parent ends after Popen raises.
    before = set(os.listdir('/proc/self/fd'))
    for _ in range(5):
        with pytest.raises(FileNotFoundError):
            spawn_process([str(tmp_path / 'missing-executable')], cwd=str(tmp_path), env={})
        missing = tmp_path / 'not-provisioned'
        with pytest.raises(FileNotFoundError):
            spawn_process([sys.executable], cwd=str(missing), env={})
        assert not missing.exists()
    assert set(os.listdir('/proc/self/fd')) == before


def test_successful_exit_and_explicit_close_release_parent_pipes(start):
    handle = start('pass')
    fds = [s.fileno() for s in (handle.stdin, handle.stdout, handle.stderr)]
    handle.wait(timeout=5)
    # wait/reap deliberately leaves pipe ownership with caller.
    for fd in fds:
        os.fstat(fd)
    handle.close_streams()
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)
