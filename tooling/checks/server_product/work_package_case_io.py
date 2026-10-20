"""Minimal case IO: one work package's declared inputs, verified and projected.

A work-package case is read from one explicit manifest that names each entry and
its source path. Every declared source is re-read and checked against its own
declared digest and byte length before anything is reported; a source that has
changed, moved or become unreadable refuses immediately with a named error --
nothing is guessed, downgraded, silently substituted or automatically retried.
A declared path is opened one segment at a time through directory descriptors
with ``O_NOFOLLOW`` -- each intermediate directory relative to the descriptor
opened for its parent, the final file relative to the descriptor of its own
directory -- so a symlinked parent directory, including one replaced by a symlink
between the check and the open, cannot carry the read out of the declared root:
an escaping path refuses before a single byte is read.

Reporting stays finite. Only the declared projection is returned, carrying the
original case and manifest references plus each entry's own path, digest and
byte length. Material bytes, credentials, keys and environment values are never
read into the report and never written back, and the manifest itself may not
carry a material or credential field.

This is deliberately not an architecture: there is no library search, no case
discovery and no second authority. It is the smallest IO that reads one declared
case, refuses on drift and reports a bounded projection. It starts no model,
provider or listener and consults no process environment.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any

from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_infrastructure.filesystem import (
    DirectoryReplacedError,
    PlatformUnsupportedError,
    UnsafeFileTypeError,
    UnsafePathError,
    open_directory_nofollow,
    open_directory_relative,
    open_regular_at,
)

SCHEMA = 'ordessa.work-package-case-io/1'

# Owner budgets for the two encodings this check performs: the declared manifest
# and the finite case projection it reports.
MANIFEST_MAX_BYTES = 64 * 1024
RESULT_MAX_BYTES = 32 * 1024

# The declared finite shapes. A manifest is exactly these keys, an entry is
# exactly these keys, and the report is exactly these keys -- so an undeclared
# key (a smuggled `material`, `content`, `credential` or environment value)
# cannot widen any of them.
MANIFEST_FIELDS = ('schema', 'case_ref', 'entries')
ENTRY_FIELDS = ('entry_id', 'source_path', 'sha256', 'byte_length')
CASE_IO_FIELDS = ('case_ref', 'manifest_ref', 'manifest_sha256', 'entries')

# A declared digest is the lowercase hex sha256 of the source bytes; the byte
# length is a non-negative integer. Anything else is a malformed declaration.
_SHA256 = re.compile(r'[0-9a-f]{64}')

# Named refusals. Every refusal carries one of these codes plus a fixed summary;
# the raw error text, message, module path or offending value is never reported.
ERROR_SUMMARIES = {
    'manifest_shape': 'Manifest shape refused',
    'unsupported_schema': 'Unsupported manifest schema',
    'source_missing': 'Declared source is missing',
    'source_not_regular': 'Declared source is not a regular file',
    'source_unreadable': 'Declared source is unreadable',
    'source_changed': 'Declared source changed',
    'source_escapes_root': 'Declared source escapes the root',
    'root_refused': 'Source root refused',
    'unexpected': 'Unclassified error',
}
_CLASS_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')


class CaseIOError(Exception):
    """A named case-IO refusal.

    `code` is one of `ERROR_SUMMARIES`. `entry_id` and `source_path` name the
    declared entry that refused when one is known; both are values the manifest
    already declares, so they carry no material or credential.
    """

    code = 'manifest_shape'

    def __init__(self, code: str, *, entry_id: str | None = None,
                 source_path: str | None = None) -> None:
        if code not in ERROR_SUMMARIES:
            raise ValueError('unknown case-io error code')
        self.code = code
        self.entry_id = entry_id
        self.source_path = source_path
        super().__init__(code)


def digest(raw: bytes) -> str:
    """The lowercase hex sha256 of raw bytes -- the declared digest form."""
    return hashlib.sha256(raw).hexdigest()


def bounded(fields: Mapping[str, Any], order: Sequence[str]) -> dict:
    """Project a mapping onto the declared field list, in that order.

    This is the finite-projection primitive: undeclared keys cannot leak, and a
    declared key that is missing raises (KeyError) instead of silently reading
    as absent.
    """
    return {field: fields[field] for field in order}


def error_class_name(error: BaseException) -> str:
    """A bounded class identifier, never a module path, message or attribute."""
    name = type(error).__qualname__.rsplit('.', 1)[-1]
    return name if _CLASS_NAME.fullmatch(name) else 'UnclassifiedError'


def error_record(error: BaseException) -> dict:
    """Reduce a caught error to its named code, a fixed summary and a class name."""
    code = getattr(error, 'code', 'unexpected')
    if code not in ERROR_SUMMARIES:
        code = 'unexpected'
    return {'error_code': code, 'error_summary': ERROR_SUMMARIES[code],
            'error_class': error_class_name(error)}


def _exact_keys(value: Mapping[str, Any], allowed: Sequence[str]) -> None:
    """Refuse any key outside the declared set; a missing key is refused by caller."""
    if set(value) - set(allowed):
        raise CaseIOError('manifest_shape')


def _is_relative_source(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and '..' not in path.parts


def _load_entry(value: Any) -> dict:
    if not isinstance(value, Mapping):
        raise CaseIOError('manifest_shape')
    _exact_keys(value, ENTRY_FIELDS)
    for field in ENTRY_FIELDS:
        if field not in value:
            raise CaseIOError('manifest_shape')
    entry_id, source_path = value['entry_id'], value['source_path']
    if not isinstance(entry_id, str) or not entry_id:
        raise CaseIOError('manifest_shape')
    if not _is_relative_source(source_path):
        raise CaseIOError('manifest_shape', entry_id=entry_id)
    sha = value['sha256']
    if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
        raise CaseIOError('manifest_shape', entry_id=entry_id, source_path=source_path)
    length = value['byte_length']
    if type(length) is not int or length < 0:
        raise CaseIOError('manifest_shape', entry_id=entry_id, source_path=source_path)
    return bounded(value, ENTRY_FIELDS)


def load_manifest(value: Any) -> dict:
    """Validate an explicit case manifest and return its declared projection.

    Unknown keys are refused (a manifest may not smuggle material, credentials
    or environment values), the schema must be the declared one, entries must be
    non-empty with unique ids, and every entry must name a relative source path
    with a lowercase sha256 and a non-negative byte length.
    """
    if not isinstance(value, Mapping):
        raise CaseIOError('manifest_shape')
    _exact_keys(value, MANIFEST_FIELDS)
    for field in MANIFEST_FIELDS:
        if field not in value:
            raise CaseIOError('manifest_shape')
    if value['schema'] != SCHEMA:
        raise CaseIOError('unsupported_schema')
    case_ref = value['case_ref']
    if not isinstance(case_ref, str) or not case_ref:
        raise CaseIOError('manifest_shape')
    entries = value['entries']
    if (not isinstance(entries, Sequence) or isinstance(entries, (str, bytes))
            or not entries):
        raise CaseIOError('manifest_shape')
    seen: set[str] = set()
    projected = []
    for raw in entries:
        entry = _load_entry(raw)
        if entry['entry_id'] in seen:
            raise CaseIOError('manifest_shape', entry_id=entry['entry_id'])
        seen.add(entry['entry_id'])
        projected.append(entry)
    return {'schema': SCHEMA, 'case_ref': case_ref, 'entries': projected}


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """The original reference to the exact declared manifest, as canonical bytes."""
    return digest(safe_json(manifest, max_bytes=MANIFEST_MAX_BYTES).encode())


def _open_root_directory(root: Path) -> int:
    """Open the trusted root as a directory descriptor, refusing an unsafe root.

    The root is the caller's trust anchor; it is opened through the shared
    filesystem mechanism with no-follow semantics and an identity check, so the
    per-segment walk below never starts from an unverified directory. Any
    refusal here is reported as `root_refused`.
    """
    try:
        return open_directory_nofollow(root)
    except (UnsafeFileTypeError, DirectoryReplacedError, PlatformUnsupportedError, OSError):
        raise CaseIOError('root_refused')


def _component_is_symlink(parent_fd: int, name: str) -> bool:
    """Classify a component the directory open has already refused.

    ``O_NOFOLLOW|O_DIRECTORY`` reports a symlink and a plain non-directory alike
    as ``ENOTDIR``; this distinguishes them so the refusal keeps its meaning (a
    symlink escapes the root, a plain non-directory is a broken declaration).
    It runs only *after* the open already failed, so no byte was read and no
    follow was taken -- it merely selects the refusal code and cannot reopen the
    check-then-read window.
    """
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode)


def _open_walked_directory(parent_fd: int, name: str, entry_id: str, source_path: str) -> int:
    """Open one intermediate segment as O_NOFOLLOW|O_DIRECTORY under ``parent_fd``.

    The open is relative to the descriptor of the segment's own parent, so a
    parent directory replaced by a symlink to an outside directory cannot be
    followed: the mechanism refuses the symlink (or a non-directory) and this
    owner reports `source_escapes_root`. A missing or plainly non-directory
    segment is reported as `source_missing`; any other failure as
    `source_unreadable`.
    """
    try:
        return open_directory_relative(parent_fd, name)
    except (UnsafePathError, UnsafeFileTypeError, PlatformUnsupportedError):
        raise CaseIOError('source_escapes_root', entry_id=entry_id, source_path=source_path)
    except OSError as error:
        if error.errno == errno.ENOENT:
            raise CaseIOError('source_missing', entry_id=entry_id, source_path=source_path)
        if error.errno == errno.ENOTDIR:
            code = ('source_escapes_root' if _component_is_symlink(parent_fd, name)
                    else 'source_missing')
            raise CaseIOError(code, entry_id=entry_id, source_path=source_path)
        raise CaseIOError('source_unreadable', entry_id=entry_id, source_path=source_path)


def _read_walked_file(directory_fd: int, name: str, entry_id: str, source_path: str) -> bytes:
    """Open the final segment as O_NOFOLLOW under ``directory_fd`` and read it.

    The file is opened relative to the descriptor of its own directory with the
    no-follow guarantee, so a symlinked or non-regular final component refuses
    as `source_not_regular` rather than being followed. Only a descriptor the
    mechanism already confirmed to be a regular file is read; the bytes are
    returned to the caller and never retained here.
    """
    try:
        descriptor = open_regular_at(directory_fd, name)
    except UnsafePathError:
        raise CaseIOError('source_escapes_root', entry_id=entry_id, source_path=source_path)
    except (UnsafeFileTypeError, PlatformUnsupportedError):
        raise CaseIOError('source_not_regular', entry_id=entry_id, source_path=source_path)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR):
            raise CaseIOError('source_missing', entry_id=entry_id, source_path=source_path)
        raise CaseIOError('source_unreadable', entry_id=entry_id, source_path=source_path)
    try:
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            return stream.read()
    except OSError:
        raise CaseIOError('source_unreadable', entry_id=entry_id, source_path=source_path)
    finally:
        os.close(descriptor)


def _read_declared_source(root: Path, source_path: str, entry_id: str) -> bytes:
    """Read one declared source through dirfd-relative, no-follow opens.

    An absolute path or a `..` component refuses as `source_escapes_root` before
    the root is even opened. Otherwise the declared path is opened one component
    at a time from a descriptor on the trusted root: every intermediate
    directory is opened with `O_NOFOLLOW|O_DIRECTORY` relative to the descriptor
    of its parent, and the final file is opened with `O_NOFOLLOW` relative to
    the descriptor of its own directory. A component that is a symlink --
    including a parent directory replaced by a symlink to an outside directory
    -- makes the open refuse, so no byte of an escaping target is ever read. The
    opened descriptors are closed on every path.
    """
    if not _is_relative_source(source_path):
        raise CaseIOError('source_escapes_root', entry_id=entry_id, source_path=source_path)
    parts = Path(source_path).parts
    if not parts:
        raise CaseIOError('source_not_regular', entry_id=entry_id, source_path=source_path)
    root_fd = _open_root_directory(root)
    try:
        directory_fd = root_fd
        opened: list[int] = []
        try:
            for part in parts[:-1]:
                child = _open_walked_directory(directory_fd, part, entry_id, source_path)
                opened.append(child)
                directory_fd = child
            return _read_walked_file(directory_fd, parts[-1], entry_id, source_path)
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)
    finally:
        os.close(root_fd)


def verify_entry(entry: Mapping[str, Any], root: Path) -> dict:
    """Re-read one declared source and refuse on any drift, without retrying.

    The declared source path is opened one segment at a time with no-follow
    semantics first: an absolute path, a `..` component or a symlinked (or
    replaced) parent directory refuses as `source_escapes_root` before a single
    byte is read. Only then is the source checked for regular-file form and a
    matching digest and byte length. Returns the entry's declared projection
    (path, digest, byte length). The source bytes themselves are never returned,
    retained or reported.
    """
    entry_id, source_path = entry['entry_id'], entry['source_path']
    raw = _read_declared_source(Path(root), source_path, entry_id)
    if len(raw) != entry['byte_length'] or digest(raw) != entry['sha256']:
        raise CaseIOError('source_changed', entry_id=entry_id, source_path=source_path)
    return bounded(entry, ENTRY_FIELDS)


def _verify_loaded(manifest: Mapping[str, Any], root: Path) -> list[dict]:
    """Verify every declared entry against its source, refusing at the first drift."""
    root = Path(root)
    if not root.is_dir():
        raise CaseIOError('root_refused')
    return [verify_entry(entry, root) for entry in manifest['entries']]


def verify_manifest(value: Any, root: Path) -> dict:
    """Validate and verify a manifest; a drifted source refuses before any report."""
    manifest = load_manifest(value)
    return {'case_ref': manifest['case_ref'], 'entries': _verify_loaded(manifest, root)}


def project_case_io(value: Any, root: Path, *, manifest_ref: str) -> dict:
    """The finite case projection: verified entries plus the original references.

    Only the declared projection is reported. Material bytes, credentials, keys
    and environment values never appear; the original case ref, manifest ref and
    per-entry source path and digest are preserved so a caller can reconcile the
    case without re-reading any material.
    """
    if not isinstance(manifest_ref, str) or not manifest_ref:
        raise CaseIOError('manifest_shape')
    manifest = load_manifest(value)
    projection = {'case_ref': manifest['case_ref'], 'manifest_ref': manifest_ref,
                  'manifest_sha256': manifest_digest(manifest),
                  'entries': _verify_loaded(manifest, root)}
    return bounded(projection, CASE_IO_FIELDS)


def serialize_projection(projection: Mapping[str, Any]) -> str:
    """Canonical bounded text of a finite projection."""
    return safe_json(projection, max_bytes=RESULT_MAX_BYTES)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--manifest-ref', default=None,
                        help='the original manifest reference to preserve '
                             '(default: the manifest path as given)')
    args = parser.parse_args(argv)
    manifest_ref = args.manifest_ref if args.manifest_ref is not None else str(args.manifest)
    try:
        manifest = load_manifest(json.loads(args.manifest.read_text(encoding='utf-8')))
        projection = project_case_io(manifest, args.root, manifest_ref=manifest_ref)
    except Exception as error:
        print(json.dumps(error_record(error), sort_keys=True))
        return 1
    print(serialize_projection(projection))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
