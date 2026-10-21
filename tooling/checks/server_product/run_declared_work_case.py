"""Preparation and (gated) execution entry for one declared-Work case.

Project-internal replacement for the private ``/tmp`` operator. It keeps the
operator's actual protections and adds no generic framework: one case, one
frozen data-root clone, one formally worked action.

Layers, all explicit:

``pins``        frozen source manifest, target baseline, handed-off operator
                bytes, recovered check configuration and check candidate - each
                refused on drift; no pin is ever rewritten here.
``clone``       the whole frozen data root is copied byte-for-byte into a new,
                exclusively created directory and verified against a complete
                manifest before anything opens it. Every ``*.sqlite`` in the
                clone is then checkpointed *inside the clone* and its sidecars
                removed, so the original owner library can open it read-only.
                The original root is never opened for writing and the helper
                that hard-codes the original root is never executed.
``evidence``    the Grant/control/budget come from the **cloned owner
                records** (``uow.authorization``) and from the formal
                ``engineering.work.get``; the evidence JSON only names the
                Grant reference and the expected values, and every claim it
                makes is compared with those owner records. This entry never
                mints a Grant, an answer or a challenge.
``execute``     ``execute_case`` performs the formal ``engineering.work.invoke``
                through the runtime's plugin method handler exactly once, only
                after the clone, the owner records and the formal Work view all
                agree. A Work step with an existing dispatch row is never sent
                again. On failure a redacted diagnostic receipt is written
                *first*, then the caller closes the original object; an UNKNOWN
                is read back only, never re-sent.
``receipt``     every receipt is created exclusively (new file, mode 0600); an
                existing receipt/pin/database target is refused untouched. A
                receipt that cannot be written never erases the original
                failure: the refusal keeps it as its cause.

The review/report ports, the chat/human-source binding, the case policy
(``FrozenScope``) and the ``before_review`` callback are **not** rebuilt here.
They come from the owner handoff through the caller's
``application_ports_factory`` (``case_runtime.build`` with the operator's
``assemble`` transform); this entry refuses to invent a substitute graph.

CLI preparation never contacts a provider. ``execute_case`` needs in-process
runtime handles (``application_ports_factory`` + ``engineering_options`` +
``pi_selection``/``pi_ports``) that only the approved owner handoff can supply;
the CLI refuses with a typed code instead of guessing a graph.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[3]
NIGHTLY = REPO / '.nightly-cache'
STAGE = 'PREPARED_CHECK_ONLY'
EXECUTED_STAGE = 'EXECUTED_DECLARED_WORK'

REAL_MODE_REFUSAL = 'WORK_CASE_REAL_MODE_NOT_APPROVED'
SOURCES_MANIFEST_CHANGED = 'WORK_CASE_SOURCES_MANIFEST_CHANGED'
SOURCES_MANIFEST_INVALID = 'WORK_CASE_SOURCES_MANIFEST_INVALID'
SOURCE_MISSING = 'WORK_CASE_SOURCE_MISSING'
SOURCE_DRIFT = 'WORK_CASE_SOURCE_DRIFT'
TARGET_HASHES_INVALID = 'WORK_CASE_TARGET_HASHES_INVALID'
TARGET_CHANGED = 'WORK_CASE_TARGET_CHANGED'
CHECK_CONFIGURATION_CHANGED = 'WORK_CASE_CHECK_CONFIGURATION_CHANGED'
CHECK_CANDIDATE_MISSING = 'WORK_CASE_CHECK_CANDIDATE_MISSING'
CHECK_CANDIDATE_CHANGED = 'WORK_CASE_CHECK_CANDIDATE_CHANGED'
OUTPUT_OUTSIDE_CACHE = 'WORK_CASE_OUTPUT_OUTSIDE_CACHE'
OUTPUT_EXISTS = 'WORK_CASE_OUTPUT_EXISTS'
PROTECTED_TARGET_CHANGED = 'WORK_CASE_PROTECTED_TARGET_CHANGED'
OPERATOR_HANDOFF_MISSING = 'WORK_CASE_OPERATOR_HANDOFF_MISSING'
OPERATOR_HANDOFF_CHANGED = 'WORK_CASE_OPERATOR_HANDOFF_CHANGED'
CLONE_ROOT_UNAVAILABLE = 'WORK_CASE_CLONE_ROOT_UNAVAILABLE'
CLONE_ROOT_EXISTS = 'WORK_CASE_CLONE_ROOT_EXISTS'
CLONE_SOURCE_MISSING = 'WORK_CASE_CLONE_SOURCE_MISSING'
CLONE_COPY_MISMATCH = 'WORK_CASE_CLONE_COPY_MISMATCH'
CLONE_MANIFEST_MISSING = 'WORK_CASE_CLONE_MANIFEST_MISSING'
CLONE_MANIFEST_CHANGED = 'WORK_CASE_CLONE_MANIFEST_CHANGED'
CLONE_MANIFEST_INCOMPLETE = 'WORK_CASE_CLONE_MANIFEST_INCOMPLETE'
CLONE_NOT_COMPLETE = 'WORK_CASE_CLONE_NOT_COMPLETE'
CLONE_CHECKPOINT_REFUSED = 'WORK_CASE_CLONE_CHECKPOINT_REFUSED'
EVIDENCE_MISSING = 'WORK_CASE_EVIDENCE_MISSING'
EVIDENCE_INVALID = 'WORK_CASE_EVIDENCE_INVALID'
EVIDENCE_EXPECTATION_MISSING = 'WORK_CASE_EVIDENCE_EXPECTATION_MISSING'
GRANT_MISMATCH = 'WORK_CASE_GRANT_MISMATCH'
GRANT_EXPIRED = 'WORK_CASE_GRANT_EXPIRED'
GRANT_BUDGET_MISMATCH = 'WORK_CASE_GRANT_BUDGET_MISMATCH'
GRANT_CONTROL_CHANGED = 'WORK_CASE_GRANT_CONTROL_CHANGED'
PERMISSION_MISMATCH = 'WORK_CASE_PERMISSION_MISMATCH'
OWNER_RECORDS_UNAVAILABLE = 'WORK_CASE_OWNER_RECORDS_UNAVAILABLE'
ATTEMPT_ALREADY_EXISTS = 'WORK_CASE_ATTEMPT_ALREADY_EXISTS'
CONTINUATION_ORIGIN_UNAVAILABLE = 'WORK_CASE_CONTINUATION_ORIGIN_UNAVAILABLE'
CONTINUATION_ORIGIN_MISMATCH = 'WORK_CASE_CONTINUATION_ORIGIN_MISMATCH'
CONTINUATION_ROOT_CONSUMPTION_MISMATCH = 'WORK_CASE_CONTINUATION_ROOT_CONSUMPTION_MISMATCH'
CONTINUATION_SELECTOR_INVALID = 'WORK_CASE_CONTINUATION_SELECTOR_INVALID'
RUNTIME_SEAM_UNAVAILABLE = 'WORK_CASE_RUNTIME_SEAM_UNAVAILABLE'
CASE_HOLDER_UNAVAILABLE = 'WORK_CASE_HOLDER_UNAVAILABLE'
CASE_OWNER_GRAPH_MISMATCH = 'WORK_CASE_OWNER_GRAPH_MISMATCH'
CASE_BEFORE_REVIEW_UNAVAILABLE = 'WORK_CASE_BEFORE_REVIEW_UNAVAILABLE'
CASE_REPORT_DELIVERY_REFUSED = 'WORK_CASE_REPORT_DELIVERY_REFUSED'
RUNTIME_GRAPH_MISMATCH = 'WORK_CASE_RUNTIME_GRAPH_MISMATCH'
EXECUTED_READBACK_STAGE = 'EXECUTED_DECLARED_WORK_READBACK_FAILED'
# Tokens minted by ``build_clone_runtime``, mapped to the *exact* binding object
# they were minted with. A token alone is not a capability: a copied dataclass
# (``dataclasses.replace(binding_a, runtime=runtime_b)``) keeps the token, so the
# gate requires the registered object itself, not the token value.
_GRAPH_BINDINGS = {}
EXECUTION_REFUSED = 'WORK_CASE_EXECUTION_REFUSED'
EXECUTION_BINDING_MISMATCH = 'WORK_CASE_EXECUTION_BINDING_MISMATCH'
EXECUTION_DIAGNOSIS_LOST = 'WORK_CASE_EXECUTION_DIAGNOSIS_LOST'

# A complete frozen graph is the whole data root the original owner opened; a
# single copied database cannot serve as one.
FROZEN_ROOT_REQUIRED = (
    'engineering.sqlite',
    'environments.sqlite',
    'product/state/core.sqlite',
    'product/state/agentbox.sqlite',
    'product/state/agent-owner/operations.sqlite',
)


class PreparationRefusal(Exception):
    """A prepared reason this entry will not proceed; never a silent skip."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        value = {'refused': True, 'code': self.code}
        if self.detail:
            value['detail'] = self.detail
        return value


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    return _digest(Path(path).read_bytes())


def _domain_scope(scope):
    """The owners take a domain ``Scope``; the product factory hands the wire one.

    Three accepted shapes, one result: the Engineering domain ``Scope``, the
    system-access wire ``Scope`` the product's ``application_ports_factory``
    receives, and the plain ``{'realm_id','project_id'}`` projection.
    """
    from ordessa_engineering.domain.common.models.identity import Scope
    if type(scope) is Scope:
        return scope
    try:
        from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    except Exception:  # the wire package is optional for this tooling entry
        WireScope = ()
    if type(scope) is WireScope:
        return Scope(scope.realm_id, scope.project_id)
    if type(scope) is dict:
        realm, project = scope.get('realm_id'), scope.get('project_id')
    else:
        realm, project = getattr(scope, 'realm_id', None), getattr(scope, 'project_id', None)
    if (type(realm) is str and type(project) is str and realm and project):
        return Scope(realm, project)
    raise PreparationRefusal(
        EXECUTION_REFUSED,
        'domain Scope, wire Scope or {realm_id, project_id} required')


def _wire_scope(scope):
    """The formal plugin handlers receive the scope as its plain dict form."""
    if type(scope) is dict:
        return {'realm_id': scope['realm_id'], 'project_id': scope['project_id']}
    return {'realm_id': scope.realm_id, 'project_id': scope.project_id}


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise PreparationRefusal(EVIDENCE_INVALID, type(exc).__name__) from None


# ---------------------------------------------------------------- source pins

def verify_sources(sources: Path, expected_sha256: str) -> int:
    """Every pinned path must still be the reviewed bytes; count them."""
    sources = Path(sources)
    raw = sources.read_bytes()
    if _digest(raw) != expected_sha256:
        raise PreparationRefusal(SOURCES_MANIFEST_CHANGED, str(sources.name))
    values = json.loads(raw)
    if type(values) is not dict or not values:
        raise PreparationRefusal(SOURCES_MANIFEST_INVALID, str(sources.name))
    for path, digest in values.items():
        target = Path(path)
        if type(digest) is not str or len(digest) != 64:
            raise PreparationRefusal(SOURCES_MANIFEST_INVALID, target.name)
        if not target.is_file():
            raise PreparationRefusal(SOURCE_MISSING, str(target.name))
        if _file_digest(target) != digest:
            raise PreparationRefusal(SOURCE_DRIFT, str(target.name))
    return len(values)


def verify_target(root: Path, hashes_path: Path) -> int:
    """The reviewed target paths must be unchanged (absent stays absent)."""
    root = Path(root)
    if not root.is_absolute() or root.is_symlink():
        raise PreparationRefusal(TARGET_HASHES_INVALID, 'target root must be absolute')
    values = json.loads(Path(hashes_path).read_bytes())
    if type(values) is not dict or not values:
        raise PreparationRefusal(TARGET_HASHES_INVALID, 'empty target hash set')
    for name, expected in values.items():
        if type(name) is not str or not name or '..' in Path(name).parts:
            raise PreparationRefusal(TARGET_HASHES_INVALID, 'relative target name required')
        if expected is not None and (type(expected) is not str or len(expected) != 64):
            raise PreparationRefusal(TARGET_HASHES_INVALID, name)
        path = root / name
        if any(part.is_symlink() for part in (path, *path.relative_to(root).parents)):
            raise PreparationRefusal(TARGET_CHANGED, name)
        actual = _file_digest(path) if path.is_file() else None
        if actual != expected:
            raise PreparationRefusal(TARGET_CHANGED, name)
    return len(values)


def verify_operator_handoff(directory: Path) -> dict:
    """The handed-off operator/helper must still be the reviewed bytes."""
    directory = Path(directory)
    manifest_path = directory / 'manifest.json'
    if not manifest_path.is_file():
        raise PreparationRefusal(OPERATOR_HANDOFF_MISSING, str(directory))
    manifest = json.loads(manifest_path.read_bytes())
    if (type(manifest) is not dict or manifest.get('schema_version') != 1
            or manifest.get('byte_for_byte_verified') is not True
            or manifest.get('databases_credentials_or_runtime_state_copied') is not False
            or type(manifest.get('files')) is not list or not manifest['files']):
        raise PreparationRefusal(OPERATOR_HANDOFF_CHANGED, 'manifest claims')
    verified = {}
    for item in manifest['files']:
        name = item.get('file') if type(item) is dict else None
        digest = item.get('sha256') if type(item) is dict else None
        length = item.get('byte_length') if type(item) is dict else None
        if (type(name) is not str or not name or Path(name).name != name
                or type(digest) is not str or len(digest) != 64):
            raise PreparationRefusal(OPERATOR_HANDOFF_CHANGED, 'manifest entry')
        path = directory / name
        if not path.is_file():
            raise PreparationRefusal(OPERATOR_HANDOFF_MISSING, name)
        raw = path.read_bytes()
        if _digest(raw) != digest or (type(length) is int and len(raw) != length):
            raise PreparationRefusal(OPERATOR_HANDOFF_CHANGED, name)
        verified[name] = digest
    if 'operator.py' not in verified or 'case_runtime.py' not in verified:
        raise PreparationRefusal(OPERATOR_HANDOFF_MISSING, 'operator.py/case_runtime.py')
    return {
        'handoff_version': manifest.get('handoff_version'),
        'operator_sha256': verified['operator.py'],
        'case_runtime_sha256': verified['case_runtime.py'],
        'handoff_files': len(verified),
    }


def verify_check_configuration(path: Path, expected_sha256: str) -> str:
    """Digest gate for the recovered check runtime pins (no execution here)."""
    raw = Path(path).read_bytes()
    actual = _digest(raw)
    if actual != expected_sha256:
        raise PreparationRefusal(CHECK_CONFIGURATION_CHANGED, Path(path).name)
    value = json.loads(raw)
    if type(value) is not dict or not value:
        raise PreparationRefusal(CHECK_CONFIGURATION_CHANGED, Path(path).name)
    return actual


def verify_check_candidate(directory: Path) -> dict:
    """Accept the recovered check candidate as a *candidate*: digest, don't pin.

    The candidate is the runtime recovery's record; this entry reports its
    identity so a later source freeze can bind it, and refuses an inconsistent
    candidate rather than preparing against unknown interpreter pins.
    """
    directory = Path(directory)
    candidate_path = directory / 'configuration-candidate.json'
    identity_path = directory / 'identity.json'
    if not candidate_path.is_file() or not identity_path.is_file():
        raise PreparationRefusal(CHECK_CANDIDATE_MISSING, str(directory.name))
    candidate = json.loads(candidate_path.read_bytes())
    identity = json.loads(identity_path.read_bytes())
    if type(candidate) is not dict or type(identity) is not dict:
        raise PreparationRefusal(CHECK_CANDIDATE_CHANGED, 'shape')
    tree_digest = candidate.get('runtime_tree_digest')
    if type(tree_digest) is not str or tree_digest != identity.get('runtime_tree_digest'):
        raise PreparationRefusal(CHECK_CANDIDATE_CHANGED, 'runtime_tree_digest')
    pinned = candidate.get('pinned_files')
    if type(pinned) is not dict or not pinned:
        raise PreparationRefusal(CHECK_CANDIDATE_CHANGED, 'pinned_files')
    for path, digest in pinned.items():
        target = Path(path)
        if type(digest) is not str or len(digest) != 64 or not target.is_file():
            raise PreparationRefusal(CHECK_CANDIDATE_CHANGED, target.name)
        if _file_digest(target) != digest:
            raise PreparationRefusal(CHECK_CANDIDATE_CHANGED, target.name)
    return {
        'check_candidate_directory': str(directory),
        'check_candidate_sha256': _file_digest(candidate_path),
        'check_runtime_tree_digest': tree_digest,
        'check_candidate_pinned_files': len(pinned),
        'check_candidate_status': 'candidate_not_frozen',
    }


# ------------------------------------------------------------------ receipts

def write_receipt_exclusive(path: Path, report: dict) -> Path:
    """Create a brand-new receipt; never overwrite an existing target."""
    destination = Path(path)
    try:
        destination.resolve().relative_to(NIGHTLY.resolve())
    except ValueError:
        raise PreparationRefusal(OUTPUT_OUTSIDE_CACHE, str(destination)) from None
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise PreparationRefusal(OUTPUT_EXISTS, str(destination))
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise PreparationRefusal(OUTPUT_EXISTS, str(destination)) from None
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(payload)
    if destination.read_bytes() != payload:
        raise PreparationRefusal(OUTPUT_EXISTS, 'receipt read-back differs')
    return destination


def snapshot_protected(paths) -> dict:
    """Record size+digest of every old receipt, pin and database we may not touch."""
    before = {}
    for raw in paths or ():
        path = Path(raw)
        if not path.is_file():
            raise PreparationRefusal(PROTECTED_TARGET_CHANGED, str(path))
        before[str(path.resolve())] = (path.stat().st_size, _file_digest(path))
    return before


def assert_protected_unchanged(before: dict) -> None:
    for path, (size, digest) in before.items():
        target = Path(path)
        if (not target.is_file() or target.stat().st_size != size
                or _file_digest(target) != digest):
            raise PreparationRefusal(PROTECTED_TARGET_CHANGED, target.name)


# --------------------------------------------------------------------- clone

def _regular_files(root: Path) -> dict:
    """Every regular file under ``root`` as {relative posix path: Path}."""
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise PreparationRefusal(CLONE_NOT_COMPLETE, f'symlink refused: {path.name}')
        if path.is_dir():
            continue
        if not path.is_file():
            raise PreparationRefusal(CLONE_NOT_COMPLETE, f'non-file refused: {path.name}')
        files[path.relative_to(root).as_posix()] = path
    return files


def load_clone_manifest(manifest_path: Path, expected_sha256: str) -> dict:
    """The frozen root manifest: one sha256 per file, complete by construction."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise PreparationRefusal(CLONE_MANIFEST_MISSING, str(manifest_path))
    raw = manifest_path.read_bytes()
    if type(expected_sha256) is not str or len(expected_sha256) != 64 or _digest(raw) != expected_sha256:
        raise PreparationRefusal(CLONE_MANIFEST_CHANGED, manifest_path.name)
    value = json.loads(raw)
    if (type(value) is not dict or not value
            or any(type(name) is not str or not name or name.startswith('/')
                   or '..' in Path(name).parts or type(digest) is not str or len(digest) != 64
                   for name, digest in value.items())):
        raise PreparationRefusal(CLONE_MANIFEST_INCOMPLETE, manifest_path.name)
    return value


def clone_frozen_root(source_root: Path, clone_root: Path, *,
                      manifest: dict, required_entries=FROZEN_ROOT_REQUIRED) -> dict:
    """Copy one *complete frozen data root* into a brand-new root.

    The manifest must name every file of the source root (an unlisted file is a
    changed root, not a copy target) and every copied byte is verified. The
    clone root must be new, outside the source root and not an ancestor of it.
    SQLite sidecars are copied with their database and then checkpointed inside
    the clone, because the original owner library refuses to open a database
    that still has sidecars; the original root is only ever read.
    """
    source = Path(source_root)
    root = Path(clone_root)
    if not source.is_dir() or source.is_symlink():
        raise PreparationRefusal(CLONE_SOURCE_MISSING, str(source))
    if not root.is_absolute() or root.is_symlink():
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE, 'clone root must be absolute')
    source_resolved = source.resolve()
    root_resolved = root.resolve()
    if root_resolved == source_resolved:
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE, 'clone root equals the source root')
    try:
        root_resolved.relative_to(source_resolved)
    except ValueError:
        pass
    else:
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE,
            'clone root must be outside the original library root')
    try:
        source_resolved.relative_to(root_resolved)
    except ValueError:
        pass
    else:
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE,
            'clone root must not contain the original library root')
    if root.exists() and any(root.iterdir()):
        raise PreparationRefusal(CLONE_ROOT_EXISTS, str(root))

    files = _regular_files(source)
    if set(files) != set(manifest):
        missing = sorted(set(files) - set(manifest))
        absent = sorted(set(manifest) - set(files))
        raise PreparationRefusal(CLONE_MANIFEST_INCOMPLETE,
            f'unlisted={missing[:3]} missing={absent[:3]}')
    missing_required = [name for name in required_entries if name not in files]
    if missing_required:
        raise PreparationRefusal(CLONE_NOT_COMPLETE, ','.join(missing_required))
    for name, path in files.items():
        if _file_digest(path) != manifest[name]:
            raise PreparationRefusal(CLONE_MANIFEST_CHANGED, name)

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    copied = 0
    for name, path in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(path.read_bytes())
        if _file_digest(destination) != manifest[name]:
            raise PreparationRefusal(CLONE_COPY_MISMATCH, name)
        copied += len(manifest[name])
    for name, path in files.items():
        if _file_digest(path) != manifest[name]:
            raise PreparationRefusal(CLONE_MANIFEST_CHANGED,
                f'{name} changed while it was copied')
    checkpointed = _checkpoint_clone_databases(root)
    after = {name: _file_digest(root / name) for name in files if (root / name).is_file()}
    return {
        'clone_root': str(root),
        'clone_product_root': str(root / 'product'),
        'clone_library': str(root / 'engineering.sqlite'),
        'clone_source_root': str(source),
        'clone_source_manifest_sha256': _digest(json.dumps(manifest, sort_keys=True).encode()),
        'clone_files': len(files),
        'clone_bytes': copied,
        'clone_checkpointed': checkpointed,
        'clone_manifest': after,
        'clone_verified': True,
        'original_library_opened_for_write': False,
    }


def _checkpoint_clone_databases(root: Path) -> list:
    """Merge each cloned WAL into its database and drop the clone's sidecars.

    This mutates only the clone. Without it the original owner library refuses
    to open the file (it rejects sidecars), and a bare copy would drop the
    committed frames that live in the WAL.
    """
    root = Path(root)
    checkpointed = []
    for name in sorted(p.relative_to(root).as_posix() for p in root.rglob('*.sqlite')):
        database = root / name
        try:
            connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)
            try:
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                # A checkpoint keeps every committed frame but leaves the header
                # in WAL mode; the original owner library only opens a
                # rollback-journal database, so the clone is switched over.
                mode = connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
                if str(mode).lower() != 'delete':
                    raise PreparationRefusal(CLONE_CHECKPOINT_REFUSED,
                                             f'{name}: journal mode {mode}')
                connection.commit()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise PreparationRefusal(CLONE_CHECKPOINT_REFUSED, f'{name}: {type(exc).__name__}') from None
        for suffix in ('-wal', '-shm'):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        header = database.read_bytes()[:20]
        if len(header) < 20 or header[18:20] != b'\x01\x01':
            raise PreparationRefusal(CLONE_CHECKPOINT_REFUSED, f'{name}: header is not rollback')
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as probe:
            if str(probe.execute('PRAGMA journal_mode').fetchone()[0]).lower() != 'delete':
                raise PreparationRefusal(CLONE_CHECKPOINT_REFUSED, f'{name}: reopen mode')
        checkpointed.append(name)
    return checkpointed


def verify_clone_root(clone_root: Path, manifest: dict) -> dict:
    """Re-verify one clone root against its own recorded manifest.

    Used before a runtime is built over the clone: the bytes the gates read are
    the bytes the runtime will open.
    """
    root = Path(clone_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE, str(root))
    present = {name: _file_digest(root / name) for name in manifest if (root / name).is_file()}
    if set(present) != set(manifest):
        raise PreparationRefusal(CLONE_NOT_COMPLETE, 'clone root lost files')
    for name, digest in manifest.items():
        if present[name] != digest:
            raise PreparationRefusal(CLONE_COPY_MISMATCH, name)
    return {'clone_root': str(root), 'clone_files': len(manifest), 'clone_verified': True}


# ------------------------------------------------------- owner-record reads

def continuation_selector(*, operation_ref, attempt, dispatch_version, acp_revision) -> dict:
    """The explicit v2 origin selector this entry sends; it authorizes nothing.

    These four operator pins locate the record last read. The public v2 input
    carries only operation/ref versions; the actual next attempt, the
    causal operation id and the root are derived by the owner from its own rows;
    a caller-selected root, unit or budget is not expressible in this shape.
    """
    if (type(operation_ref) is not str or not operation_ref
            or type(attempt) is not int or attempt < 1
            or type(dispatch_version) is not int or dispatch_version < 1
            or type(acp_revision) is not int or acp_revision < 1):
        raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'origin selector')
    return {'execution_operation_ref': operation_ref, 'attempt': attempt,
            'expected_dispatch_version': dispatch_version,
            'expected_acp_revision': acp_revision}


def read_case_records(*, factory, scope, grant_ref, expectations, mode='first',
                      origin=None) -> dict:
    """Read Grant/control/budget from the cloned owner records; never from JSON.

    Mirrors the operator's ``FrozenScope.grant``: the Grant is resolved through
    the original authorization owner, its control must still be granted, the
    window must contain now, each expected action carries exactly one unconsumed
    unit, and the declared Work step must have no dispatch row yet.
    """
    from ordessa_engineering.application.contracts.dispatch_identity import (
        work_dispatch_key,
    )
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.application.usecases.packages.authorization import (
        resolve_work_package_authorization,
    )
    from ordessa_engineering.application.usecases.support.clock import utc_now
    from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
    from ordessa_engineering.domain.common.models.identity import Scope

    if mode not in ('first', 'continuation'):
        raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'unknown invocation mode')
    if mode == 'continuation':
        if type(origin) is not dict or set(origin) != {
                'execution_operation_ref', 'attempt', 'expected_dispatch_version',
                'expected_acp_revision'}:
            raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'origin selector')
        continuation_selector(operation_ref=origin['execution_operation_ref'],
            attempt=origin['attempt'], dispatch_version=origin['expected_dispatch_version'],
            acp_revision=origin['expected_acp_revision'])
    scope = _domain_scope(scope)
    if type(scope) is not Scope:
        raise PreparationRefusal(EXECUTION_REFUSED, 'original Scope required')
    if type(expectations) is not dict:
        raise PreparationRefusal(EVIDENCE_EXPECTATION_MISSING, 'expectations')
    for key in ('work_id', 'action_id', 'step_id', 'work_revision', 'package_digest',
                'intent_digest', 'actions'):
        if key not in expectations:
            raise PreparationRefusal(EVIDENCE_EXPECTATION_MISSING, key)
    try:
        ref = decode_approval_ref(grant_ref)
    except Exception:
        raise PreparationRefusal(EVIDENCE_INVALID, 'grant reference') from None
    now = utc_now()
    with factory.begin(scope, 'read') as uow:
        try:
            grant = uow.authorization.get_grant(ref)
            control = uow.authorization.get_control(grant.ref)
            budget = uow.authorization.action_budget(grant.ref)
            facts = resolve_work_package_authorization(uow, grant.intent.authorization)
        except ApplicationError as error:
            # A Grant the caller names but this owner does not hold is a
            # refusal; it is never a reason to open another library.
            raise PreparationRefusal(OWNER_RECORDS_UNAVAILABLE,
                                     getattr(error, 'code', '') or '') from error
        authorization = grant.intent.authorization
        if (authorization.work_id, authorization.action_id, authorization.step_id) \
                != (expectations['work_id'], expectations['action_id'], expectations['step_id']):
            raise PreparationRefusal(GRANT_MISMATCH, 'work identity')
        if authorization.work_revision != expectations['work_revision']:
            raise PreparationRefusal(GRANT_MISMATCH, 'work revision')
        if (authorization.package_ref.digest.hex != expectations['package_digest']
                or grant.intent.digest.hex != expectations['intent_digest']):
            raise PreparationRefusal(GRANT_MISMATCH, 'package/intent digest')
        if tuple(authorization.actions) != tuple(expectations['actions']):
            raise PreparationRefusal(GRANT_MISMATCH, 'actions')
        if (control.get('state') != 'granted' or control.get('revoked_at') is not None):
            raise PreparationRefusal(GRANT_CONTROL_CHANGED, str(control.get('state')))
        if not grant.intent.not_before <= now < grant.intent.expires_at:
            raise PreparationRefusal(GRANT_EXPIRED, 'window')
        if (facts.work.work_id, facts.work.revision) != (
                expectations['work_id'], expectations['work_revision']):
            raise PreparationRefusal(GRANT_MISMATCH, 'resolved Work')
        key = work_dispatch_key(expectations['work_id'], expectations['action_id'],
                                expectations['step_id'])
        slots = {item['action']: item for item in budget['actions']}
        if mode == 'continuation':
            # A continuation is decided by the origin row, never by "no attempt
            # yet": the origin attempt must exist, be the unconfirmed one and
            # keep the exact identity this selector names.
            if type(origin) is not dict:
                raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'origin selector')
            try:
                row = uow.work_dispatch.by_operation(origin['execution_operation_ref'], scope)
            except ApplicationError as error:
                if error.code != 'NOT_FOUND':
                    raise
                raise PreparationRefusal(CONTINUATION_ORIGIN_UNAVAILABLE,
                                         origin['execution_operation_ref']) from error
            if (row['run_id'] != key or row['step_id'] != expectations['step_id']
                    or row['attempt'] != origin['attempt']
                    or row['execution_operation_ref'] != origin['execution_operation_ref']
                    or row['dispatch_phase'] != 'unknown'
                    or row['dispatch_version'] != origin['expected_dispatch_version']):
                raise PreparationRefusal(CONTINUATION_ORIGIN_MISMATCH,
                                         origin['execution_operation_ref'])
            # The root's debits stay exactly as the original dispatch left them:
            # a continuation never refunds and never consumes a second time.
            for action in expectations['actions']:
                item = slots.get(action)
                if item is None or item.get('limit') != 1 or item.get('consumed') != 1:
                    raise PreparationRefusal(CONTINUATION_ROOT_CONSUMPTION_MISMATCH,
                                             action)
        else:
            # An existing attempt is decided first: it is the fact that forbids
            # another send, whether or not its debit is also already consumed.
            try:
                uow.work_dispatch.get(key, expectations['step_id'], 1, scope)
            except ApplicationError as error:
                if error.code != 'NOT_FOUND':
                    raise
            else:
                raise PreparationRefusal(ATTEMPT_ALREADY_EXISTS, key)
            for action in expectations['actions']:
                item = slots.get(action)
                if item is None or item.get('limit') != 1 or item.get('consumed') != 0:
                    raise PreparationRefusal(GRANT_BUDGET_MISMATCH, action)
        return {
            'grant_ref': grant.ref,
            'grant_digest': grant.intent.digest.hex,
            'control': control,
            'window': {'not_before': grant.intent.not_before,
                       'expires_at': grant.intent.expires_at},
            'budget': {item['action']: {'limit': item['limit'], 'consumed': item['consumed']}
                       for item in budget['actions']},
            'work': {'work_id': facts.work.work_id, 'revision': facts.work.revision,
                     'method': facts.work.method_ref},
            'package': {'digest': facts.package.ref.digest.hex},
            'actions': list(authorization.actions),
            'mode': mode,
            'origin': None if origin is None else dict(origin),
        }


def validate_evidence_reference(evidence_path: Path, expectations: dict, *,
                                mode='first', origin=None) -> dict:
    """Read the evidence JSON as a *reference*: it may only name the Grant.

    Every claim it carries is later compared with the owner records; a record
    can never define its own expectation.
    """
    if mode not in ('first', 'continuation'):
        raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'unknown invocation mode')
    record = _read_json(evidence_path)
    if type(record) is not dict:
        raise PreparationRefusal(EVIDENCE_INVALID, 'record must be an object')
    grant = record.get('grant')
    if type(grant) is not dict:
        raise PreparationRefusal(EVIDENCE_MISSING, 'grant')
    ref, digest = grant.get('ref'), grant.get('digest')
    if type(ref) is not dict or type(digest) is not str or len(digest) != 64:
        raise PreparationRefusal(EVIDENCE_INVALID, 'grant identity')
    for key in ('work_id', 'action_id', 'step_id', 'work_revision', 'package_digest',
                'intent_digest'):
        if grant.get(key) != expectations.get(key):
            raise PreparationRefusal(GRANT_MISMATCH, key)
    if tuple(grant.get('actions') or ()) != tuple(expectations['actions']):
        raise PreparationRefusal(GRANT_MISMATCH, 'actions')
    budget = record.get('budget')
    if type(budget) is not dict or type(budget.get('actions')) is not dict:
        raise PreparationRefusal(EVIDENCE_INVALID, 'budget')
    expected_consumed = 1 if mode == 'continuation' else 0
    if mode == 'continuation' and type(origin) is not dict:
        raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'origin selector')
    for action in expectations['actions']:
        item = budget['actions'].get(action)
        # The debit rule is kept, not deleted: a first attempt must still be
        # wholly unconsumed, and a continuation must still be exactly the one
        # original root debit (never refunded, never double-charged).
        if (type(item) is not dict or item.get('limit') != 1
                or item.get('consumed') != expected_consumed):
            raise PreparationRefusal(
                CONTINUATION_ROOT_CONSUMPTION_MISMATCH if mode == 'continuation'
                else GRANT_BUDGET_MISMATCH, action)
    capabilities = record.get('permission_capabilities')
    if (type(capabilities) is not list
            or not set(expectations.get('required_capabilities', ())).issubset(set(capabilities))):
        raise PreparationRefusal(PERMISSION_MISMATCH, 'capabilities')
    return {
        'grant_ref': ref,
        'grant_digest': digest,
        'evidence_sha256': _file_digest(Path(evidence_path)),
    }


def _compare_owner_with_reference(owner: dict, reference: dict, expectations: dict) -> None:
    """The JSON must agree with the owner records; it is never their authority."""
    if owner['grant_digest'] != reference['grant_digest']:
        raise PreparationRefusal(GRANT_MISMATCH, 'grant digest')
    for action in expectations['actions']:
        slot = owner['budget'].get(action)
        consumed = 1 if owner['mode'] == 'continuation' else 0
        if slot is None or slot != {'limit': 1, 'consumed': consumed}:
            raise PreparationRefusal(GRANT_BUDGET_MISMATCH, action)


# ----------------------------------------------------------------- execution

PROBE_PATH = REPO / 'tooling/checks/server_product/probe-work-package-generation.py'
PROBE_SHA256 = 'a5f0bd45ef859061edc3598466e6972a35a868a1d66a8c3e4b2064144fe922bd'
UNKNOWN_CODES = frozenset({'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'})


def _safe_error(error) -> dict:
    """Reuse the verified operator projection instead of a thinner copy."""
    raw = PROBE_PATH.read_bytes()
    if _digest(raw) != PROBE_SHA256:
        raise PreparationRefusal(EXECUTION_DIAGNOSIS_LOST, 'diagnosis projection changed')
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location('_verified_safe_error', PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.safe_error(error)


def _is_unknown(error: BaseException) -> bool:
    """Only an unconfirmed dispatch is UNKNOWN; a determined refusal is not.

    The formal wire reports the business code in ``details.internalCode`` and
    the recovery hint in ``details.recoveryAction``; a real unconfirmed result
    must not be recorded as a determined failure just because the exception
    object carries no ``code`` of its own.
    """
    if getattr(error, 'code', None) in UNKNOWN_CODES:
        return True
    details = getattr(error, 'details', None)
    if type(details) is not dict:
        details = getattr(error, 'data', None)
    if type(details) is dict:
        if details.get('internalCode') in UNKNOWN_CODES:
            return True
        if details.get('recoveryAction') == 'queryOriginalRequest':
            return True
    return getattr(error, 'retry', None) == 'reconcile'


def record_failure_receipt(path: Path, *, request_id: str, operation: str,
                           error: BaseException) -> dict:
    """Save the verified diagnosis *before* cleanup; never re-send a request.

    If the diagnosis or its receipt cannot be produced, the original exception
    stays the cause of the refusal - it is never replaced by ``from None``.
    """
    try:
        diagnosis = _safe_error(error)
    except PreparationRefusal as projection:
        raise PreparationRefusal(EXECUTION_DIAGNOSIS_LOST,
            f'diagnosis unavailable: {projection.code}') from error
    unknown = _is_unknown(error)
    receipt = {
        'stage': 'UNKNOWN_RECORDED_NO_RESEND' if unknown else 'FAILED_DETERMINED_NO_RESEND',
        'request_id': request_id,
        'operation': operation,
        'error': diagnosis,
        'retry_allowed': False,
        'unknown_requires_reconciliation': unknown,
    }
    try:
        write_receipt_exclusive(path, receipt)
    except PreparationRefusal as secondary:
        raise PreparationRefusal(EXECUTION_DIAGNOSIS_LOST,
            f'{getattr(error, "code", None) or type(error).__name__}; '
            f'receipt not written: {secondary.code}') from error
    return receipt


# ---------------------------------------------------- one-graph case assembly

@dataclass(frozen=True)
class CloneGraphBinding:
    """The real graph captured from the product's own ports-factory call.

    A path string or a caller boolean proves nothing: these are the exact
    factory/access objects the runtime handed to the case assembly, plus the
    runtime object itself, so the gates read the same owner records the
    execution writes.
    """

    runtime: object
    factory: object
    access: object
    library_path: str
    library_id: str
    clone_root: str
    product_root: str
    # Only ``build_clone_runtime`` can mint this: a hand-made binding or a
    # caller boolean never carries a token from this process.
    token: object = None


@dataclass(frozen=True)
class DeclaredWorkCaseAssembly:
    """The single case-port build plus the original dispatch seams over it."""

    case_ports: object
    selection: object
    snapshots: object
    dispatch_query: object
    binder: object
    applier: object
    before_review: object


def build_case_before_review(*, factory, scope, frozen_scope, deliver, holder):
    """The operator's ``before_review``, as a closure over the same graph.

    It resolves the **already registered** submission in the same UoW, hands it
    to the host's delivery callback, and only after that fixes this review's id
    on the frozen scope. Nothing is registered twice: the submission must
    already exist, no report is recorded here, and a refused delivery leaves
    ``review_id`` unset so the reviewer bootstrap stays refused.
    """
    domain_scope = _domain_scope(scope)

    def before_review(context, plan, request):
        try:
            with factory.begin(domain_scope, 'read') as uow:
                target = plan.requirement.expected_targets.targets[0].ref
                report = uow.submissions.resolve(target)
        except Exception as error:
            raise PreparationRefusal(CASE_REPORT_DELIVERY_REFUSED,
                                     type(error).__name__) from error
        delivered = deliver(plan, report)
        if type(delivered) is not dict or type(delivered.get('submission_ref')) is not dict:
            raise PreparationRefusal(CASE_REPORT_DELIVERY_REFUSED,
                                     'delivery must return the submission reference')
        frozen_scope.review_id = plan.review_id
        holder['report_delivered'] = delivered['submission_ref']
        return delivered

    return before_review


def assemble_declared_work_case(*, runtime, holder, scope, caller, frozen_scope,
                                expected_selection, prompt_parameters, review_paths,
                                deliver=None, implementation_timeout=1800,
                                continuation=False, report_correction_sources=None,
                                report_correction_only=False,
                                review_successor_only=False,
                                report_content_rework_only=False,
                                report_content_rework_approval=None,
                                before_review_native_prompt=None):
    """Build **one** case-port set from the same-graph holder and bind it.

    Every owner input - factory, access, Method control, blobs, materials,
    source review bindings, reviewer and caller - comes from the one base
    holder the owner handoff produced, and the Unit owner is
    ``runtime.unit_execution_owner``. ``expected_selection`` is the host's own
    fixed ``(ActorRef, roles, trust_version)``, never derived from the reviewer
    object under test. The original ``build_local_dispatch_bindings`` and the
    same ``FrozenScope.work_scope`` are used, and the dispatch binder's
    ``review_prompt_source`` is the same ``case_ports.review_runtime``.
    """
    from ordessa_engineering.adapters.native_records import build_local_dispatch_bindings
    from ordessa_server.composition.engineering_declared_work_case_assembly import (
        apply_declared_work_case_ports,
        build_declared_work_case_ports,
    )
    from ordessa_server.composition.engineering_native_dispatch_assembly import (
        bind_engineering_native_dispatch,
    )
    from ordessa_units.public import unit_services
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope

    scope = _domain_scope(scope)
    wire_scope = WireScope(scope.realm_id, scope.project_id)
    if type(holder) is not dict:
        raise PreparationRefusal(CASE_HOLDER_UNAVAILABLE, 'base holder required')
    required = ('factory', 'access', 'controls', 'blobs', 'materials', 'bindings',
                'reviewer', 'caller')
    missing = [name for name in required if holder.get(name) is None]
    if missing:
        raise PreparationRefusal(CASE_HOLDER_UNAVAILABLE, ','.join(missing))
    if holder['caller'] is not caller:
        raise PreparationRefusal(CASE_HOLDER_UNAVAILABLE, 'caller must be the holder caller')
    if deliver is None or not callable(deliver):
        # Without the delivery closure the review id can never be fixed, so the
        # case is not prepared at all rather than prepared half-way.
        raise PreparationRefusal(CASE_BEFORE_REVIEW_UNAVAILABLE,
                                 'host report delivery closure required')
    if runtime is None or getattr(runtime, 'unit_execution_owner', None) is None:
        raise PreparationRefusal(CASE_OWNER_GRAPH_MISMATCH,
                                 'runtime.unit_execution_owner required')
    owner = runtime.unit_execution_owner
    if getattr(owner, 'records', None) is None:
        raise PreparationRefusal(CASE_OWNER_GRAPH_MISMATCH, 'original Unit records required')
    if (type(report_correction_only) is not bool
            or type(review_successor_only) is not bool
            or type(report_content_rework_only) is not bool
            or sum((report_correction_only, review_successor_only, report_content_rework_only)) > 1
            or (report_correction_only or report_content_rework_only) and (report_correction_sources is None
                or getattr(owner, 'effect_write_guard_factory', None) is not None
                or getattr(owner, 'acp_turn_opt_in', None) is not True)):
        raise PreparationRefusal(CASE_OWNER_GRAPH_MISMATCH,
                                 'report-only and review-successor modes require their fixed owner')

    before_review = build_case_before_review(
        factory=holder['factory'], scope=scope, frozen_scope=frozen_scope,
        deliver=deliver, holder=holder)
    case_ports = build_declared_work_case_ports(
        factory=holder['factory'], access=holder['access'], wire_scope=wire_scope,
        owner=owner, method_control=holder['controls'], blobs=holder['blobs'],
        source_materials=holder['materials'],
        source_review_bindings=holder['bindings'],
        reviewer_source=holder['reviewer'],
        expected_selection=expected_selection, caller=caller,
        review_paths=review_paths, before_review=before_review,
        timeout=implementation_timeout,
        report_correction_sources=report_correction_sources,
        report_content_rework_approval=report_content_rework_approval,
        before_review_native_prompt=before_review_native_prompt)
    standalone_report = report_correction_only or report_content_rework_only
    if standalone_report:
        selection, snapshots = None, None
        if report_content_rework_only:
            from ordessa_server.composition.engineering_declared_work_case_assembly import build_declared_report_history_query_factory
            dispatch_query = build_declared_report_history_query_factory(case_ports)
        else:
            from ordessa_engineering.adapters.native_records import build_historical_dispatch_query_factory
            dispatch_query = build_historical_dispatch_query_factory(owner, holder['access'])
    else:
        selection, snapshots, dispatch_query = build_local_dispatch_bindings(
            owner, holder['access'], prompt_parameters=prompt_parameters,
            workspace_scope_guard=frozen_scope.work_scope)
        if report_correction_sources is not None:
            # The original business Unit is completed and released. Select its
            # public historical query once, retaining the same callable for
            # Service and the canonical owner identity checks.
            from ordessa_server.composition.engineering_declared_work_case_assembly import build_declared_report_history_query_factory
            dispatch_query = build_declared_report_history_query_factory(case_ports)

    def bind(service):
        return bind_engineering_native_dispatch(
            service, runtime, services=unit_services(runtime.unit_runtime.context),
            records=owner.records, blobs=holder['blobs'], query_factory=dispatch_query,
            selection=selection, source_snapshots=snapshots, history_sources=snapshots,
            implementation_timeout=implementation_timeout,
            review_prompt_source=case_ports.review_runtime,
            continuation=continuation)

    def apply(ports):
        return apply_declared_work_case_ports(
            ports, case_ports=case_ports, execution_records=owner.records,
            execution_query_factory=dispatch_query,
            execution_dispatch_binder=None if standalone_report else bind)

    return DeclaredWorkCaseAssembly(
        case_ports=case_ports, selection=selection, snapshots=snapshots,
        dispatch_query=dispatch_query, binder=None if standalone_report else bind, applier=apply,
        before_review=before_review)


def open_local_library_registered_graph(*, graph_root, manifest, candidate, output,
                                       driver, case, source_selection,
                                       report_correction_only=False,
                                       review_successor_only=False,
                                       report_content_rework_only=False,
                                       report_content_rework_approval_factory=None,
                                       report_content_rework_budget=None):
    """Reopen this case's registered owners, without registration or dispatch.

    ``case`` and ``driver`` are the fixed repository handoff modules, never
    caller-selected imports. Their original material/profile/permission ports
    are retained; only the explicit report and successor phases select
    read-only Pi callback policies.
    The three phases are opened and stopped serially by the report driver.
    """
    from dataclasses import replace
    from datetime import datetime
    from functools import partial
    import time
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_agents.profiles import ProfileService, decode_revision_ref
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.assembly import UnitRunPermission
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.product_native_configuration import construct_pi_harness_declaration
    from ordessa_server.composition.pi_selection import PiExecutionSelection, PiExecutionPorts
    from ordessa_server.composition.agent_owner import AgentJournalReopen
    from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
    from ordessa_server.composition.engineering_chat_confirmation import FrozenChatInstruction, MainAgentChatConfirmation
    from ordessa_server.composition.engineering_declared_work_case_assembly import report_correction_file_approval
    from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
    from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
    from ordessa_engineering.application.usecases.packages.authorization import ImplementationIntentAdmission
    from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
    from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
    from ordessa_engineering.domain.approvals.consent_codec import decode_record
    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
    from ordessa_engineering.domain.common.models.identity import ActorRef
    from ordessa_infrastructure.encoding import canonical_bytes

    graph, output = Path(graph_root), Path(output)
    verify_clone_root(graph, manifest)
    authorization = candidate['authorization']
    invoke = candidate['invoke_parameters']
    if (type(report_correction_only) is not bool
            or type(review_successor_only) is not bool
            or type(report_content_rework_only) is not bool
            or sum((report_correction_only, review_successor_only, report_content_rework_only)) > 1
            or report_content_rework_approval_factory is not None
               and not callable(report_content_rework_approval_factory)
            or authorization['work_id'] != invoke['work_id']
            or authorization['action_id'] != 'incremental.implement-package'
            or authorization['method_ref'] != invoke['inputs']['method']
            or candidate['fixed_profile_ref'] != invoke['inputs']['profile']):
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'original candidate identity differs')
    frozen_scope = json.loads(authorization['request_summary'])
    case.WORK = authorization['work_id']
    case.INTENT_DIGEST = candidate['intent']['digest']['hex']
    case.FROZEN_PACKAGE_DIGEST = authorization['package_ref']['digest']['hex']
    case.TARGET = Path(frozen_scope['root'])
    case.BEFORE = frozen_scope['before_sha256']
    case.GRANT_VALIDITY_SECONDS = (datetime.fromisoformat(authorization['expires_at'].replace('Z', '+00:00'))
        - datetime.fromisoformat(authorization['not_before'].replace('Z', '+00:00'))).total_seconds()
    driver.REQUEST_PREFIX = case.WORK + '-'
    driver.CAPABILITIES = tuple(dict.fromkeys((*driver.CAPABILITIES, *case.CAPS)))
    paths = tuple(str(case.TARGET / name) for name in case.BEFORE)
    if len(paths) != 4 or set(frozen_scope['allowed_operations']) != set(case.BEFORE):
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'original four-file scope required')
    setup_record = _read_json(graph.parent / 'native-setup-before-product.json')
    environment_id = setup_record['environment_identity']
    fingerprint = ProtectedFingerprintHmac({'process-only': os.urandom(32)}, active_key_id='process-only')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(graph / 'product')
    try:
        context = setup.unit_runtime.context
        namespace = context.environment_namespace
        declaration = construct_pi_harness_declaration(setup, bridge_executable=case.BRIDGE,
            pi_executable=driver.PI, reviewed_bridge_sha256=case.BRIDGE_SHA)
        profile = decode_revision_ref(candidate['fixed_profile_ref'])
        if (ProfileService(UnitProfileAdmission(context)).get_revision(profile).ref != profile
                or profile.environment_namespace != namespace):
            raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'original immutable profile differs')
    finally:
        setup.stop()
    environment_root = graph / 'local-environment'
    if not environment_root.is_dir() or not (graph / 'environments.sqlite').is_file():
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'registered environment is missing')
    environment_store = SQLiteEnvironmentStore(graph / 'environments.sqlite')
    environments = EnvironmentManager(store=environment_store,
        providers={'local': LocalEnvironmentResourceProvider(default_root=str(environment_root))})
    environment = environments.get(environment_id)
    if environment.snapshot.backend_id != str(environment_root):
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'registered environment backend differs')
    scope = WireScope(namespace, driver.CASE_ID)
    product = graph / 'product'
    identity = lambda path: (path.stat().st_dev, path.stat().st_ino)
    reopen = AgentJournalReopen(expected_namespace=namespace, root_path=str(product),
        root_identity=identity(product), core_identity=identity(product / 'state/core.sqlite'),
        journal_identity=identity(product / 'state/agent-owner/operations.sqlite'))
    policy = case.FrozenScope()
    holder = dict(material_selection=driver.load_materials(case.MATERIAL_MANIFEST,
        case.MATERIAL_MANIFEST_SHA256), attempt_root=output, runtime_root=graph,
        reuse_existing_runtime=True, environment_identity=environment.identity,
        profile_revision=candidate['fixed_profile_ref'], frozen_source_files=graph / 'caller-files',
        candidate_intent_digest=case.INTENT_DIGEST, environment=environment,
        environment_store=environment_store, jev_source=driver.ENV_SOURCE,
        jev_variable='OPEN_CODE_GO_API_KEY', case_scope=policy, output=output,
        driver=driver, preapproval_build_only=False)
    policy.bind(holder)

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope,
            tuple('execution.units.' + name for name in sorted(driver.ACTIONS)) + driver.CAPABILITIES),))
        holder['runtime'] = runtime
        principal = authority.authenticate('Bearer ' + runtime.token)
        return UnitRunPermission(access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(environment_root),
            actions=driver.ACTIONS, expires_at=time.time() + 3600)

    selection = PiExecutionSelection('local-library-generation-agent', profile, environment.identity,
        'local', 'none', True, 'selected-model', driver.PROVIDER, driver.MODEL,
        str(case.BRIDGE), case.BRIDGE_SHA, str(driver.PI), str(driver.ENV_SOURCE))
    standalone_report = report_correction_only or report_content_rework_only
    if standalone_report:
        callback = partial(report_correction_file_approval, allowed_paths=paths)
    elif review_successor_only:
        def callback(*, runtime, permission, environment_instance):
            return UnitFileCallbackApproval(runtime=runtime, permission=permission,
                environment_instance=environment_instance, allowed_paths=paths,
                scope_guard=policy.callback, approved_check_command=None)
    else:
        callback = policy.callback_factory
    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
        (driver.MODEL,), driver.selected_model(), acp_turn_opt_in=True,
        defer_effect_write_guard_factory=not standalone_report,
        credential_environment_variable='DEEPSEEK_API_KEY', callback_approval_factory=callback,
        restricted_file_tools=True,
        approved_check_command=None if standalone_report or review_successor_only else policy.check_command,
        read_only_file_tools=review_successor_only or report_content_rework_only,
        request_budget=(None if report_content_rework_budget is None else
            report_content_rework_budget.configuration('report' if report_content_rework_only else 'review')),
        agent_journal_reopen=reopen)
    base = driver.application_factory(output, holder, live=True, long_context=True,
                                      review_input_mode='sections-v1')
    intent = decode_record(canonical_bytes(candidate['intent']), WorkPackageAuthorizationIntent)
    notice = decode_record(canonical_bytes(candidate['notice']), WorkPackageNotice)
    frozen = FrozenChatInstruction(intent, notice, candidate['actual_instruction'],
                                   candidate['original_business_context'], notice.source)

    def application(factory, access, wire_scope):
        result = base(factory, access, wire_scope)
        with factory.begin(holder['scope'], 'read') as uow:
            row = uow.work_dispatch.by_operation(source_selection['origin_operation_ref'], holder['scope'])
            binding = decode_dispatch(row['binding_bytes'])
            if binding.intent_digest != intent.digest or binding.work['work_id'] != case.WORK:
                raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'original dispatch identity differs')
            holder['grant_ref'] = binding.approval_ref
        raw = (case.ROOT / 'methods/incremental-engineering/policies/product-chat-confirmation.v2.yaml').read_bytes()
        if hashlib.sha256(raw).hexdigest() != intent.policy_ref.digest.hex:
            raise PreparationRefusal(SOURCE_DRIFT, 'original confirmation policy differs')
        attestor = RegisteredMainAgentAttestor(access, scope=wire_scope,
            principal_id=holder['caller'].principal_id, selected_policy_ref=intent.policy_ref)
        admission = ImplementationIntentAdmission(factory, holder['controls'], holder['bindings'])
        conversation = ConversationAdmission(raw, intent.policy_ref,
            attestor_guard=attestor.guard, intent_guard=admission.guard_intent)
        chat = MainAgentChatConfirmation(factory, conversation,
            conversation_locator=notice.source.locator, instruction_binding=frozen)
        holder.update(chat=chat, policy=intent.policy_ref)

        def deliver(plan, report):
            return {'submission_ref': asdict(report.ref)}

        def prompt_parameters(context, package, unit, recipe=None):
            if recipe is None:
                raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'frozen recipe required')
            return recipe['params']

        rework_approval = (None if report_content_rework_approval_factory is None else
            report_content_rework_approval_factory(factory=factory, access=access,
                blobs=holder['blobs'], scope=holder['scope']))
        assembly = assemble_declared_work_case(runtime=holder['runtime'], holder=holder,
            scope=wire_scope, caller=holder['caller'], frozen_scope=policy,
            expected_selection=(ActorRef('jev-real-source-reviewer', 'service', 'explicit-host-selection'),
                                ('reviewer',), 1), prompt_parameters=prompt_parameters,
            review_paths=paths, deliver=deliver, implementation_timeout=1800,
            report_correction_sources=source_selection,
            report_correction_only=report_correction_only,
            review_successor_only=review_successor_only,
            report_content_rework_only=report_content_rework_only,
            report_content_rework_approval=rework_approval,
            before_review_native_prompt=(None if report_content_rework_budget is None else
                lambda owner, unit: report_content_rework_budget.require_unit_ready(owner, unit, 'review')))
        holder['assembly'] = assembly
        selected = assembly.applier(replace(result, conversation_admission=chat))
        if not standalone_report:
            binder = selected.execution_dispatch_binder

            def bind(service):
                holder['service'] = service
                return binder(service)

            selected = replace(selected, execution_dispatch_binder=bind)
        holder['review_admission'] = selected.review_admission
        return selected

    # Refresh only the noncredential files selected by the recovery driver.
    # Opening this existing owner graph must not hash its instance secrets.
    current_manifest = {name: _file_digest(graph / name) for name in manifest}
    capabilities = tuple(name for name in driver.CAPABILITIES
                         if not (standalone_report or review_successor_only)
                         or name != 'engineering.executions.dispatch')
    runtime, projection = build_clone_runtime(clone_root=graph, manifest=current_manifest,
        pi_selection=selection, pi_ports=ports, application_ports_factory=application,
        engineering_options=dict(library_path=str(graph / 'engineering.sqlite'),
            library_id=driver.CASE_ID, scope=scope, create_library=False,
            schema_version=17, machine_capabilities=capabilities))
    return runtime, holder, projection


def build_clone_runtime(*, clone_root: Path, manifest: dict, application_ports_factory,
                        engineering_options, pi_selection=None, pi_ports=None):
    """Open the product runtime over this verified, already owned graph.

    This function never copies a graph or creates a Work/Grant. Report recovery
    passes the current manifest of the original registered graph; ordinary
    preparation may pass a previously copied graph. Both use its same owners.

    ``application_ports_factory`` is the owner handoff's own seam
    (``case_runtime.build``: base ports + chat admission + the operator's
    ``assemble`` transform). Rebuilding those ports here would select a second
    reviewer/chat/Grant authority, so this entry only verifies the clone and
    hands the original factory through.
    """
    if not callable(application_ports_factory):
        raise PreparationRefusal(RUNTIME_SEAM_UNAVAILABLE,
            'application_ports_factory from the owner handoff is required')
    if type(engineering_options) is not dict or not engineering_options:
        raise PreparationRefusal(RUNTIME_SEAM_UNAVAILABLE, 'engineering options are required')
    root = Path(clone_root)
    cloned = verify_clone_root(root, manifest)
    product_root = root / 'product'
    if not product_root.is_dir() or product_root.is_symlink():
        raise PreparationRefusal(CLONE_NOT_COMPLETE, 'clone product root is missing')
    # The product runtime opens the frozen root's own ``product`` data root;
    # the total clone root is an unowned directory (DATA_ROOT_UNOWNED). The
    # Engineering library the gates read must be the same graph the runtime
    # opens, so an explicit library path is checked rather than trusted.
    library = root / 'engineering.sqlite'
    if not library.is_file():
        raise PreparationRefusal(CLONE_NOT_COMPLETE, 'clone engineering library is missing')
    declared = engineering_options.get('library_path')
    if declared is not None and Path(declared) != library:
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'library path is not the clone library')
    cloned = dict(cloned, clone_manifest=dict(manifest),
                  clone_product_root=str(product_root),
                  clone_library=str(library))
    captured = {}

    def capture(factory, access, scope):
        # The product runtime hands its own Engineering owners here; keeping
        # them is what makes the later Grant read and the execution one graph.
        captured.setdefault('owners', (factory, access, scope))
        return application_ports_factory(factory, access, scope)

    from ordessa_server.composition.product_runtime import build_product_runtime  # noqa: PLC0415
    options = dict(engineering_options)
    options.setdefault('library_path', str(library))
    options['application_ports_factory'] = capture
    runtime = build_product_runtime(product_root, pi_selection=pi_selection,
                                    pi_ports=pi_ports, **options)
    owners = captured.get('owners')
    if owners is None:
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'the ports factory was never called by the runtime')
    factory, access, _scope = owners
    factory_library = getattr(getattr(factory, 'library', None), 'path', None)
    library_id = getattr(getattr(factory, 'library', None), 'library_id', None)
    if (factory_library is None or Path(factory_library) != library
            or type(library_id) is not str or not library_id):
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'captured factory is not this clone library')
    token = object()
    cloned['graph_binding'] = _register_graph_binding(CloneGraphBinding(
        runtime=runtime, factory=factory, access=access,
        library_path=str(library), library_id=library_id,
        clone_root=str(root), product_root=str(product_root), token=token))
    return runtime, cloned


def _register_graph_binding(binding):
    """Register the one object a token stands for; copies can never pass."""

    token = getattr(binding, 'token', None)
    if token is None:
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'graph binding needs a minted token')
    _GRAPH_BINDINGS[token] = binding
    return binding


def _wire_payload(answer):
    """Unwrap one formal plugin result into its business payload."""
    if type(answer) is not dict:
        return answer
    if answer.get('record_type') == 'command_result':
        return answer.get('result')
    if isinstance(answer.get('data'), dict):
        return answer['data']
    record = answer.get('record')
    return record if isinstance(record, dict) else answer


def invoke_formal_work_action(runtime, *, caller, scope, parameters, request_id):
    """Call ``engineering.work.invoke`` through the formal plugin method handler."""
    methods = getattr(getattr(runtime, 'plugin_host', None), 'methods', None)
    descriptor = methods.lookup('engineering.work.invoke') if methods is not None else None
    if descriptor is None or not callable(getattr(descriptor, 'handler', None)):
        raise PreparationRefusal(EXECUTION_REFUSED, 'formal engineering.work.invoke unavailable')
    import asyncio  # noqa: PLC0415
    return asyncio.run(descriptor.handler({
        'scope': _wire_scope(scope), 'requestId': request_id,
        'parameters': parameters}, caller))


def read_formal_work_action(runtime, *, caller, scope, work_id, action_id, request_id):
    """The formal ``engineering.work.get`` must show this action as runnable.

    A declared four-step action is only ``available`` when this graph actually
    carries the case's review/report ports (the implementation results are not
    ``runnable`` otherwise), so this read is also the proof that the owner
    handoff's assembly was applied - not rebuilt here.
    """
    methods = getattr(getattr(runtime, 'plugin_host', None), 'methods', None)
    descriptor = methods.lookup('engineering.work.get') if methods is not None else None
    if descriptor is None or not callable(getattr(descriptor, 'handler', None)):
        raise PreparationRefusal(EXECUTION_REFUSED, 'formal engineering.work.get unavailable')
    import asyncio  # noqa: PLC0415
    view = _wire_payload(asyncio.run(descriptor.handler({
        'scope': _wire_scope(scope), 'requestId': request_id,
        'parameters': {'work_id': work_id}}, caller)))
    if type(view) is not dict:
        raise PreparationRefusal(EXECUTION_REFUSED, 'engineering.work.get returned no Work view')
    action = next((item for item in view.get('actions', ())
                   if item.get('action_id') == action_id), None)
    if (action is None or action.get('disposition') != 'available'
            or action.get('execute_permitted') is not True):
        raise PreparationRefusal(EXECUTION_REFUSED, 'declared action is not available')
    return {'work_id': work_id, 'action_id': action_id,
            'revision': view.get('revision'), 'disposition': action['disposition'],
            'execute_permitted': True}


def read_unknown_formally(runtime, *, caller, scope, request_id):
    """Read the operation record of an UNKNOWN; this path never re-sends."""
    methods = getattr(getattr(runtime, 'plugin_host', None), 'methods', None)
    descriptor = methods.lookup('engineering.operations.get') if methods is not None else None
    if descriptor is None or not callable(getattr(descriptor, 'handler', None)):
        raise PreparationRefusal(EXECUTION_REFUSED, 'engineering.operations.get unavailable')
    import asyncio  # noqa: PLC0415
    return asyncio.run(descriptor.handler({
        'scope': _wire_scope(scope), 'requestId': request_id + '-read',
        'parameters': {'request_id': request_id}}, caller))


def _reserve_receipt(receipt_path: Path) -> Path:
    """Resolve the exclusive receipt target *before* the effectful call."""
    destination = Path(receipt_path)
    try:
        destination.resolve().relative_to(NIGHTLY.resolve())
    except ValueError:
        raise PreparationRefusal(OUTPUT_OUTSIDE_CACHE, str(destination)) from None
    if destination.exists() or destination.is_symlink():
        raise PreparationRefusal(OUTPUT_EXISTS, str(destination))
    return destination


def _bound_case(case, parameters) -> tuple:
    """Bind the verified clone and the evidence reference to this exact call."""
    if type(case) is not dict:
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'case record required')
    required = {'grant', 'grant_ref', 'expectations', 'library_id', 'pins', 'clone'}
    if not required.issubset(case):
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'case record shape')
    grant, clone = case['grant'], case['clone']
    pins, expectations = case['pins'], case['expectations']
    if (type(grant) is not dict or type(clone) is not dict or type(pins) is not dict
            or type(expectations) is not dict or type(case['library_id']) is not str
            or type(clone.get('clone_library')) is not str
            or type(clone.get('clone_manifest')) is not dict
            or type(pins.get('sources_path')) is not str
            or type(pins.get('sources_sha256')) is not str):
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'case record values')
    binding = clone.get('graph_binding')
    if (type(clone.get('clone_root')) is not str
            or type(clone.get('clone_product_root')) is not str
            or type(clone.get('clone_library')) is not str
            or clone.get('clone_verified') is not True
            or type(binding) is not CloneGraphBinding):
        # A caller boolean or a path string is self-attestation, not an owner.
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH,
                                 'captured graph binding required')
    # The frozen copy is verified at clone time (``clone_verified``) and the
    # runtime is built over the very same clone (``runtime_graph_verified``);
    # the runtime then writes its own state into that root, so re-hashing the
    # frozen manifest here would refuse a legitimate run. The remaining checks
    # prove the graph identity instead: the gated library is the clone's own
    # file, inside the clone root, and the product state sits under it.
    root = Path(clone['clone_root'])
    if Path(clone['clone_library']) != root / 'engineering.sqlite':
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'gated library is outside the clone')
    if Path(clone['clone_product_root']) != root / 'product':
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'product root is outside the clone')
    if not root.is_dir() or not Path(clone['clone_library']).is_file():
        raise PreparationRefusal(CLONE_NOT_COMPLETE, 'clone root lost its library')
    if not Path(clone['clone_product_root']).is_dir():
        raise PreparationRefusal(CLONE_NOT_COMPLETE, 'clone root lost its product state')
    registered = (_GRAPH_BINDINGS.get(binding.token)
                  if binding.token is not None else None)
    if registered is None or registered is not binding:
        # Same token, different object: a copied/forged binding is refused.
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'graph binding was not minted by this entry')
    if (binding.clone_root != clone['clone_root']
            or binding.product_root != clone['clone_product_root']
            or binding.library_path != clone['clone_library']
            or binding.library_id != case['library_id']
            or getattr(getattr(binding.factory, 'library', None), 'path', None) is None):
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'captured binding does not belong to this case')
    if Path(binding.factory.library.path).resolve() != Path(clone['clone_library']).resolve():
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'captured factory library differs')
    if getattr(binding.factory.library, 'library_id', None) != case['library_id']:
        # Equal paths are not the same owner: the library identity is checked.
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'captured factory identity differs')
    verify_sources(Path(pins['sources_path']), pins['sources_sha256'])
    if (type(parameters) is not dict
            or parameters.get('work_id') != expectations['work_id']
            or parameters.get('action_id') != expectations['action_id']):
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH, 'parameters vs frozen case')
    return grant, clone


def execute_case(*, runtime, caller, scope, parameters, request_id, case,
                 receipt_path: Path, mode='first', origin=None) -> dict:
    """One formal declared action: bound, gated on owner records, executed once.

    The clone is verified, the Grant/control/budget are read from the cloned
    owner records, the formal Work view must show the action runnable, and only
    then is the single ``engineering.work.invoke`` issued. A determined refusal
    is never written as UNKNOWN; only an unconfirmed dispatch is. The redacted
    diagnosis is written before this function lets the caller clean up, and the
    operation is read back through the same formal owner - never re-sent.
    """
    if runtime is None or caller is None or scope is None:
        raise PreparationRefusal(RUNTIME_SEAM_UNAVAILABLE, 'runtime/caller/scope are required')
    if mode not in ('first', 'continuation'):
        raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'unknown invocation mode')
    if type(parameters) is not dict or parameters.get('operation') is not None:
        raise PreparationRefusal(EXECUTION_REFUSED, 'caller-selected operations are not allowed')
    if mode == 'continuation':
        # The formal v2 selector is the only continuation input; an ordinary
        # first-attempt payload must never reach the continuation flow.
        if (parameters.get('invocation_version') != 2
                or type(parameters.get('continuation_of')) is not dict
                or type(origin) is not dict
                or parameters['continuation_of'] != {key: origin.get(key) for key in (
                    'execution_operation_ref', 'expected_dispatch_version', 'expected_acp_revision')}):
            raise PreparationRefusal(CONTINUATION_SELECTOR_INVALID, 'v2 origin selector')
    elif parameters.get('invocation_version') == 2 or 'continuation_of' in parameters:
        raise PreparationRefusal(EXECUTION_BINDING_MISMATCH,
                                 'continuation payload in a first-attempt run')
    scope = _domain_scope(scope)
    grant, clone = _bound_case(case, parameters)
    binding = clone['graph_binding']
    if binding.runtime is not runtime:
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH,
                                 'this runtime is not the one built over the clone')
    # The runtime, when it exposes its data root, must be the one built over
    # this clone: the Gate reads and the effect are then the same graph.
    runtime_root = getattr(runtime, 'data_root', None)
    if runtime_root is not None and Path(runtime_root) != Path(clone['clone_product_root']):
        raise PreparationRefusal(RUNTIME_GRAPH_MISMATCH, 'runtime is not built over this clone')
    # Grant/control/budget are read only through the factory the runtime itself
    # handed to the case assembly - never through a path or a caller flag.
    owner = read_case_records(factory=binding.factory, scope=scope,
                              grant_ref=case['grant_ref'],
                              expectations=case['expectations'],
                              mode=mode, origin=origin)
    _compare_owner_with_reference(owner, grant, case['expectations'])
    read_formal_work_action(runtime, caller=caller, scope=scope,
                            work_id=case['expectations']['work_id'],
                            action_id=case['expectations']['action_id'],
                            request_id=request_id + '-preflight')
    destination = _reserve_receipt(receipt_path)
    try:
        value = invoke_formal_work_action(runtime, caller=caller, scope=scope,
                                          parameters=parameters, request_id=request_id)
    except BaseException as error:
        record_failure_receipt(destination, request_id=request_id,
                               operation='engineering.work.invoke', error=error)
        raise
    # The invoke already happened. Its result is saved before any further
    # read, and a failing read-back is appended to that same receipt - this
    # path never re-sends the action.
    report = {
        'stage': EXECUTED_STAGE,
        'request_id': request_id,
        'grant_ref': asdict(owner['grant_ref']),
        'grant_digest': owner['grant_digest'],
        'control': owner['control'],
        'work_id': owner['work']['work_id'],
        'action_id': case['expectations']['action_id'],
        'mode': mode,
        'origin': owner['origin'],
        'clone_root': clone['clone_root'],
        'clone_files': clone['clone_files'],
        'sources_sha256': case['pins']['sources_sha256'],
        'result': value,
        'read_back': None,
        'retry_allowed': False,
    }
    try:
        operation = read_unknown_formally(runtime, caller=caller, scope=scope,
                                          request_id=request_id)
    except BaseException as readback_error:
        report['stage'] = EXECUTED_READBACK_STAGE
        try:
            report['read_back_error'] = _safe_error(readback_error)
        except PreparationRefusal:
            report['read_back_error'] = {'type': type(readback_error).__name__}
        try:
            write_receipt_exclusive(destination, report)
        except PreparationRefusal as secondary:
            raise PreparationRefusal(
                EXECUTION_DIAGNOSIS_LOST,
                f'read-back failed and its receipt was not written: {secondary.code}'
            ) from readback_error
        raise
    report['read_back'] = operation
    try:
        write_receipt_exclusive(destination, report)
    except PreparationRefusal as secondary:
        report['receipt_written'] = None
        report['receipt_error'] = secondary.code
    else:
        report['receipt_written'] = str(destination)
    return report


# ----------------------------------------------------------------------- run

def _expectations_from_args(args) -> dict:
    required = (args.work_id, args.action_id, args.step_id, args.work_revision,
                args.package_digest, args.intent_digest)
    if any(value is None for value in required) or not args.required_action:
        raise PreparationRefusal(EVIDENCE_EXPECTATION_MISSING,
            'work/action/step/revision/package/intent/actions are required with --evidence')
    return {
        'work_id': args.work_id,
        'action_id': args.action_id,
        'step_id': args.step_id,
        'work_revision': args.work_revision,
        'package_digest': args.package_digest,
        'intent_digest': args.intent_digest,
        'actions': tuple(args.required_action),
        'required_capabilities': tuple(args.required_capability),
        'now': args.now,
    }


def run(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--sources-sha256', required=True)
    parser.add_argument('--target-root', type=Path)
    parser.add_argument('--target-hashes', type=Path)
    parser.add_argument('--check-configuration', type=Path)
    parser.add_argument('--check-configuration-sha256')
    parser.add_argument('--check-candidate', type=Path)
    parser.add_argument('--operator-handoff', type=Path)
    parser.add_argument('--protect', type=Path, action='append')
    parser.add_argument('--clone-source-root', type=Path)
    parser.add_argument('--clone-manifest', type=Path)
    parser.add_argument('--clone-manifest-sha256')
    parser.add_argument('--clone-root', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--library-id')
    parser.add_argument('--work-id')
    parser.add_argument('--action-id')
    parser.add_argument('--step-id')
    parser.add_argument('--work-revision', type=int)
    parser.add_argument('--package-digest')
    parser.add_argument('--intent-digest')
    parser.add_argument('--required-action', action='append', default=[])
    parser.add_argument('--required-capability', action='append', default=[])
    parser.add_argument('--now')
    parser.add_argument('--continuation-operation-ref')
    parser.add_argument('--continuation-attempt', type=int)
    parser.add_argument('--continuation-dispatch-version', type=int)
    parser.add_argument('--continuation-acp-revision', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)

    clone_args = (args.clone_source_root, args.clone_manifest, args.clone_manifest_sha256,
                  args.clone_root, args.library_id)
    if any(value is not None for value in clone_args) and not all(
            value is not None for value in clone_args):
        raise PreparationRefusal(CLONE_ROOT_UNAVAILABLE,
            'clone source root, manifest, manifest digest, clone root and library id '
            'are required together')
    if (args.target_root is None) != (args.target_hashes is None):
        raise PreparationRefusal(TARGET_HASHES_INVALID,
            'target root and target hashes are required together')
    if args.check_configuration is not None and not args.check_configuration_sha256:
        raise PreparationRefusal(CHECK_CONFIGURATION_CHANGED,
            'check configuration digest is required with its file')

    continuation = None
    given = (args.continuation_operation_ref, args.continuation_attempt,
             args.continuation_dispatch_version, args.continuation_acp_revision)
    if any(value is not None for value in given):
        continuation = continuation_selector(
            operation_ref=args.continuation_operation_ref,
            attempt=args.continuation_attempt,
            dispatch_version=args.continuation_dispatch_version,
            acp_revision=args.continuation_acp_revision)
    protected_before = snapshot_protected(args.protect)
    report = {
        'stage': STAGE,
        'models': 0,
        'new_unit': 0,
        'new_grant': 0,
        'new_dispatch': 0,
        'real_database_touched': False,
        'original_library_touched': False,
        'credential_live': False,
        'real_jev_or_grant_proven': False,
        'business_dispatch_ready': False,
        'real_mode': 'gated_in_process' if args.execute else 'not_requested',
    }
    report['source_files'] = verify_sources(args.sources, args.sources_sha256)
    if args.target_root is not None:
        report['target_files'] = verify_target(args.target_root, args.target_hashes)
        report['target_unchanged'] = True
    if args.operator_handoff is not None:
        report['operator_source_verified'] = True
        report.update(verify_operator_handoff(args.operator_handoff))
    if args.check_configuration is not None:
        report['check_configuration_sha256'] = verify_check_configuration(
            args.check_configuration, args.check_configuration_sha256)
    if args.check_candidate is not None:
        report.update(verify_check_candidate(args.check_candidate))
    clone_result = None
    if args.clone_source_root is not None:
        manifest = load_clone_manifest(args.clone_manifest, args.clone_manifest_sha256)
        clone_result = clone_frozen_root(args.clone_source_root, args.clone_root,
                                         manifest=manifest)
        report.update(clone_result)
    if args.evidence is not None:
        expectations = _expectations_from_args(args)
        reference = validate_evidence_reference(args.evidence, expectations)
        report.update(reference)
        report['evidence_validated'] = True
        if clone_result is not None:
            report['case'] = {
                'grant': reference,
                'grant_ref': reference['grant_ref'],
                'expectations': expectations,
                'library_id': args.library_id,
                'pins': {'sources_path': str(args.sources),
                         'sources_sha256': args.sources_sha256},
                'clone': clone_result,
            }
    elif args.execute:
        raise PreparationRefusal(EVIDENCE_MISSING, '--execute requires --evidence')
    if args.execute:
        # The formal invoke needs the in-process runtime handles; the CLI has no
        # way to own them, so it refuses instead of inventing a graph. The real
        # path is ``execute_case(...)`` below, called by the owner-integrated
        # process that holds application_ports_factory/engineering_options.
        raise PreparationRefusal(RUNTIME_SEAM_UNAVAILABLE,
            'call execute_case(...) from the process that owns the runtime seam')
    assert_protected_unchanged(protected_before)
    report['protected_targets'] = len(protected_before)
    if args.output is not None:
        report['receipt_written'] = str(write_receipt_exclusive(args.output, report))
    return report


def main(argv=None) -> int:
    try:
        report = run(argv)
    except PreparationRefusal as refusal:
        print(json.dumps(refusal.as_dict(), ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
