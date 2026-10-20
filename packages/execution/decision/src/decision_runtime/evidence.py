"""Summary-only durable evidence with atomic, fsynced writes and verified reads.

Write protocol: open a fresh temp file in the store directory, write canonical
bytes, fsync the file, close, atomically `os.replace` onto the digest name, then
fsync the directory. A reader therefore only ever sees a complete canonical file
under its own digest; a torn/partial temp file is never addressed and is removed
on the next successful write. Reads re-verify both the summary shape and the
content digest, so a tampered or truncated final file is refused.
"""
from __future__ import annotations

import os
import tempfile
import re
import stat
from contextlib import contextmanager
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path

from .definitions.values import DecisionError, MAX_VALUE_BYTES, canonical_bytes, decode_json, digest_hex

_ALLOWED = {"job_digest", "input_digest", "steps", "answers", "usage", "result_digest",
            "skipped", "engine", "provider", "call_evidence", "receipt"}
_FORBIDDEN = ("prompt", "response", "text", "messages", "secret", "api_key")


def check_summary(summary) -> dict:
    if type(summary) is not dict or not set(summary) <= _ALLOWED:
        raise DecisionError("invalid_evidence")
    if type(summary.get("job_digest")) is not str:
        raise DecisionError("invalid_evidence")
    if any(key in summary for key in _FORBIDDEN):
        raise DecisionError("invalid_evidence")
    return summary


@dataclass(frozen=True)
class EvidenceRef:
    digest: str
    byte_length: int
    durability: str = "durable"   # durable | directory_sync_unknown


@dataclass(frozen=True)
class EvidenceScope:
    """Existing authority namespace data; this value confers no access."""
    kind: str
    ref: str

    def __post_init__(self):
        if (self.kind not in ('principal','project') or type(self.ref) is not str
                or not self.ref or len(self.ref.encode('utf-8'))>512
                or any(ord(c)<32 or ord(c)==127 for c in self.ref)):
            raise DecisionError('invalid_evidence_scope')

    def projection(self):
        return {'schemaVersion':'decision-evidence-scope/1','kind':self.kind,'ref':self.ref}


class FilesystemEvidenceStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def scoped(self, scope: EvidenceScope):
        if type(scope) is not EvidenceScope:
            raise DecisionError('invalid_evidence_scope')
        return _ScopedEvidenceStore(self.root,scope)

    def _target(self, digest: str) -> Path:
        return self.root / (digest + ".json")

    def put(self, summary) -> EvidenceRef:
        """Write once, atomically. Same bytes are idempotent; different bytes conflict.

        If the atomic rename succeeded but the directory fsync failed, the bytes
        are already visible under their digest: the returned reference says so
        (`directory_sync_unknown`) and the existing correct file is never removed.
        """
        check_summary(summary)
        body = canonical_bytes(summary)
        digest = digest_hex(summary)
        target = self._target(digest)
        if target.exists():
            if target.read_bytes() != body:
                raise DecisionError("evidence_conflict")
            return EvidenceRef(digest, len(body))
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        replaced = False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(name, target)
            except FileExistsError:
                # A concurrent writer won the rename; identical bytes are fine.
                if target.read_bytes() != body:
                    raise DecisionError("evidence_conflict") from None
                replaced = True
            else:
                replaced = True
        except BaseException:
            if not replaced:
                try:
                    os.unlink(name)
                except OSError:
                    pass
            raise
        durability = "durable"
        try:
            self._fsync_directory()
        except OSError:
            durability = "directory_sync_unknown"
        return EvidenceRef(digest, len(body), durability)

    def _fsync_directory(self) -> None:
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def get(self, ref):
        digest = ref.digest if isinstance(ref, EvidenceRef) else ref
        if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}',digest) is None:
            raise DecisionError("invalid_evidence_ref")
        target = self._target(digest)
        if not target.is_file():
            raise DecisionError("evidence_unavailable")
        raw = target.read_bytes()
        summary = decode_json(raw)
        check_summary(summary)
        if digest_hex(summary) != digest or canonical_bytes(summary) != raw:
            raise DecisionError("evidence_tampered")
        return summary


class _ScopedEvidenceStore(FilesystemEvidenceStore):
    """A view of the SAME original owner, with scope in the physical lookup.

    Historical unscoped files are never read or adopted by this view. Selecting
    the view is trusted composition's job; the capability verifies that choice
    from its current externally authenticated invocation on every operation.
    """
    def __init__(self, root, scope):
        self.scope=scope
        self.root=root/'scopes'/digest_hex(scope.projection())

    def scoped(self,scope):
        raise DecisionError('evidence_scope_already_bound')

    @contextmanager
    def _directory(self, *, create=False):
        # Pin every directory component and reject links. All subsequent opens,
        # links and unlinks are relative to the pinned final directory fd, so a
        # concurrent path replacement cannot redirect an in-progress operation.
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        fd=None
        try:
            parts=self.root.absolute().parts
            fd=os.open(parts[0],flags)
            for part in parts[1:]:
                if create:
                    try:os.mkdir(part,0o700,dir_fd=fd)
                    except FileExistsError:pass
                    # Also sync an existing entry: a concurrent first creator
                    # may not yet have synced its parent, and the configured
                    # root itself may have just been created by composition.
                    os.fsync(fd)
                child=os.open(part,flags,dir_fd=fd)
                os.close(fd);fd=child
            yield fd
        except OSError:
            raise DecisionError('evidence_scope_unavailable') from None
        finally:
            if fd is not None:os.close(fd)

    @staticmethod
    def _read_file(directory,name):
        descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        try:
            facts=os.fstat(descriptor)
            if not stat.S_ISREG(facts.st_mode) or facts.st_size>MAX_VALUE_BYTES:
                raise DecisionError('invalid_evidence_file')
            # Bound reads even if a concurrent actor grows the same inode.
            with os.fdopen(descriptor,'rb',closefd=False) as stream:
                raw=stream.read(MAX_VALUE_BYTES+1)
            if len(raw)>MAX_VALUE_BYTES:raise DecisionError('invalid_evidence_file')
            return raw
        finally:os.close(descriptor)

    def _atomic_create(self,directory,name,body, *, compare=True):
        temporary='.pending-'+uuid4().hex
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
            0o600,dir_fd=directory)
        try:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(body);stream.flush();os.fsync(stream.fileno())
            try:
                os.link(temporary,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
            except FileExistsError:
                if compare and self._read_file(directory,name)!=body:
                    raise DecisionError('evidence_conflict') from None
                return False
            return True
        finally:os.unlink(temporary,dir_fd=directory)

    def _verify_scope(self,directory, *, create=False):
        expected=canonical_bytes(self.scope.projection())
        if create:
            try:self._read_file(directory,'.scope.json')
            except FileNotFoundError:
                self._atomic_create(directory,'.scope.json',expected)
                os.fsync(directory)
        if self._read_file(directory,'.scope.json')!=expected:
            raise DecisionError('evidence_scope_invalid')

    def verify_scope(self, *, for_write=False):
        """Validate original namespace storage before any rules/model effects.

        The caller has already obtained external access; this only checks bytes
        and directories and never grants access or adopts historical artifacts.
        """
        with self._directory(create=for_write) as directory:
            self._verify_scope(directory,create=for_write)

    def put(self,summary):
        check_summary(summary);body=canonical_bytes(summary);digest=digest_hex(summary)
        with self._directory(create=True) as directory:
            self._verify_scope(directory,create=True)
            self._atomic_create(directory,digest+'.json',body)
            durability='durable'
            try:os.fsync(directory)
            except OSError:durability='directory_sync_unknown'
            return EvidenceRef(digest,len(body),durability)

    def get(self,ref):
        digest=ref.digest if isinstance(ref,EvidenceRef) else ref
        if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}',digest) is None:
            raise DecisionError('invalid_evidence_ref')
        with self._directory() as directory:
            self._verify_scope(directory)
            raw=self._read_file(directory,digest+'.json')
        summary=decode_json(raw);check_summary(summary)
        if digest_hex(summary)!=digest:raise DecisionError('evidence_tampered')
        return summary

    def claim_run(self,request_id,request_digest):
        """Original decision-run reservation BEFORE any runner/model effect.

        Immutable claim and result are two files of one original run record;
        absence of result after a crash is unknown, never a new execution right.
        The created flag is returned only by this atomic first claim and is not
        serialized as a permission or reconstructed from historical JSON.
        """
        if (type(request_id) is not str or not request_id or len(request_id)>512
                or any(ord(c)<32 or ord(c)==127 for c in request_id)
                or type(request_digest) is not str or re.fullmatch(r'[0-9a-f]{64}',request_digest) is None):
            raise DecisionError('invalid_run_request')
        key=digest_hex({'requestId':request_id})
        operation='decision-run/'+digest_hex({'scope':self.scope.projection(),'requestId':request_id})
        claim={'schemaVersion':'decision-run-claim/1','requestDigest':request_digest,'operationRef':operation}
        with self._directory(create=True) as directory:
            self._verify_scope(directory,create=True)
            try:self._read_file(directory,'.run-'+key+'.json')
            except FileNotFoundError:
                # A result without its original claim is damaged history, not
                # a new operation. Never repair/adopt it by issuing a new claim.
                try:self._read_file(directory,'.run-result-'+key+'.json')
                except FileNotFoundError:pass
                else:raise DecisionError('run_record_corrupt')
            created=self._atomic_create(directory,'.run-'+key+'.json',canonical_bytes(claim),compare=False)
            if created:os.fsync(directory)
            stored=decode_json(self._read_file(directory,'.run-'+key+'.json'))
            if type(stored) is not dict or set(stored)!=set(claim) or stored.get('schemaVersion')!=claim['schemaVersion'] or stored.get('operationRef')!=operation:
                raise DecisionError('run_record_corrupt')
            if stored.get('requestDigest')!=request_digest:raise DecisionError('run_request_conflict')
            try:result=decode_json(self._read_file(directory,'.run-result-'+key+'.json'))
            except FileNotFoundError:result=None
            if result is not None:
                if created:raise DecisionError('run_record_corrupt')
                if type(result) is not dict or set(result)!={'schemaVersion','claimDigest','resultDigest','result'} or result['schemaVersion']!='decision-run-result/1' or result['claimDigest']!=digest_hex(claim) or result['resultDigest']!=digest_hex(result['result']):
                    raise DecisionError('run_record_corrupt')
                result=result['result']
            return created,operation,result

    def read_run(self,request_id,request_digest):
        """Read an existing original claim/result without reserving or replaying.

        This scoped owner port issues no access. Trusted callers must retain
        their existing read authority. Missing or pending records never create
        a claim or confer permission to run again. Existing on-disk formats and
        digest bindings are exactly those used by claim_run/complete_run.
        """
        if (type(request_id) is not str or not request_id or len(request_id)>512
                or any(ord(c)<32 or ord(c)==127 for c in request_id)
                or type(request_digest) is not str or re.fullmatch(r'[0-9a-f]{64}',request_digest) is None):
            raise DecisionError('invalid_run_request')
        key=digest_hex({'requestId':request_id})
        operation='decision-run/'+digest_hex({'scope':self.scope.projection(),'requestId':request_id})
        expected={'schemaVersion':'decision-run-claim/1','requestDigest':request_digest,'operationRef':operation}
        with self._directory() as directory:
            self._verify_scope(directory)
            try:claim=decode_json(self._read_file(directory,'.run-'+key+'.json'))
            except FileNotFoundError:raise DecisionError('run_not_found') from None
            if type(claim) is not dict or set(claim)!=set(expected) or claim.get('schemaVersion')!=expected['schemaVersion'] or claim.get('operationRef')!=operation:
                raise DecisionError('run_record_corrupt')
            if claim.get('requestDigest')!=request_digest:
                raise DecisionError('run_request_conflict')
            try:recorded=decode_json(self._read_file(directory,'.run-result-'+key+'.json'))
            except FileNotFoundError:return operation,None
            if (type(recorded) is not dict or set(recorded)!={'schemaVersion','claimDigest','resultDigest','result'}
                    or recorded['schemaVersion']!='decision-run-result/1'
                    or recorded['claimDigest']!=digest_hex(claim)
                    or recorded['resultDigest']!=digest_hex(recorded['result'])):
                raise DecisionError('run_record_corrupt')
            return operation,recorded['result']

    def complete_run(self,request_id,request_digest,result):
        key=digest_hex({'requestId':request_id})
        with self._directory() as directory:
            self._verify_scope(directory)
            claim=decode_json(self._read_file(directory,'.run-'+key+'.json'))
            if claim.get('requestDigest')!=request_digest:raise DecisionError('run_request_conflict')
            body=canonical_bytes({'schemaVersion':'decision-run-result/1','claimDigest':digest_hex(claim),'resultDigest':digest_hex(result),'result':result})
            self._atomic_create(directory,'.run-result-'+key+'.json',body)
            os.fsync(directory)
