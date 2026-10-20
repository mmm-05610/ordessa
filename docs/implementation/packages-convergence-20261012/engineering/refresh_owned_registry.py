"""Refresh the owned Engineering operation registry from the reviewed source delta.

Ownership
---------
Three artifacts move together and are owned by this tool:

* ``adapters/registry/resources/operation_registry.v1.json`` — the canonical
  registry resource the runtime loader consumes;
* ``ENGINEERING_FILES`` in ``adapters/registry/source_integrity.py`` — the pinned
  Engineering source closure;
* ``INFRASTRUCTURE_FILES`` in the same module — the pinned transitive
  Infrastructure closure.

Scope
-----
This is not a general refresher. It is the fixed, one-shot R1 tool that moved
the registry from the reviewed revision 101 to the approved revision 102, and it
has no authority beyond that single transition.

Discipline
----------
Every candidate fact (closure, operations, pins, digests) is assembled and
validated in memory first; the tool writes only after every check passes, so a
refused run leaves the tree byte-identical. A run that finds nothing to change
does not bump the revision.

Facts are locked by *content*, never by path alone, at three points:

* the input registry must be one of the two reviewed byte sequences — the 101
  input (``EXPECTED_PRE_REFRESH_SHA256``) or the approved 102 output
  (``EXPECTED_POST_REFRESH_SHA256``) — so "same path, new bytes" refuses;
* the twelve Infrastructure pins the 101 carries must survive byte-for-byte, so
  a changed digest at the same path refuses;
* the produced registry must equal the approved 102 as whole-file bytes and as
  an ``implementation`` content digest and a ``registry_digest``.

External dependency facts (decision-runtime, pydantic-graph, jsonschema,
referencing and the Decision contract) are checked *before* any "no change"
verdict, so a dependency move refuses the run even when the owned Engineering
tree is byte-identical.

The only drift this tool accepts is the reviewed R1 delta, enumerated below by
exact path: the removed, added and changed Engineering sources, the two added
Infrastructure pins (with their reviewed hashes), and the operation set change.
Any other pin or operation difference refuses the run — the delta is an explicit
allow-list, never a tree scan. The receipt records every changed owned pin so the
accepted content delta stays visible.

I/O
---
A refusal is decided before anything is written, so a refused run makes zero
writes. Publishing is *not* a transaction: each owned file is replaced on its
own, so an I/O failure part-way leaves the earlier files updated. A failed write
is raised, and each target's prior bytes are kept under the Evidence directory as
a backup with a recovery report — there is no automatic rollback.
"""
from pathlib import Path
import ast
import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
import os
import sys
import tempfile
from dataclasses import fields

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'packages/engineering/src/ordessa_engineering'
RESOURCE = SOURCE / 'adapters/registry/resources/operation_registry.v1.json'
INTEGRITY = SOURCE / 'adapters/registry/source_integrity.py'
EVIDENCE = Path(__file__).resolve().parent / 'r1-registry-refresh-20261016'

REGISTRY_ID = 'ordessa-engineering.operations'
REGISTRY_SCHEMA = 'engineering-operation-registry/1'
REGISTRY_KEYS = {'schema_version', 'registry_id', 'revision', 'operations', 'implementation',
                 'implementation_digest', 'registry_digest'}

# Reviewed R1 delta. Exact paths only; nothing else may differ.
APPROVED_ENGINEERING_ADDED = frozenset({
    'adapters/decision/source_bindings.py',
    'adapters/decision/source_reviewer.py',
    'adapters/filesystem/project_sources.py',
    'adapters/persistence/sqlite/method_declaration_codec.py',
    'adapters/persistence/sqlite/package_document_materials.py',
    'application/contracts/declared_generation.py',
    'application/contracts/dispatch_identity.py',
    'application/contracts/source_reviews.py',
    'application/contracts/work_context.py',
    'application/orchestration/declared_prepare_packages.py',
    'application/orchestration/declared_review_change.py',
    'application/orchestration/steps/declared_generation_dispatch.py',
    'application/orchestration/steps/declared_generation_port.py',
    'application/usecases/queries/works.py',
    'application/usecases/works.py',
})
APPROVED_ENGINEERING_REMOVED = frozenset({'application/orchestration/cancellation.py'})
APPROVED_ENGINEERING_CHANGED = frozenset({
    'adapters/native_records/local_bindings.py',
    'adapters/native_records/recorded_dispatch.py',
    'adapters/persistence/sqlite/acceptance_repository.py',
    'adapters/persistence/sqlite/artifact_repository.py',
    'adapters/persistence/sqlite/authorization_repository.py',
    'adapters/persistence/sqlite/blob_store.py',
    'adapters/persistence/sqlite/command_journal.py',
    'adapters/persistence/sqlite/dispatch_repository.py',
    'adapters/persistence/sqlite/dispatch_schema.py',
    'adapters/persistence/sqlite/engineering_library.py',
    'adapters/persistence/sqlite/implementation_repository.py',
    'adapters/persistence/sqlite/method_control.py',
    'adapters/persistence/sqlite/method_repository.py',
    'adapters/persistence/sqlite/migrations.py',
    'adapters/persistence/sqlite/proposal_repository.py',
    'adapters/persistence/sqlite/review_repository.py',
    'adapters/persistence/sqlite/reviewer_assignment_repository.py',
    'adapters/persistence/sqlite/snapshot_store.py',
    'adapters/persistence/sqlite/submission_repository.py',
    'adapters/persistence/sqlite/unit_of_work.py',
    'adapters/persistence/sqlite/workflow_transactions.py',
    'adapters/registry/source_integrity.py',
    'application/api/method_publication.py',
    'application/api/service.py',
    'application/contracts/execution_observations.py',
    'application/contracts/method_controls.py',
    'application/contracts/repositories.py',
    'application/contracts/service_ports.py',
    'application/contracts/source_materials.py',
    'application/contracts/transactions.py',
    'application/orchestration/method_bridge.py',
    'application/orchestration/method_runs.py',
    'application/orchestration/owner_capabilities.py',
    'application/orchestration/steps/implementation_dispatch.py',
    'application/usecases/approvals/service.py',
    'application/usecases/changes/execution_capture.py',
    'application/usecases/owner_operations.py',
    'application/usecases/queries/commands.py',
    'application/usecases/queries/run_waits.py',
    'application/usecases/queries/service.py',
    'application/usecases/support/methods.py',
    'domain/approvals/consent.py',
    'domain/approvals/consent_codec.py',
    'domain/approvals/implementation.py',
    'domain/changes/dispatch.py',
    'domain/changes/dispatch_codec.py',
    'methods/definitions/models/__init__.py',
    'methods/definitions/models/method.py',
    'methods/definitions/schemas/v2.py',
    'methods/entry.py',
})
APPROVED_INFRASTRUCTURE_ADDED = {
    'encoding/immutable_json.py': 'sha256:6258a7f4bde166fb6b5ef63a2f39f09755fff080d71800cd7ce43be00a187e4b',
    'identifiers.py': 'sha256:8517ec005fb76d72dba3edb617e04e6dcbc5db80732ee22f0d7c27ecc5e1ff93',
}
APPROVED_OPERATIONS_REMOVED = frozenset({
    'engineering.runs.cancel', 'engineering.runs.resume', 'engineering.work.bind_inputs',
    'engineering.work.record_command_step', 'engineering.work.record_dispatch_step'})
APPROVED_OPERATIONS_ADDED = frozenset({'engineering.work.invoke'})
APPROVED_OPERATIONS_UPDATED = frozenset({'engineering.work.start'})

_SELF = 'adapters/registry/source_integrity.py'
_INFRASTRUCTURE_PREFIX = 'ordessa_infrastructure:'

# Hard locks for the single reviewed R1 transition (101 -> 102). These are the
# byte-level identities this tool is allowed to see; they are what turns "the
# file at this path" into "these exact bytes", so a registry that is neither the
# reviewed 101 input nor the approved 102 output refuses at the same path.
EXPECTED_PRE_REFRESH_SHA256 = 'b212c3c49d06ae246f80ca97ea4cc82e5a947d08a706702ff6d444f7b0e7dc0d'
EXPECTED_POST_REFRESH_SHA256 = '41fdb6b777a0d90ff0b988c85589dfcb3470654ecf394bf6add074158656ad30'
EXPECTED_POST_REFRESH_IMPLEMENTATION_DIGEST = 'sha256:e3f20868b870e6b9b083e9813b8dbc2cabef650a43f93a41840247c118736075'
EXPECTED_POST_REFRESH_REGISTRY_DIGEST = 'sha256:6dea845d31e19698082de122b10b87dbe4bb57f8c18318b5d3a22f218d56d2d7'

#: The reviewed twelve Infrastructure pins the 101 input carries and the 102
#: output must keep byte-for-byte. Asserted item-by-item against the 101 input,
#: never by count.
EXPECTED_PRE_REFRESH_INFRASTRUCTURE = frozenset({
    '__init__.py',
    'database/__init__.py',
    'database/options.py',
    'database/sqlite.py',
    'encoding/__init__.py',
    'encoding/canonical_json.py',
    'encoding/digests.py',
    'filesystem/__init__.py',
    'filesystem/directories.py',
    'filesystem/errors.py',
    'filesystem/files.py',
    'filesystem/publication.py',
})


class RefreshRefused(Exception):
    """A candidate is not the reviewed delta; nothing is written."""


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return 'sha256:' + _sha256_hex(raw)


def _locked_registry_state(raw: bytes) -> str:
    """The registry resource may only hold the reviewed 101 or approved 102 bytes."""
    digest = _sha256_hex(raw)
    if digest == EXPECTED_PRE_REFRESH_SHA256:
        return 'pre'
    if digest == EXPECTED_POST_REFRESH_SHA256:
        return 'post'
    raise RefreshRefused(f'refusing registry content {digest}: it is neither the '
                         f'locked 101 input nor the approved 102 output')


def _infrastructure_pins(registry: dict) -> dict:
    """The Infrastructure pins a registry carries, keyed by module path."""
    engineering = registry['implementation']['engineering']
    return {key[len(_INFRASTRUCTURE_PREFIX):]: digest for key, digest in engineering.items()
            if key.startswith(_INFRASTRUCTURE_PREFIX)}


def _hash_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise RefreshRefused(f'pinned source is unavailable: {path}') from exc


def _require_digest(name: str, digest: object) -> None:
    if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith('sha256:'):
        raise RefreshRefused(f'pin {name} is not a sha256 digest')


def _require_unique(names, label: str) -> None:
    if len(set(names)) != len(names):
        raise RefreshRefused(f'{label} contains a duplicate entry')


def _manifest_assignment(text: str, name: str):
    for node in ast.parse(text).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return node
    raise RefreshRefused(f'{name} assignment is not present in source_integrity.py')


def _manifest_names(text: str, name: str):
    value = ast.literal_eval(_manifest_assignment(text, name).value)
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise RefreshRefused(f'{name} is not a tuple of names')
    return value


def _render_manifest(text: str, name: str, names) -> str:
    node = _manifest_assignment(text, name)
    lines = text.splitlines(keepends=True)
    updated = ''.join(lines[:node.lineno - 1]) + f'{name} = {tuple(names)!r}\n' + ''.join(lines[node.end_lineno:])
    ast.parse(updated)
    return updated


def current_foreign_facts() -> dict:
    """The Decision/dependency half of ``implementation_facts`` (no Engineering scan)."""
    from ordessa_engineering.adapters.registry.source_integrity import DECISION_RUNTIME_FILES
    from decision_runtime import DecisionRequest
    root = Path(importlib.import_module('decision_runtime').__file__).parent
    return {
        'decision_runtime': {name: _hash_path(root / name) for name in DECISION_RUNTIME_FILES},
        'decision_runtime_version': importlib.metadata.version('decision-runtime'),
        'decision_contract_version': next((item.default for item in fields(DecisionRequest)
                                           if item.name == 'contract_version'), None),
        'pydantic_graph_version': importlib.metadata.version('pydantic-graph'),
        'jsonschema_version': importlib.metadata.version('jsonschema'),
        'referencing_version': importlib.metadata.version('referencing'),
    }


def current_operations() -> dict:
    """The live operation contracts the loader pins."""
    from ordessa_engineering.application.api import EngineeringService
    return {declared.capability_id: {'version': declared.interface_version,
                                     'inputs': declared.contract['input_schema'],
                                     'results': declared.contract['workflow_outcomes']}
            for declared in EngineeringService.operation_capabilities().capabilities}


def _load_old(raw: bytes) -> dict:
    try:
        old = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RefreshRefused('registry resource is not valid JSON') from exc
    if not isinstance(old, dict) or set(old) != REGISTRY_KEYS:
        raise RefreshRefused('registry resource has an unexpected shape')
    if old['schema_version'] != REGISTRY_SCHEMA or old['registry_id'] != REGISTRY_ID:
        raise RefreshRefused('registry resource identity mismatch')
    if type(old['revision']) is not int or old['revision'] < 1:
        raise RefreshRefused('registry revision is invalid')
    return old


def _content_digest(value) -> str:
    from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
    return content_digest(value)


def build_plan(*, old_bytes: bytes, integrity_text: str, engineering_hashes: dict,
               infrastructure_hashes: dict, foreign_facts: dict, operations: dict):
    """Return the new texts and receipt, or ``None`` when nothing changed.

    Pure: reads and writes nothing. Raises :class:`RefreshRefused` on any drift
    that is not the reviewed delta, so the caller can abort before writing.
    """
    old = _load_old(old_bytes)
    # Content lock on the input: the resource is only ever allowed to hold the
    # reviewed 101 bytes or the approved 102 bytes. A path lock alone would
    # accept "same path, new bytes".
    state = _locked_registry_state(old_bytes)
    if old['implementation_digest'] != _content_digest(old['implementation']):
        raise RefreshRefused('implementation_digest does not match the pinned implementation')
    if old['registry_digest'] != _content_digest({k: v for k, v in old.items() if k != 'registry_digest'}):
        raise RefreshRefused('registry_digest does not match the registry content')

    # External dependency facts come first: a Decision or dependency move refuses
    # the run even when the owned Engineering tree is byte-identical, so a
    # "no change" verdict is never reported on stale dependency evidence.
    if {k: v for k, v in old['implementation'].items() if k != 'engineering'} != foreign_facts:
        raise RefreshRefused('Decision or dependency drift; not authorized to repin')

    current_engineering = _manifest_names(integrity_text, 'ENGINEERING_FILES')
    current_infrastructure = _manifest_names(integrity_text, 'INFRASTRUCTURE_FILES')
    _require_unique(current_engineering, 'ENGINEERING_FILES')
    _require_unique(current_infrastructure, 'INFRASTRUCTURE_FILES')

    candidate_engineering = tuple(sorted(engineering_hashes))
    candidate_infrastructure = tuple(sorted(infrastructure_hashes))
    _require_unique(candidate_engineering, 'candidate Engineering closure')
    _require_unique(candidate_infrastructure, 'candidate Infrastructure closure')
    for name, digest in engineering_hashes.items():
        _require_digest(name, digest)
    for name, digest in infrastructure_hashes.items():
        _require_digest(name, digest)
    if _SELF not in engineering_hashes:
        raise RefreshRefused('the source_integrity module is missing from the closure')

    # Content lock on the reviewed Infrastructure closure: every pin the input
    # carries must survive byte-for-byte. Comparing names (the path lock) would
    # accept the same path with changed bytes.
    input_infrastructure = _infrastructure_pins(old)
    if state == 'pre' and frozenset(input_infrastructure) != EXPECTED_PRE_REFRESH_INFRASTRUCTURE:
        raise RefreshRefused('the 101 input does not carry the reviewed twelve Infrastructure pins')
    for name, digest in input_infrastructure.items():
        if infrastructure_hashes.get(name) != digest:
            raise RefreshRefused(f'Infrastructure pin {name} is not preserved byte-for-byte')

    # Prepare the complete candidate in memory before any drift is judged.
    new_integrity_text = _render_manifest(
        _render_manifest(integrity_text, 'ENGINEERING_FILES', candidate_engineering),
        'INFRASTRUCTURE_FILES', candidate_infrastructure)
    engineering_hashes = dict(engineering_hashes)
    engineering_hashes[_SELF] = _sha256_bytes(new_integrity_text.encode('utf-8'))

    previous = old['implementation']['engineering']
    engineering_facts = dict(engineering_hashes)
    engineering_facts.update({'ordessa_infrastructure:' + name: digest
                              for name, digest in infrastructure_hashes.items()})
    implementation = {**old['implementation'], 'engineering': engineering_facts}

    # Idempotence: an unchanged tree must not bump the revision.
    if implementation == old['implementation'] and operations == old['operations'] \
            and new_integrity_text == integrity_text:
        return None

    engineering_added = frozenset(candidate_engineering) - frozenset(current_engineering)
    engineering_removed = frozenset(current_engineering) - frozenset(candidate_engineering)
    if engineering_added != APPROVED_ENGINEERING_ADDED or engineering_removed != APPROVED_ENGINEERING_REMOVED:
        raise RefreshRefused(f'unapproved Engineering closure drift: '
                             f'added={sorted(engineering_added - APPROVED_ENGINEERING_ADDED)} '
                             f'removed={sorted(engineering_removed - APPROVED_ENGINEERING_REMOVED)}')
    engineering_changed = frozenset(name for name, digest in engineering_hashes.items()
                                    if name in previous and previous[name] != digest)
    if engineering_changed != APPROVED_ENGINEERING_CHANGED:
        raise RefreshRefused(f'unapproved Engineering content drift: '
                             f'unexpected={sorted(engineering_changed - APPROVED_ENGINEERING_CHANGED)} '
                             f'missing={sorted(APPROVED_ENGINEERING_CHANGED - engineering_changed)}')

    infrastructure_added = frozenset(candidate_infrastructure) - frozenset(current_infrastructure)
    infrastructure_removed = frozenset(current_infrastructure) - frozenset(candidate_infrastructure)
    if infrastructure_added != frozenset(APPROVED_INFRASTRUCTURE_ADDED) or infrastructure_removed:
        raise RefreshRefused('unapproved Infrastructure pin drift')
    for name, digest in APPROVED_INFRASTRUCTURE_ADDED.items():
        if infrastructure_hashes.get(name) != digest:
            raise RefreshRefused(f'pinned Infrastructure source {name} does not match the reviewed hash')

    operations_removed = frozenset(old['operations']) - frozenset(operations)
    operations_added = frozenset(operations) - frozenset(old['operations'])
    operations_updated = frozenset(name for name in set(operations) & set(old['operations'])
                                   if operations[name] != old['operations'][name])
    if (operations_removed != APPROVED_OPERATIONS_REMOVED or operations_added != APPROVED_OPERATIONS_ADDED
            or operations_updated != APPROVED_OPERATIONS_UPDATED):
        raise RefreshRefused(f'unapproved operation change: removed={sorted(operations_removed)} '
                             f'added={sorted(operations_added)} updated={sorted(operations_updated)}')

    revision = old['revision'] + 1
    value = {**old, 'revision': revision, 'operations': operations, 'implementation': implementation}
    value['implementation_digest'] = _content_digest(implementation)
    value['registry_digest'] = _content_digest({k: v for k, v in value.items() if k != 'registry_digest'})
    new_registry_text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n'

    # Content locks on the output: the candidate must be the approved 102 — as
    # whole-file bytes and, so a mismatch names its section rather than only
    # failing a byte count, as the implementation and registry content digests.
    if _sha256_hex(new_registry_text.encode('utf-8')) != EXPECTED_POST_REFRESH_SHA256:
        raise RefreshRefused('candidate registry is not the approved 102 resource')
    if value['implementation_digest'] != EXPECTED_POST_REFRESH_IMPLEMENTATION_DIGEST:
        raise RefreshRefused('candidate implementation pins are not the approved 102 pins')
    if value['registry_digest'] != EXPECTED_POST_REFRESH_REGISTRY_DIGEST:
        raise RefreshRefused('candidate registry content is not the approved 102 content')

    receipt = {
        'unpublished': True, 'registration': False,
        'before_revision': old['revision'], 'after_revision': revision,
        'before_resource_sha256': hashlib.sha256(old_bytes).hexdigest(),
        'after_resource_sha256': _sha256_hex(new_registry_text.encode('utf-8')),
        'registry_digest': value['registry_digest'], 'implementation_digest': value['implementation_digest'],
        'engineering_closure_entries': len(engineering_hashes),
        'infrastructure_closure_entries': len(infrastructure_hashes),
        'operation_entries': len(operations),
        'added_owned_source': sorted(APPROVED_ENGINEERING_ADDED),
        'removed_owned_source': sorted(APPROVED_ENGINEERING_REMOVED),
        'changed_owned_source': {name: {'before': previous.get(name), 'after': engineering_hashes[name]}
                                 for name in sorted(engineering_changed)},
        'added_infrastructure_source': sorted(APPROVED_INFRASTRUCTURE_ADDED),
        'removed_operations': sorted(APPROVED_OPERATIONS_REMOVED),
        'added_operations': sorted(APPROVED_OPERATIONS_ADDED),
        'updated_operations': sorted(APPROVED_OPERATIONS_UPDATED),
        'foreign_facts_unchanged': True,
    }
    return {'new_integrity_text': new_integrity_text, 'new_registry_text': new_registry_text, 'receipt': receipt}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _publish(plan: dict) -> None:
    """Write the planned artifacts, keeping recoverable evidence.

    This is deliberately not a transaction: each target is replaced on its own,
    so an I/O failure part-way leaves the earlier targets updated. Only the
    precheck refusal is guaranteed to write nothing. To keep a failed write
    recoverable, every existing target's previous bytes are copied under the
    Evidence directory first and a ``RECOVERY.json`` report names what was
    already written when a write fails — there is no automatic rollback.
    """
    targets = (
        ('source_integrity.py', INTEGRITY, plan['new_integrity_text']),
        ('operation_registry.v1.json', RESOURCE, plan['new_registry_text']),
        ('RECEIPT.json', EVIDENCE / 'RECEIPT.json',
         json.dumps(plan['receipt'], indent=2, sort_keys=True) + '\n'),
    )
    backups = EVIDENCE / 'backup-before-r102'
    backups.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, path, text in targets:
        if path.exists():
            _write_atomic(backups / name, path.read_text(encoding='utf-8'))
        try:
            _write_atomic(path, text)
        except OSError as exc:
            _write_recovery(name, written, [target[0] for target in targets], backups, exc)
            raise
        written.append(name)


def _write_recovery(failed: str, written, planned, backups: Path, exc: OSError) -> None:
    """Best-effort report so a half-published run can be restored by hand."""
    report = {
        'outcome': 'write-failed', 'failed_target': failed,
        'already_written': list(written),
        'not_written': [name for name in planned if name not in written and name != failed],
        'backup_dir': str(backups),
        'error': f'{type(exc).__name__}: {exc}',
        'note': ('multi-file replacement is not atomic; restore any already_written '
                 'target from its backup copy by hand'),
    }
    try:
        (EVIDENCE / 'RECOVERY.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n',
                                                encoding='utf-8')
    except OSError:
        pass


def main() -> int:
    old_bytes = RESOURCE.read_bytes()
    integrity_text = INTEGRITY.read_text(encoding='utf-8')
    old = _load_old(old_bytes)
    current_infrastructure = _manifest_names(integrity_text, 'INFRASTRUCTURE_FILES')

    candidate_engineering = tuple(sorted(p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*.py')
                                         if '__pycache__' not in p.parts))
    candidate_infrastructure = tuple(sorted(set(current_infrastructure) | set(APPROVED_INFRASTRUCTURE_ADDED)))
    infrastructure_root = importlib.resources.files('ordessa_infrastructure')

    plan = build_plan(
        old_bytes=old_bytes, integrity_text=integrity_text,
        engineering_hashes={name: _hash_path(SOURCE / name) for name in candidate_engineering},
        infrastructure_hashes={name: _hash_path(infrastructure_root / name) for name in candidate_infrastructure},
        foreign_facts=current_foreign_facts(), operations=current_operations())
    if plan is None:
        print(f'No owned source drift; revision {old["revision"]} unchanged')
        return 0
    if RESOURCE.read_bytes() != old_bytes or INTEGRITY.read_text(encoding='utf-8') != integrity_text:
        raise RefreshRefused('the tree changed while the candidate was being planned')
    _publish(plan)
    print(json.dumps(plan['receipt'], indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
