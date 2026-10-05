"""Local POSIX evidence: dirfd traversal, flock lifetime, fsync and atomic terminal.

Only a host-selected local filesystem with working flock/fsync is supported.
The hash chain detects accidental corruption, not a malicious filesystem owner.
"""
import errno
import fcntl
import os
import stat
import uuid
from pathlib import Path
from ..contracts.codec import canonical, decode, digest, plain
from ..contracts.ports import DurabilityAck, ReadContext
from .codec import EvidenceError, authorised, projection, record, terminal

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE = os.O_NOFOLLOW | os.O_CLOEXEC

def _run_id(value):
    try:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise EvidenceError('evidence_run_id') from None
    return value

def _root(path):
    absolute = Path(path).absolute()
    fd = os.open('/', _DIR)
    try:
        for part in absolute.parts[1:]:
            nxt = os.open(part, _DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            raise EvidenceError('evidence_root_permissions')
        return fd
    except BaseException:
        os.close(fd)
        raise

def _open_file(directory, name, flags):
    fd = os.open(name, flags | _FILE, 0o600, dir_fd=directory)
    if not stat.S_ISREG(os.fstat(fd).st_mode) or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
        os.close(fd)
        raise EvidenceError('evidence_file_permissions')
    return fd

def _write(fd, data):
    while data:
        written = os.write(fd, data)
        if not written: raise EvidenceError('evidence_write')
        data = data[written:]
    os.fsync(fd)

def _read(directory, name, limit):
    fd = _open_file(directory, name, os.O_RDONLY)
    try:
        if os.fstat(fd).st_size > limit: raise EvidenceError('evidence_limit')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit+1-size))
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
            if size > limit: raise EvidenceError('evidence_limit')
        return b''.join(chunks)
    finally: os.close(fd)

class FileEvidenceReader:
    def __init__(self, root, *, read_context, max_events=4096, max_record_bytes=65536):
        if not isinstance(read_context, ReadContext): raise EvidenceError('evidence_read_context')
        self.read_context = read_context
        self.max_events, self.max_record_bytes = max_events, max_record_bytes
        try: self._root_fd = _root(root)
        except OSError: raise EvidenceError('evidence_root') from None

    async def read(self, run_id, read_context):
        if not authorised(self.read_context, read_context): return {'status':'refused'}
        directory = lock = None
        try:
            _run_id(run_id)
            directory = os.open(run_id, _DIR, dir_fd=self._root_fd)
            if stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
                raise EvidenceError('evidence_directory_permissions')
            lock = _open_file(directory, 'writer.lock', os.O_RDWR)
            alive = False
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: alive = True
            data = _read(directory, 'events.jsonl', (self.max_events+1)*(self.max_record_bytes+1))
            if not data.endswith(b'\n'): raise EvidenceError('evidence_truncated')
            lines = data.splitlines()
            if not lines or len(lines)>self.max_events+1: raise EvidenceError('evidence_limit')
            events, previous = [], None
            for seq,line in enumerate(lines, 1):
                item = plain(decode(line, max_bytes=self.max_record_bytes))
                expected = record(item['payload'], seq, previous, self.max_record_bytes)
                if item != expected or item['payload'].get('run_id') != run_id:
                    raise EvidenceError('evidence_corrupt')
                events.append(item); previous = item['digest']
            if events[0]['payload'].get('type') != 'run.started': raise EvidenceError('evidence_started')
            commits = [e for e in events if e['payload'].get('type')=='terminal.commit']
            if commits and (len(commits)!=1 or commits[0] is not events[-1]):
                raise EvidenceError('evidence_commit_corrupt')
            committed = None
            try:
                raw = plain(decode(_read(directory, 'terminal.json', self.max_record_bytes), max_bytes=self.max_record_bytes))
                safe, td = terminal(raw['terminal'])
                # The completion receipt is appended only after the terminal's
                # rename AND directory fsync. A visible rename is not a commit.
                if alive or not commits: return {'status':'unknown'}
                commit = commits[0]
                if (raw['expected_last_seq'] != len(events)-1
                        or raw['last_digest'] != commit['prev_digest']
                        or raw['terminal_digest'] != td or safe.get('run_id') != run_id
                        or raw['digest'] != digest('event', {k:v for k,v in raw.items() if k!='digest'})
                        or commit['payload'].get('result_digest') != td
                        or commit['payload'].get('terminal_record_digest') != raw['digest']):
                    raise EvidenceError('evidence_terminal_corrupt')
                committed = safe
            except FileNotFoundError:
                if commits: return {'status':'unknown'}
            return projection(events, committed, alive=alive)
        except FileNotFoundError: return {'status':'not_found' if directory is None else 'unknown'}
        except (EvidenceError, KeyError, TypeError, ValueError): return {'status':'unknown'}
        except OSError as exc:
            return {'status':'refused' if exc.errno in (errno.EACCES, errno.EPERM, errno.ELOOP) else 'unavailable'}
        finally:
            if lock is not None: os.close(lock)
            if directory is not None: os.close(directory)

    async def close(self):
        if self._root_fd is not None: os.close(self._root_fd); self._root_fd = None

class FileEvidenceSink(FileEvidenceReader):
    durable = True
    def __init__(self, root, *, read_context, max_events=4096, max_record_bytes=65536):
        super().__init__(root, read_context=read_context, max_events=max_events, max_record_bytes=max_record_bytes)
        self._writers = {}
        self._terminals = {}

    async def start(self, meta):
        run_id = _run_id(meta.get('run_id'))
        directory = lock = log = None
        try:
            os.mkdir(run_id, 0o700, dir_fd=self._root_fd)
            os.fsync(self._root_fd)
            directory = os.open(run_id, _DIR, dir_fd=self._root_fd)
            lock = _open_file(directory, 'writer.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _write(lock, str(uuid.uuid4()).encode())
            log = _open_file(directory, 'events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND)
            os.fsync(directory)
            self._writers[run_id] = {'dir':directory, 'lock':lock, 'log':log, 'seq':0, 'digest':None, 'poisoned':False}
            return await self.append_durable(dict(meta, type='run.started'))
        except BaseException:
            self._writers.pop(run_id, None)
            for fd in (log, lock, directory):
                if fd is not None: os.close(fd)
            raise EvidenceError('evidence_start_failed') from None

    async def append_durable(self, event):
        if event.get('type',event.get('event')) == 'terminal.commit': raise EvidenceError('evidence_reserved_event')
        return self._append(event)

    def _append(self, event, *, completion=False):
        writer = self._writers.get(event.get('run_id'))
        if writer is None or writer['poisoned']: raise EvidenceError('evidence_writer')
        if writer['seq'] >= self.max_events+int(completion): raise EvidenceError('evidence_limit')
        item = record(event, writer['seq']+1, writer['digest'], self.max_record_bytes)
        try: _write(writer['log'], canonical(item, max_bytes=self.max_record_bytes)+b'\n')
        except BaseException:
            writer['poisoned'] = True
            raise EvidenceError('evidence_append_failed') from None
        writer['seq'], writer['digest'] = item['seq'], item['digest']
        return DurabilityAck(item['seq'], item['digest'], 'durable')

    async def finish(self, value):
        safe, td = terminal(value)
        run_id = safe.get('run_id')
        if run_id in self._terminals:
            old, ack = self._terminals[run_id]
            if old != safe: raise EvidenceError('terminal_conflict')
            return ack
        writer = self._writers.get(run_id)
        if writer is None or writer['poisoned']: raise EvidenceError('evidence_writer')
        if 'expected_last_seq' in safe and safe['expected_last_seq'] != writer['seq']:
            raise EvidenceError('evidence_terminal_sequence')
        payload = {'expected_last_seq':writer['seq'], 'last_digest':writer['digest'],
                   'terminal_digest':td, 'terminal':safe}
        payload['digest'] = digest('event', payload)
        fd = None
        try:
            fd = _open_file(writer['dir'], 'terminal.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            _write(fd, canonical(payload, max_bytes=self.max_record_bytes))
            os.close(fd); fd = None
            os.rename('terminal.tmp', 'terminal.json', src_dir_fd=writer['dir'], dst_dir_fd=writer['dir'])
            os.fsync(writer['dir'])
            self._append({'type':'terminal.commit','run_id':run_id,'result_digest':td,
                          'terminal_record_digest':payload['digest']}, completion=True)
        except BaseException:
            writer['poisoned'] = True
            raise EvidenceError('evidence_terminal_unknown') from None
        finally:
            if fd is not None: os.close(fd)
        ack = DurabilityAck(writer['seq'], td, 'durable')
        self._terminals[run_id] = (safe, ack)
        self._release(run_id)
        return ack

    def _release(self, run_id):
        writer = self._writers.pop(run_id)
        for key in ('log','lock','dir'): os.close(writer[key])

    async def close(self):
        for run_id in tuple(self._writers): self._release(run_id)
        await super().close()
