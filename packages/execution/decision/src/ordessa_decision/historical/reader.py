"""Preserved original evidence reader only; no sink, runner or new-run writes.

Reads historical decision-evidence/1 chains under explicit opaque read authority.
This module neither interprets history as a new execution right nor upgrades it.
"""
import errno
import fcntl
import os
import stat
import uuid
from pathlib import Path
from .values import canonical, decode, digest, plain
from .context import ReadContext
from .codec import EvidenceError, authorised, projection, record, terminal, summary, require_terminal_binding

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE = os.O_NOFOLLOW | os.O_CLOEXEC

def _close_once(descriptors):
    """Attempt each owned fd once; POSIX close errors may already release it."""
    failed = False
    for fd in descriptors:
        if fd is not None:
            try: os.close(fd)
            except OSError: failed = True
    if failed: raise EvidenceError('evidence_cleanup_failed') from None

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
        if self._root_fd is None: return {'status':'unavailable'}
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
            started = events[0]['payload']
            identity_fields = {'writer_incarnation','writer_device','writer_inode'}
            present = identity_fields.intersection(started)
            identity_verified = False
            if present:
                if present != identity_fields: raise EvidenceError('evidence_writer_identity')
                incarnation = _run_id(started['writer_incarnation'])
                if any(type(started[k]) is not int or started[k]<0 for k in ('writer_device','writer_inode')):
                    raise EvidenceError('evidence_writer_identity')
                held = os.fstat(lock)
                named = os.stat('writer.lock',dir_fd=directory,follow_symlinks=False)
                if os.pread(lock,257,0) != incarnation.encode('ascii'):
                    raise EvidenceError('evidence_writer_identity')
                identity_verified = ((held.st_dev,held.st_ino)==(started['writer_device'],started['writer_inode'])
                    and (named.st_dev,named.st_ino)==(held.st_dev,held.st_ino))
                # A copied durable terminal is proved by its exact commit chain,
                # not the archive's new inode. Nonterminal liveness still needs
                # the original held inode and can never use this relaxation.
            commits = [e for e in events if e['payload'].get('type')=='terminal.commit']
            if commits and (len(commits)!=1 or commits[0] is not events[-1]):
                raise EvidenceError('evidence_commit_corrupt')
            committed = None
            try:
                raw = plain(decode(_read(directory, 'terminal.json', self.max_record_bytes), max_bytes=self.max_record_bytes))
                safe, td = terminal(raw['terminal'])
                require_terminal_binding(safe,started)
                # The completion receipt is appended only after the terminal's
                # rename AND directory fsync. A visible rename is not a commit.
                if alive or not commits: return {'status':'unknown'}
                commit = commits[0]
                if (raw['expected_last_seq'] != len(events)-1
                        or raw['last_digest'] != commit['prev_digest']
                        # Older decision-evidence/1 receipts bind this digest
                        # through the envelope digest and terminal.commit event.
                        # Accept that exact legacy shape without rewriting it.
                        or raw.get('terminal_digest', td) != td or safe.get('run_id') != run_id
                        or raw['digest'] != digest('event', {k:v for k,v in raw.items() if k!='digest'})
                        or commit['payload'].get('result_digest') != td
                        or commit['payload'].get('terminal_record_digest') != raw['digest']):
                    raise EvidenceError('evidence_terminal_corrupt')
                committed = safe
            except FileNotFoundError:
                if commits: return {'status':'unknown'}
            if committed is None and not identity_verified: return {'status':'unknown'}
            return projection(events, committed, alive=alive)
        except FileNotFoundError: return {'status':'not_found' if directory is None else 'unknown'}
        except (EvidenceError, KeyError, TypeError, ValueError): return {'status':'unknown'}
        except OSError as exc:
            return {'status':'refused' if exc.errno in (errno.EACCES, errno.EPERM, errno.ELOOP) else 'unavailable'}
        finally:
            _close_once((lock,directory))

    async def close(self):
        root,self._root_fd = self._root_fd,None
        _close_once((root,))
