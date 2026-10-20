"""The case entry prepares, clones and only then executes one declared action.

Environment-free: every fixture is temporary. Not part of the default suites;
run it explicitly with the nightly venv:

    .venv-nightly/bin/python -m pytest \
        tooling/checks/server_product/test_run_declared_work_case.py -q

The owner-record and execution cases use the real schema-17 Engineering library
and the real declared-dispatch line from the engineering test fixtures (a
controlled transport: no Unit, no model, no server). The point of the file is
that every refusal is typed and byte-preserving, that one copied database is
never mistaken for a complete graph, that the Grant/control/budget come from
the cloned owner records rather than from the evidence JSON, and that a failed
receipt never erases the original failure.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
ENTRY_PATH = REPO / 'tooling/checks/server_product/run_declared_work_case.py'
ENGINEERING_TESTS = REPO / 'packages/engineering/tests/application'
REQUIRED = ('engineering.sqlite', 'environments.sqlite', 'product/state/core.sqlite',
            'product/state/agentbox.sqlite', 'product/state/agent-owner/operations.sqlite')


def _load():
    spec = importlib.util.spec_from_file_location('run_declared_work_case', ENTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register like a normal import: dataclasses resolves the owner module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ENTRY = _load()


def _engineering_tests_on_path():
    if str(ENGINEERING_TESTS) not in sys.path:
        sys.path.insert(0, str(ENGINEERING_TESTS))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sources(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, str]:
    values = {}
    for name, raw in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        values[str(path)] = _sha(path.read_bytes())
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps(values))
    return manifest, _sha(manifest.read_bytes())


def _target(tmp_path: Path, files: dict[str, bytes | None]) -> tuple[Path, Path]:
    root = tmp_path / 'target'
    root.mkdir(exist_ok=True)
    values = {}
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is None:
            if path.exists():
                path.unlink()
            values[name] = None
            continue
        path.write_bytes(raw)
        values[name] = _sha(path.read_bytes())
    hashes = tmp_path / 'target-hashes.json'
    hashes.write_text(json.dumps(values))
    return root, hashes


def _handoff(tmp_path: Path, *, tamper: str | None = None) -> Path:
    directory = tmp_path / 'handoff'
    directory.mkdir(parents=True, exist_ok=True)
    files = {'operator.py': b'# operator\n', 'case_runtime.py': b'# case runtime\n'}
    entries = []
    for name, raw in files.items():
        (directory / name).write_bytes(raw if tamper != name else raw + b'# drifted\n')
        entries.append({'file': name, 'sha256': _sha(raw), 'byte_length': len(raw)})
    (directory / 'manifest.json').write_text(json.dumps({
        'schema_version': 1,
        'byte_for_byte_verified': True,
        'databases_credentials_or_runtime_state_copied': False,
        'handoff_version': 'local-library-operator-source-handoff/20261017-r1',
        'files': entries}))
    return directory


def _frozen_root(tmp_path: Path, name: str = 'frozen-root') -> tuple[Path, Path, str]:
    """A complete frozen data root made of real (empty) SQLite files."""
    root = tmp_path / name
    for entry in REQUIRED:
        path = root / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as database:
            database.execute('CREATE TABLE IF NOT EXISTS frozen (value TEXT)')
            database.execute("INSERT INTO frozen VALUES ('reviewed')")
    (root / 'caller-files').mkdir(exist_ok=True)
    (root / 'caller-files' / 'baseline.txt').write_bytes(b'baseline bytes\n')
    manifest = {path.relative_to(root).as_posix(): _sha(path.read_bytes())
                for path in sorted(root.rglob('*')) if path.is_file()}
    manifest_path = tmp_path / f'{name}-manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    return root, manifest_path, _sha(manifest_path.read_bytes())


# ------------------------------------------------------------ source pins

def test_prepared_check_only_verifies_pins_and_claims_zero_effects(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n', 'b/c.py': b'two\n'})
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest])
    assert report['stage'] == 'PREPARED_CHECK_ONLY'
    assert report['models'] == 0 and report['new_unit'] == 0
    assert report['new_grant'] == 0 and report['new_dispatch'] == 0
    assert report['real_database_touched'] is False
    assert report['original_library_touched'] is False
    assert report['credential_live'] is False
    assert report['real_jev_or_grant_proven'] is False
    assert report['business_dispatch_ready'] is False
    assert report['source_files'] == 2


def test_sources_manifest_is_verified_and_drift_is_refused(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    assert ENTRY.verify_sources(manifest, digest) == 1
    (tmp_path / 'a.py').write_bytes(b'two\n')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.verify_sources(manifest, digest)
    assert refused.value.code == 'WORK_CASE_SOURCE_DRIFT'
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.verify_sources(manifest, '0' * 64)
    assert refused.value.code == 'WORK_CASE_SOURCES_MANIFEST_CHANGED'


def test_target_baseline_is_checked_and_absence_stays_absence(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    root, hashes = _target(tmp_path, {'catalog/views.py': b'v1\n',
                                      'catalog/tests/test_search.py': None})
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                        '--target-root', str(root), '--target-hashes', str(hashes)])
    assert report['target_files'] == 2 and report['target_unchanged'] is True
    (root / 'catalog/views.py').write_bytes(b'v2\n')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                   '--target-root', str(root), '--target-hashes', str(hashes)])
    assert refused.value.code == 'WORK_CASE_TARGET_CHANGED'


def test_operator_handoff_is_verified_and_drift_refused(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    handoff = _handoff(tmp_path)
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                        '--operator-handoff', str(handoff)])
    assert report['operator_source_verified'] is True
    assert report['operator_sha256'] == _sha(b'# operator\n')
    assert report['case_runtime_sha256'] == _sha(b'# case runtime\n')
    drifted = _handoff(tmp_path / 'x', tamper='case_runtime.py')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                   '--operator-handoff', str(drifted)])
    assert refused.value.code == 'WORK_CASE_OPERATOR_HANDOFF_CHANGED'
    assert refused.value.detail == 'case_runtime.py'


def test_check_candidate_is_reported_as_candidate_not_frozen(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    candidate = tmp_path / 'recovery'
    candidate.mkdir()
    interpreter = tmp_path / 'python'
    interpreter.write_bytes(b'#!/bin/sh\n')
    tree = 'f' * 64
    (candidate / 'configuration-candidate.json').write_text(json.dumps({
        'runtime_tree_digest': tree,
        'pinned_files': {str(interpreter): _sha(interpreter.read_bytes())}}))
    (candidate / 'identity.json').write_text(json.dumps({'runtime_tree_digest': tree}))
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                        '--check-candidate', str(candidate)])
    assert report['check_candidate_status'] == 'candidate_not_frozen'
    (candidate / 'identity.json').write_text(json.dumps({'runtime_tree_digest': 'e' * 64}))
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                   '--check-candidate', str(candidate)])
    assert refused.value.code == 'WORK_CASE_CHECK_CANDIDATE_CHANGED'


def test_receipt_is_exclusive_and_never_overwrites(tmp_path, monkeypatch):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / 'cache')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                   '--output', str(tmp_path / 'elsewhere' / 'receipt.json')])
    assert refused.value.code == 'WORK_CASE_OUTPUT_OUTSIDE_CACHE'
    inside = tmp_path / 'cache' / 'case' / 'receipt.json'
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                        '--output', str(inside)])
    assert report['receipt_written'] == str(inside)
    first = inside.read_bytes()
    assert json.loads(first)['stage'] == 'PREPARED_CHECK_ONLY'
    assert inside.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                   '--output', str(inside)])
    assert refused.value.code == 'WORK_CASE_OUTPUT_EXISTS'
    assert inside.read_bytes() == first


def test_protected_targets_are_byte_identical_after_preparation(tmp_path):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    receipt = tmp_path / 'old-receipt.json'
    receipt.write_bytes(b'{"old":true}\n')
    report = ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest,
                        '--protect', str(receipt)])
    assert report['protected_targets'] == 1
    assert receipt.read_bytes() == b'{"old":true}\n'
    before = ENTRY.snapshot_protected([receipt])
    receipt.write_bytes(b'changed')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.assert_protected_unchanged(before)
    assert refused.value.code == 'WORK_CASE_PROTECTED_TARGET_CHANGED'


# ------------------------------------------------------------------ clone

def test_clone_copies_the_whole_root_and_checkpoints_its_databases(tmp_path):
    root, manifest_path, manifest_sha = _frozen_root(tmp_path)
    manifest = ENTRY.load_clone_manifest(manifest_path, manifest_sha)
    clone = ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    assert clone['clone_verified'] is True
    assert clone['clone_files'] == len(manifest)
    assert set(clone['clone_checkpointed']) == {
        name for name in manifest if name.endswith('.sqlite')}
    for name, digest in clone['clone_manifest'].items():
        assert ENTRY._file_digest(Path(clone['clone_root']) / name) == digest
    with sqlite3.connect(Path(clone['clone_library'])) as database:
        assert database.execute('SELECT value FROM frozen').fetchone()[0] == 'reviewed'
    assert not list(Path(clone['clone_root']).rglob('*-wal'))
    for name, digest in manifest.items():
        assert ENTRY._file_digest(root / name) == digest


def test_clone_refuses_a_single_file_root_and_an_incomplete_manifest(tmp_path):
    root = tmp_path / 'one-file'
    root.mkdir()
    (root / 'engineering.sqlite').write_bytes(b'not-a-graph')
    manifest_path = tmp_path / 'm.json'
    manifest_path.write_text(json.dumps({'engineering.sqlite': _sha(b'not-a-graph')}))
    manifest = ENTRY.load_clone_manifest(manifest_path, _sha(manifest_path.read_bytes()))
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    assert refused.value.code == 'WORK_CASE_CLONE_NOT_COMPLETE'


def test_clone_refuses_unlisted_extra_files_and_digest_drift(tmp_path):
    root, manifest_path, manifest_sha = _frozen_root(tmp_path)
    manifest = ENTRY.load_clone_manifest(manifest_path, manifest_sha)
    (root / 'extra.txt').write_bytes(b'unexpected')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    assert refused.value.code == 'WORK_CASE_CLONE_MANIFEST_INCOMPLETE'
    (root / 'extra.txt').unlink()
    (root / 'engineering.sqlite').write_bytes(b'drifted')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    assert refused.value.code == 'WORK_CASE_CLONE_MANIFEST_CHANGED'


def test_clone_refuses_a_root_inside_the_source_and_a_used_root(tmp_path):
    root, manifest_path, manifest_sha = _frozen_root(tmp_path)
    manifest = ENTRY.load_clone_manifest(manifest_path, manifest_sha)
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.clone_frozen_root(root, root / 'nested', manifest=manifest)
    assert refused.value.code == 'WORK_CASE_CLONE_ROOT_UNAVAILABLE'
    used = tmp_path / 'used'
    used.mkdir()
    (used / 'x').write_bytes(b'x')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.clone_frozen_root(root, used, manifest=manifest)
    assert refused.value.code == 'WORK_CASE_CLONE_ROOT_EXISTS'


def test_clone_manifest_digest_is_pinned(tmp_path):
    _, manifest_path, _ = _frozen_root(tmp_path)
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.load_clone_manifest(manifest_path, '0' * 64)
    assert refused.value.code == 'WORK_CASE_CLONE_MANIFEST_CHANGED'


def test_verify_clone_root_refuses_a_tampered_clone(tmp_path):
    root, manifest_path, manifest_sha = _frozen_root(tmp_path)
    manifest = ENTRY.load_clone_manifest(manifest_path, manifest_sha)
    clone = ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    ENTRY.verify_clone_root(Path(clone['clone_root']), clone['clone_manifest'])
    (Path(clone['clone_root']) / 'environments.sqlite').write_bytes(b'tampered')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.verify_clone_root(Path(clone['clone_root']), clone['clone_manifest'])
    assert refused.value.code == 'WORK_CASE_CLONE_COPY_MISMATCH'


def test_build_clone_runtime_verifies_the_clone_and_uses_the_owner_factory(
        tmp_path, monkeypatch):
    root, manifest_path, manifest_sha = _frozen_root(tmp_path)
    manifest = ENTRY.load_clone_manifest(manifest_path, manifest_sha)
    clone = ENTRY.clone_frozen_root(root, tmp_path / 'clone', manifest=manifest)
    calls = {}

    def fake_build(data_root, *, pi_selection=None, pi_ports=None, **options):
        calls.update(data_root=Path(data_root), options=options,
                     pi_selection=pi_selection, pi_ports=pi_ports)
        # The real runtime hands its own Engineering owners to this seam.
        owners = SimpleNamespace(
            library=SimpleNamespace(path=Path(clone['clone_library']),
                                    library_id='controlled-library'),
            authority_id='controlled-library')
        options['application_ports_factory'](owners, 'access', 'scope')
        return 'runtime'

    module = type(sys)('ordessa_server.composition.product_runtime')
    module.build_product_runtime = fake_build
    monkeypatch.setitem(sys.modules, 'ordessa_server.composition.product_runtime', module)
    factory = lambda *args: 'ports'  # noqa: E731 - identity only
    runtime, verified = ENTRY.build_clone_runtime(
        clone_root=Path(clone['clone_root']), manifest=clone['clone_manifest'],
        application_ports_factory=factory, engineering_options={'scope': 'unused'})
    assert runtime == 'runtime'
    assert verified['clone_verified'] is True
    binding = verified['graph_binding']
    assert type(binding) is ENTRY.CloneGraphBinding
    assert binding.runtime == 'runtime'
    assert binding.library_id == 'controlled-library'
    assert binding.library_path == str(Path(clone['clone_root']) / 'engineering.sqlite')
    assert binding.access == 'access'
    assert verified['clone_product_root'] == str(Path(clone['clone_root']) / 'product')
    assert calls['data_root'] == Path(clone['clone_root']) / 'product'
    passed = calls['options']['application_ports_factory']
    assert callable(passed) and passed is not factory
    assert passed('f', 'a', 's') == 'ports'   # the wrapper delegates to it
    assert calls['options']['library_path'] == str(Path(clone['clone_root']) / 'engineering.sqlite')
    assert 'method_unit_options' not in calls['options']
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.build_clone_runtime(clone_root=Path(clone['clone_root']),
                                  manifest=clone['clone_manifest'],
                                  application_ports_factory=None,
                                  engineering_options={'scope': 'unused'})
    assert refused.value.code == 'WORK_CASE_RUNTIME_SEAM_UNAVAILABLE'


# ------------------------------------------------------- real owner records

def _now():
    from test_real_source_chain import NOW
    return NOW


@contextmanager
def _real_graph(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_work_package_dispatch_v2 import dispatch_fixture
    monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',
                        lambda: _now())
    root = tmp_path / 'graph'
    root.mkdir()
    with dispatch_fixture(root, monkeypatch) as fixture:
        yield fixture


def _grant_reference(fixture):
    from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
    from ordessa_infrastructure.encoding import decode_json
    value = decode_json(fixture['grant_result'].result_bytes)
    return decode_approval_ref(value['approval_ref'])


def _expectations(fixture, ref):
    from test_real_source_chain import SCOPE
    with fixture['factory'].begin(SCOPE, 'read') as uow:
        grant = uow.authorization.get_grant(ref)
    authorization = grant.intent.authorization
    return {
        'work_id': authorization.work_id,
        'action_id': authorization.action_id,
        'step_id': authorization.step_id,
        'work_revision': authorization.work_revision,
        'package_digest': authorization.package_ref.digest.hex,
        'intent_digest': grant.intent.digest.hex,
        'actions': tuple(authorization.actions),
        'required_capabilities': ('engineering.work.invoke',),
    }


def test_owner_records_come_from_the_library_not_from_the_reference(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from dataclasses import asdict
    from test_real_source_chain import SCOPE
    with _real_graph(tmp_path, monkeypatch) as fixture:
        ref = _grant_reference(fixture)
        expectations = _expectations(fixture, ref)
        owner = ENTRY.read_case_records(factory=fixture['factory'], scope=SCOPE,
                                        grant_ref=asdict(ref), expectations=expectations)
        assert owner['grant_digest'] == expectations['intent_digest']
        assert owner['work']['work_id'] == expectations['work_id']
        assert owner['budget'] == {'edit_repository': {'limit': 1, 'consumed': 0},
                                   'run_checks': {'limit': 1, 'consumed': 0}}
        assert owner['control']['state'] == 'granted'
        wrong = dict(expectations, work_id='another-work')
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.read_case_records(factory=fixture['factory'], scope=SCOPE,
                                    grant_ref=asdict(ref), expectations=wrong)
        assert refused.value.code == 'WORK_CASE_GRANT_MISMATCH'
        wrong_digest = dict(expectations, package_digest='0' * 64)
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.read_case_records(factory=fixture['factory'], scope=SCOPE,
                                    grant_ref=asdict(ref), expectations=wrong_digest)
        assert refused.value.code == 'WORK_CASE_GRANT_MISMATCH'


def test_owner_records_refuse_an_expired_window(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from dataclasses import asdict
    from test_real_source_chain import SCOPE
    with _real_graph(tmp_path, monkeypatch) as fixture:
        ref = _grant_reference(fixture)
        expectations = _expectations(fixture, ref)
        monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',
                            lambda: '2027-01-01T00:00:00.000000Z')
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.read_case_records(factory=fixture['factory'], scope=SCOPE,
                                    grant_ref=asdict(ref), expectations=expectations)
        assert refused.value.code == 'WORK_CASE_GRANT_EXPIRED'


def test_owner_records_refuse_an_existing_attempt(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from dataclasses import asdict
    from test_real_source_chain import SCOPE
    from test_work_package_dispatch_v2 import call
    with _real_graph(tmp_path, monkeypatch) as fixture:
        ref = _grant_reference(fixture)
        expectations = _expectations(fixture, ref)
        call(fixture)  # the real declared dispatch writes the attempt row
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.read_case_records(factory=fixture['factory'], scope=SCOPE,
                                    grant_ref=asdict(ref), expectations=expectations)
        assert refused.value.code == 'WORK_CASE_ATTEMPT_ALREADY_EXISTS'


# ------------------------------------------------------------- execution

class _Runtime:
    def __init__(self, handlers):
        self.handlers = handlers
        self.data_root = None
        self.plugin_host = SimpleNamespace(
            methods=SimpleNamespace(lookup=lambda name: (
                SimpleNamespace(handler=handlers[name]) if name in handlers else None)))


class _BoundFactory:
    """The real owner's UoW factory as the ports factory handed it over.

    ``library`` names the clone the runtime opened; ``begin`` delegates to the
    graph's own factory (the engineering test fixture).
    """

    def __init__(self, real, *, library_path, library_id):
        self.real = real
        self.library = SimpleNamespace(path=Path(library_path),
                                       library_id=library_id)
        self.authority_id = library_id

    def begin(self, scope, mode='write'):
        return self.real.begin(scope, mode)


def _case_for(fixture, tmp_path, *, expectations=None, handlers=None):
    """Build the verified clone **and** the runtime it was built over."""
    from dataclasses import asdict
    _engineering_tests_on_path()
    ref = _grant_reference(fixture)
    expectations = expectations or _expectations(fixture, ref)
    library = fixture['factory'].library
    source = tmp_path / 'source-root'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'engineering.sqlite').write_bytes(Path(library.path).read_bytes())
    for name in REQUIRED[1:]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as database:
            database.execute('CREATE TABLE IF NOT EXISTS frozen (value TEXT)')
    manifest = {path.relative_to(source).as_posix(): _sha(path.read_bytes())
                for path in sorted(source.rglob('*')) if path.is_file()}
    clone_root = tmp_path / 'case-clone'
    cloned = ENTRY.clone_frozen_root(source, clone_root, manifest=manifest)
    runtime = _Runtime({} if handlers is None else handlers)
    clonepath = clone_root / 'engineering.sqlite'
    bound = _BoundFactory(fixture['factory'], library_path=clonepath,
                          library_id=library.library_id)

    def fake_build(data_root, *, pi_selection=None, pi_ports=None, **options):
        # The product runtime hands its own owners to the ports factory; the
        # entry must capture exactly these.
        options['application_ports_factory'](bound, 'access', 'scope')
        return runtime

    fake = type(sys)('ordessa_server.composition.product_runtime')
    fake.build_product_runtime = fake_build
    saved = sys.modules.get('ordessa_server.composition.product_runtime')
    sys.modules['ordessa_server.composition.product_runtime'] = fake
    try:
        _, clone = ENTRY.build_clone_runtime(
            clone_root=clone_root, manifest=cloned['clone_manifest'],
            application_ports_factory=lambda *a: 'ports',
            engineering_options={'scope': 'unused'})
    finally:
        if saved is None:
            sys.modules.pop('ordessa_server.composition.product_runtime', None)
        else:
            sys.modules['ordessa_server.composition.product_runtime'] = saved
    evidence = tmp_path / 'evidence.json'
    evidence.write_text(json.dumps({
        'grant': {
            'ref': asdict(ref), 'digest': expectations['intent_digest'],
            'work_id': expectations['work_id'], 'action_id': expectations['action_id'],
            'step_id': expectations['step_id'],
            'work_revision': expectations['work_revision'],
            'package_digest': expectations['package_digest'],
            'intent_digest': expectations['intent_digest'],
            'actions': list(expectations['actions']),
        },
        'budget': {'actions': {'edit_repository': {'limit': 1, 'consumed': 0},
                               'run_checks': {'limit': 1, 'consumed': 0}}},
        'permission_capabilities': list(expectations['required_capabilities']),
    }))
    reference = ENTRY.validate_evidence_reference(evidence, expectations)
    source_manifest, source_sha = _sources(tmp_path, {'pinned.py': b'pinned'})
    case = {
        'grant': reference,
        'grant_ref': reference['grant_ref'],
        'expectations': expectations,
        'library_id': library.library_id,
        'pins': {'sources_path': str(source_manifest), 'sources_sha256': source_sha},
        'clone': clone,
    }
    return case, runtime


def _parameters(fixture):
    return {'work_id': fixture['authorization'].work_id,
            'action_id': fixture['authorization'].action_id,
            'inputs': {'package': 'controlled'}}


def _handlers(fixture):
    from test_real_source_chain import SCOPE, context
    from test_work_package_dispatch_v2 import request
    from ordessa_engineering.application.contracts.work_context import (
        WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
    from ordessa_engineering.application.api import ApplicationError

    async def work_get(payload, caller):
        authorization = fixture['authorization']
        return {'record_type': 'command_result', 'result': {
            'work_id': authorization.work_id, 'revision': 1,
            'actions': [{'action_id': authorization.action_id,
                         'disposition': 'available', 'execute_permitted': True}]}}

    async def invoke(payload, caller):
        authorization = fixture['authorization']
        with fixture['factory'].begin(SCOPE, 'read') as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND,
                                         WORK_STABLE_ID_PREFIX + authorization.work_id)
            work = decode_work_binding(uow.workflow.read(head))
        answer = await fixture['service']._execute_declared_dispatch(
            request(fixture), context('work-native-implementation'), work=work,
            action_id=authorization.action_id, step_id=authorization.step_id)
        if answer.outcome not in {'completed', 'failed'}:
            native = answer.value or {}
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED',
                                   retry='reconcile',
                                   failure_diagnostic=native.get('failure_diagnostic'),
                                   failure_evidence_ref=native.get('observation_ref'))
        return {'record_type': 'command_result', 'result': {'state': answer.outcome}}

    async def operations_get(payload, caller):
        return {'record_type': 'command_result', 'result': {'state': 'completed'}}

    return {'engineering.work.get': work_get,
            'engineering.work.invoke': invoke,
            'engineering.operations.get': operations_get}


def test_execute_case_runs_one_formal_action_and_writes_the_receipt(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        receipt = tmp_path / '.nightly-cache' / 'result.json'
        report = ENTRY.execute_case(runtime=runtime,
                                    caller=object(), scope=SCOPE,
                                    parameters=_parameters(fixture),
                                    request_id='controlled-case-invoke', case=case,
                                    receipt_path=receipt)
        assert report['stage'] == ENTRY.EXECUTED_STAGE
        assert report['receipt_written'] == str(receipt)
        assert report['result']['result']['state'] in {'completed', 'unknown'}
        assert fixture['transport'].sends == 1
        assert json.loads(receipt.read_bytes())['grant_digest'] == case['grant']['grant_digest']


def test_execute_case_records_the_diagnosis_before_cleanup(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    from ordessa_engineering.application.api import ApplicationError
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        fixture['transport'].fail_send = True
        receipt = tmp_path / '.nightly-cache' / 'failed.json'
        with pytest.raises(ApplicationError) as raised:
            ENTRY.execute_case(runtime=runtime, caller=object(),
                               scope=SCOPE, parameters=_parameters(fixture),
                               request_id='controlled-case-failure', case=case,
                               receipt_path=receipt)
        assert raised.value.code == 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'
        saved = json.loads(receipt.read_bytes())
        assert saved['stage'] == 'UNKNOWN_RECORDED_NO_RESEND'
        assert saved['retry_allowed'] is False
        assert saved['unknown_requires_reconciliation'] is True
        assert saved['error']['code'] == 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'
        assert fixture['transport'].sends == 1


def test_execute_case_keeps_the_original_error_when_the_receipt_cannot_be_written(
        tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    from ordessa_engineering.application.api import ApplicationError
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        fixture['transport'].fail_send = True

        def refuse(_path, _report):
            raise ENTRY.PreparationRefusal(ENTRY.OUTPUT_EXISTS, 'controlled')

        monkeypatch.setattr(ENTRY, 'write_receipt_exclusive', refuse)
        with pytest.raises(ENTRY.PreparationRefusal) as raised:
            ENTRY.execute_case(runtime=runtime, caller=object(),
                               scope=SCOPE, parameters=_parameters(fixture),
                               request_id='controlled-case-receipt-refused', case=case,
                               receipt_path=tmp_path / '.nightly-cache' / 'lost.json')
        assert raised.value.code == ENTRY.EXECUTION_DIAGNOSIS_LOST
        assert type(raised.value.__cause__) is ApplicationError
        assert raised.value.__cause__.code == 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'
        assert 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED' in raised.value.detail
        assert ENTRY.OUTPUT_EXISTS in raised.value.detail


def test_execute_case_refuses_before_any_effect_when_the_work_is_not_runnable(
        tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)

        async def blocked(payload, caller):
            return {'record_type': 'command_result', 'result': {
                'work_id': payload['parameters']['work_id'], 'revision': 1,
                'actions': [{'action_id': 'incremental.implement-package',
                             'disposition': 'blocked', 'execute_permitted': False}]}}

        handlers['engineering.work.get'] = blocked
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.execute_case(runtime=runtime, caller=object(), scope=SCOPE,
                               parameters=_parameters(fixture),
                               request_id='controlled-case-blocked', case=case,
                               receipt_path=tmp_path / '.nightly-cache' / 'blocked.json')
        assert refused.value.code == ENTRY.EXECUTION_REFUSED
        assert fixture['transport'].sends == 0


def test_cli_execute_never_claims_a_real_run(tmp_path, monkeypatch):
    manifest, digest = _sources(tmp_path, {'a.py': b'one\n'})
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.run(['--sources', str(manifest), '--sources-sha256', digest, '--execute'])
    assert refused.value.code == 'WORK_CASE_EVIDENCE_MISSING'


def test_unknown_is_read_back_through_the_query_handler():
    seen = {}

    async def handler(payload, _caller):
        seen['payload'] = payload
        return {'record_type': 'Operation', 'data': {'state': 'unknown'}}

    value = ENTRY.read_unknown_formally(
        _Runtime({'engineering.operations.get': handler}), caller='caller',
        scope={'realm_id': 'realm-a', 'project_id': 'project-a'}, request_id='req-1')
    assert value['data']['state'] == 'unknown'
    assert seen['payload']['parameters'] == {'request_id': 'req-1'}
    assert seen['payload']['scope'] == {'realm_id': 'realm-a', 'project_id': 'project-a'}


def test_continuation_selector_is_the_only_origin_input():
    selector = ENTRY.continuation_selector(operation_ref='op-a', attempt=1,
                                           dispatch_version=2, acp_revision=1)
    assert set(selector) == {'execution_operation_ref', 'attempt',
                             'expected_dispatch_version', 'expected_acp_revision'}
    for values in ({'operation_ref': ''}, {'operation_ref': 1}, {'attempt': 0},
                   {'attempt': True}, {'attempt': 1.0}, {'dispatch_version': -1},
                   {'dispatch_version': 0},
                   {'dispatch_version': True}, {'acp_revision': 0}, {'acp_revision': True}):
        kwargs = dict(operation_ref='op-a', attempt=1, dispatch_version=2, acp_revision=1)
        kwargs.update(values)
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY.continuation_selector(**kwargs)
        assert refused.value.code == 'WORK_CASE_CONTINUATION_SELECTOR_INVALID'


def test_continuation_payload_is_refused_in_a_first_attempt_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / 'cache')
    case = {'grant': {'grant_digest': 'd' * 64}, 'pins': {}, 'clone': {}}
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.execute_case(runtime=object(), caller=object(), scope={'realm_id': 'r'},
                           parameters={'work_id': 'w', 'invocation_version': 2},
                           request_id='req-1', case=case,
                           receipt_path=tmp_path / 'cache' / 'x.json')
    assert refused.value.code == 'WORK_CASE_EXECUTION_BINDING_MISMATCH'


def _evidence(tmp_path, consumed):
    record = {'grant': {'ref': {'realm_id': 'r', 'project_id': 'p', 'approval_id': 'a'},
                        'digest': 'd' * 64, 'work_id': 'work-1',
                        'action_id': 'incremental.implement-package', 'step_id': 'implement',
                        'work_revision': 1, 'package_digest': 'p' * 64,
                        'intent_digest': 'i' * 64,
                        'actions': ['edit_repository', 'run_checks'],
                        'window': {'not_before': '2026-10-17T13:00:00Z',
                                   'expires_at': '2026-10-17T17:00:00Z'}},
              'budget': {'actions': {action: {'limit': 1, 'consumed': consumed}
                                     for action in ('edit_repository', 'run_checks')}},
              'permission_capabilities': ['engineering.work.invoke']}
    path = tmp_path / ('evidence-%d.json' % consumed)
    path.write_text(json.dumps(record))
    return path


EXPECTATIONS = {'work_id': 'work-1', 'action_id': 'incremental.implement-package',
                'step_id': 'implement', 'work_revision': 1,
                'package_digest': 'p' * 64, 'intent_digest': 'i' * 64,
                'actions': ('edit_repository', 'run_checks'),
                'required_capabilities': ('engineering.work.invoke',),
                'now': '2026-10-17T14:00:00Z'}
ORIGIN = {'execution_operation_ref': 'op-a', 'attempt': 1,
          'expected_dispatch_version': 2, 'expected_acp_revision': 1}


def test_evidence_budget_rule_follows_the_mode_not_a_weaker_check(tmp_path):
    entry = ENTRY
    fresh = _evidence(tmp_path, 0)
    used = _evidence(tmp_path, 1)
    # First attempt: the original "unconsumed" rule still refuses a used Grant.
    assert entry.validate_evidence_reference(fresh, EXPECTATIONS, mode='first')['grant_digest']
    with pytest.raises(entry.PreparationRefusal) as refused:
        entry.validate_evidence_reference(used, EXPECTATIONS, mode='first')
    assert refused.value.code == 'WORK_CASE_GRANT_BUDGET_MISMATCH'
    # Continuation: exactly the original root debit is required and accepted.
    assert entry.validate_evidence_reference(used, EXPECTATIONS,
                                             mode='continuation',
                                             origin=ORIGIN)['grant_digest']
    with pytest.raises(entry.PreparationRefusal) as refused:
        entry.validate_evidence_reference(fresh, EXPECTATIONS,
                                          mode='continuation', origin=ORIGIN)
    assert refused.value.code == 'WORK_CASE_CONTINUATION_ROOT_CONSUMPTION_MISMATCH'
    # ... and a continuation without its origin selector is refused.
    with pytest.raises(entry.PreparationRefusal) as refused:
        entry.validate_evidence_reference(used, EXPECTATIONS, mode='continuation')
    assert refused.value.code == 'WORK_CASE_CONTINUATION_SELECTOR_INVALID'


def test_assembly_forwards_the_continuation_switch_to_the_binder():
    import inspect
    source = inspect.getsource(ENTRY.assemble_declared_work_case)
    assert 'continuation=False' in inspect.signature(ENTRY.assemble_declared_work_case).__str__()
    assert 'continuation=continuation' in source


def test_entry_imports_no_product_runtime_at_module_scope():
    source = ENTRY_PATH.read_text()
    module_scope_imports = [line for line in source.splitlines()
                            if line.startswith(('import ', 'from '))]
    assert not any('ordessa' in line for line in module_scope_imports)
    assert 'composition.product_runtime import build_product_runtime' in source


def test_a_changed_diagnosis_projection_keeps_the_original_error(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    from ordessa_engineering.application.api import ApplicationError
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        fixture['transport'].fail_send = True
        monkeypatch.setattr(ENTRY, 'PROBE_SHA256', '0' * 64)
        with pytest.raises(ENTRY.PreparationRefusal) as raised:
            ENTRY.execute_case(runtime=runtime, caller=object(),
                               scope=SCOPE, parameters=_parameters(fixture),
                               request_id='controlled-case-projection', case=case,
                               receipt_path=tmp_path / '.nightly-cache' / 'lost.json')
        assert raised.value.code == ENTRY.EXECUTION_DIAGNOSIS_LOST
        assert type(raised.value.__cause__) is ApplicationError
        assert raised.value.__cause__.code == 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'
        assert 'WORK_CASE_EXECUTION_DIAGNOSIS_LOST' in raised.value.detail


# ------------------------------------------------------- one-graph assembly

SCOPE_DICT = {'realm_id': 'realm-a', 'project_id': 'project-a'}


def _assembly_holder():
    return {
        'factory': object(), 'access': object(), 'controls': object(),
        'blobs': object(), 'materials': object(), 'bindings': object(),
        'reviewer': object(), 'caller': object(),
    }


class _FrozenScope:
    """The case policy object: only ``review_id`` and ``work_scope`` matter."""

    def __init__(self):
        self.review_id = None

        @contextmanager
        def work_scope(context, package_ref, unit_ref, scopes):
            yield

        self.work_scope = work_scope


def test_case_assembly_refuses_without_the_holder_graph_or_the_closure():
    holder = _assembly_holder()
    frozen = _FrozenScope()
    missing = dict(holder)
    missing.pop('reviewer')
    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.assemble_declared_work_case(
            runtime=SimpleNamespace(unit_execution_owner=None), holder=missing,
            scope=dict(SCOPE_DICT), caller=holder['caller'], frozen_scope=frozen,
            expected_selection=('actor', ('role',), 1), prompt_parameters=lambda *a: None,
            review_paths=('path',), deliver=lambda *a: None)
    assert refused.value.code == ENTRY.CASE_HOLDER_UNAVAILABLE

    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.assemble_declared_work_case(
            runtime=SimpleNamespace(unit_execution_owner=None), holder=holder,
            scope=dict(SCOPE_DICT), caller=holder['caller'], frozen_scope=frozen,
            expected_selection=('actor', ('role',), 1), prompt_parameters=lambda *a: None,
            review_paths=('path',), deliver=None)
    assert refused.value.code == ENTRY.CASE_BEFORE_REVIEW_UNAVAILABLE

    with pytest.raises(ENTRY.PreparationRefusal) as refused:
        ENTRY.assemble_declared_work_case(
            runtime=SimpleNamespace(unit_execution_owner=None), holder=holder,
            scope=dict(SCOPE_DICT), caller=holder['caller'], frozen_scope=frozen,
            expected_selection=('actor', ('role',), 1), prompt_parameters=lambda *a: None,
            review_paths=('path',), deliver=lambda *a: None)
    assert refused.value.code == ENTRY.CASE_OWNER_GRAPH_MISMATCH


def test_case_assembly_builds_one_case_ports_over_the_same_graph(monkeypatch):
    holder = _assembly_holder()
    owner = SimpleNamespace(records=object())
    runtime = SimpleNamespace(unit_execution_owner=owner,
                              unit_runtime=SimpleNamespace(context='context'))
    frozen = _FrozenScope()
    selection, snapshots, query = object(), object(), object()
    case_ports = SimpleNamespace(review_runtime=object(), review_plan_factory=object())
    seen = {}

    def build_case_ports(**kwargs):
        seen['build'] = kwargs
        return case_ports

    def apply_ports(ports, **kwargs):
        seen['apply'] = (ports, kwargs)
        return 'applied'

    module = type(sys)('ordessa_server.composition.engineering_declared_work_case_assembly')
    module.build_declared_work_case_ports = build_case_ports
    module.apply_declared_work_case_ports = apply_ports
    monkeypatch.setitem(sys.modules,
                        'ordessa_server.composition.engineering_declared_work_case_assembly',
                        module)

    def fake_bindings(owner_arg, access_arg, *, prompt_parameters=None,
                      query_factory=None, workspace_scope_guard=None):
        seen['bindings'] = (owner_arg, access_arg, prompt_parameters,
                            workspace_scope_guard)
        return selection, snapshots, query

    monkeypatch.setattr('ordessa_engineering.adapters.native_records'
                        '.build_local_dispatch_bindings', fake_bindings)

    def fake_native_bind(service, runtime_arg, **kwargs):
        seen['native'] = dict(service=service, runtime=runtime_arg, **kwargs)
        return 'canonical'

    monkeypatch.setattr('ordessa_server.composition.engineering_native_dispatch_assembly'
                        '.bind_engineering_native_dispatch', fake_native_bind)
    monkeypatch.setattr('ordessa_units.public.unit_services', lambda context: 'services')

    def fake_before_review(**kwargs):
        seen['before_review'] = kwargs
        return 'before-review'

    monkeypatch.setattr(ENTRY, 'build_case_before_review', fake_before_review)

    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    assembly = ENTRY.assemble_declared_work_case(
        runtime=runtime, holder=holder, scope=WireScope(**SCOPE_DICT),
        caller=holder['caller'],
        frozen_scope=frozen, expected_selection=('actor', ('role',), 1),
        prompt_parameters=lambda *a: None, review_paths=('path',),
        deliver=lambda *a: None)

    build = seen['build']
    assert build['factory'] is holder['factory'] and build['access'] is holder['access']
    assert build['method_control'] is holder['controls'] and build['blobs'] is holder['blobs']
    assert build['source_materials'] is holder['materials']
    assert build['source_review_bindings'] is holder['bindings']
    assert build['reviewer_source'] is holder['reviewer']
    assert type(build['wire_scope']) is WireScope
    assert (build['wire_scope'].realm_id, build['wire_scope'].project_id) == (
        'realm-a', 'project-a')
    assert build['expected_selection'] == ('actor', ('role',), 1)
    assert build['before_review'] == 'before-review' and build['owner'] is owner
    assert seen['before_review']['factory'] is holder['factory']
    assert seen['before_review']['frozen_scope'] is frozen
    assert type(seen['before_review']['scope']).__module__.startswith('ordessa_engineering')
    assert seen['bindings'][0] is owner and seen['bindings'][1] is holder['access']
    assert seen['bindings'][3] is frozen.work_scope
    assert assembly.case_ports is case_ports
    assert assembly.binder('service') == 'canonical'
    assert seen['native']['review_prompt_source'] is case_ports.review_runtime
    assert seen['native']['records'] is owner.records
    assert seen['native']['selection'] is selection
    assert seen['native']['services'] == 'services'
    assert seen['native']['source_snapshots'] is snapshots
    assert seen['native']['history_sources'] is snapshots
    assert assembly.applier('ports') == 'applied'
    assert seen['apply'][1]['execution_records'] is owner.records
    assert seen['apply'][1]['execution_query_factory'] is query
    assert seen['apply'][1]['execution_dispatch_binder'] is assembly.binder


def test_correction_only_assembly_forwards_sources_without_binding_business_dispatch(monkeypatch):
    holder = _assembly_holder()
    owner = SimpleNamespace(records=object(), acp_turn_opt_in=True,
                            effect_write_guard_factory=None)
    runtime = SimpleNamespace(unit_execution_owner=owner)
    sources = {'origin_operation_ref': 'original-completed-operation',
               'original_journal': {'path': '/selected/original.jsonl', 'digest': {}},
               'original_check_excerpt': {'path': '/selected/check.jsonl', 'digest': {}}}
    seen = {}
    case_ports = object()
    query = lambda binding: binding

    def build_ports(**kwargs):
        seen['sources'] = kwargs['report_correction_sources']
        return case_ports

    def apply_ports(ports, **kwargs):
        seen['applied'] = kwargs
        return ports

    module = type(sys)('ordessa_server.composition.engineering_declared_work_case_assembly')
    module.build_declared_work_case_ports = build_ports
    module.apply_declared_work_case_ports = apply_ports
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr('ordessa_engineering.adapters.native_records'
                        '.build_historical_dispatch_query_factory', lambda *_: query)
    monkeypatch.setattr('ordessa_engineering.adapters.native_records'
                        '.build_local_dispatch_bindings',
                        lambda *_a, **_kw: pytest.fail('correction-only must not assemble business dispatch'))
    monkeypatch.setattr(ENTRY, 'build_case_before_review', lambda **_: object())
    assembly = ENTRY.assemble_declared_work_case(
        runtime=runtime, holder=holder, scope=SCOPE_DICT, caller=holder['caller'],
        frozen_scope=_FrozenScope(), expected_selection=('actor', ('role',), 1),
        prompt_parameters=None, review_paths=('/selected/file',), deliver=lambda *_: None,
        report_correction_sources=sources, report_correction_only=True)
    assert assembly.binder is None and assembly.selection is None
    assert assembly.applier('original-ports') == 'original-ports'
    assert seen['sources'] is sources
    assert seen['applied']['execution_records'] is owner.records
    assert seen['applied']['execution_query_factory'] is query
    assert seen['applied']['execution_dispatch_binder'] is None


def test_review_successor_assembly_keeps_canonical_binder_and_original_review_ports(monkeypatch):
    holder = _assembly_holder()
    owner = SimpleNamespace(records=object(), acp_turn_opt_in=True,
                            effect_write_guard_factory=object())
    runtime = SimpleNamespace(unit_execution_owner=owner,
                              unit_runtime=SimpleNamespace(context='context'))
    sources = {'origin_operation_ref': 'original-completed-operation',
               'original_journal': {'path': '/selected/original.jsonl', 'digest': {}},
               'original_check_excerpt': {'path': '/selected/check.jsonl', 'digest': {}}}
    seen = {}
    case_ports = SimpleNamespace(review_runtime=object())
    selection, snapshots = object(), object()
    historical_query = object()
    canonical_query = object()

    def build_ports(**kwargs):
        seen['sources'] = kwargs['report_correction_sources']
        return case_ports

    def apply_ports(ports, **kwargs):
        seen['apply'] = kwargs
        return ports

    module = type(sys)('ordessa_server.composition.engineering_declared_work_case_assembly')
    module.build_declared_work_case_ports = build_ports
    module.apply_declared_work_case_ports = apply_ports
    module.build_declared_report_history_query_factory = lambda ports: historical_query
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr('ordessa_engineering.adapters.native_records'
                        '.build_local_dispatch_bindings',
                        lambda *_a, **_kw: (selection, snapshots, canonical_query))
    monkeypatch.setattr('ordessa_engineering.adapters.native_records'
                        '.build_historical_dispatch_query_factory',
                        lambda *_a: historical_query)
    monkeypatch.setattr('ordessa_server.composition.engineering_native_dispatch_assembly'
                        '.bind_engineering_native_dispatch',
                        lambda service, runtime_arg, **kwargs: seen.update(
                            service=service, runtime=runtime_arg, native=kwargs) or 'canonical')
    monkeypatch.setattr('ordessa_units.public.unit_services', lambda context: 'services')
    monkeypatch.setattr(ENTRY, 'build_case_before_review', lambda **_: object())
    assembly = ENTRY.assemble_declared_work_case(
        runtime=runtime, holder=holder, scope=SCOPE_DICT, caller=holder['caller'],
        frozen_scope=_FrozenScope(), expected_selection=('actor', ('role',), 1),
        prompt_parameters=lambda *_: None, review_paths=('/selected/file',),
        deliver=lambda *_: None, report_correction_sources=sources,
        review_successor_only=True)
    assert assembly.binder is not None and assembly.selection is selection
    assert assembly.snapshots is snapshots and assembly.dispatch_query is historical_query
    assert assembly.binder('service') == 'canonical'
    assert seen['sources'] is sources
    assert seen['native']['review_prompt_source'] is case_ports.review_runtime
    assert seen['native']['records'] is owner.records
    assert seen['native']['selection'] is selection
    assert assembly.applier('ports') == 'ports'
    assert seen['apply']['execution_dispatch_binder'] is assembly.binder


def test_report_and_review_successor_assembly_modes_are_mutually_exclusive():
    holder = _assembly_holder()
    with pytest.raises(ENTRY.PreparationRefusal, match=ENTRY.CASE_OWNER_GRAPH_MISMATCH):
        ENTRY.assemble_declared_work_case(
            runtime=SimpleNamespace(unit_execution_owner=SimpleNamespace(records=object())),
            holder=holder, scope=SCOPE_DICT, caller=holder['caller'],
            frozen_scope=_FrozenScope(), expected_selection=('actor', ('role',), 1),
            prompt_parameters=None, review_paths=('/selected/file',), deliver=lambda *_: None,
            report_correction_sources={}, report_correction_only=True,
            review_successor_only=True)


@pytest.mark.parametrize('sources,effect_guard', [(None, None), ({}, object())])
def test_correction_only_never_detaches_an_existing_effect_guard(sources, effect_guard):
    holder = _assembly_holder()
    owner = SimpleNamespace(records=object(), acp_turn_opt_in=True,
                            effect_write_guard_factory=effect_guard)
    with pytest.raises(ENTRY.PreparationRefusal, match=ENTRY.CASE_OWNER_GRAPH_MISMATCH):
        ENTRY.assemble_declared_work_case(
            runtime=SimpleNamespace(unit_execution_owner=owner), holder=holder,
            scope=SCOPE_DICT, caller=holder['caller'], frozen_scope=_FrozenScope(),
            expected_selection=('actor', ('role',), 1), prompt_parameters=None,
            review_paths=('/selected/file',), deliver=lambda *_: None,
            report_correction_sources=sources, report_correction_only=True)


def test_before_review_delivers_then_fixes_the_review_id():
    events = []
    frozen = _FrozenScope()
    holder = {}

    class _Submissions:
        def resolve(self, target):
            events.append(('resolve', target))
            return 'registered-report'

    class _UoW:
        submissions = _Submissions()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class _Factory:
        def begin(self, scope, mode):
            events.append(('begin', scope, mode))
            return _UoW()

    def deliver(plan, report):
        events.append(('deliver', report, frozen.review_id))
        return {'submission_ref': {'approval_id': 'submission-1'}}

    closure = ENTRY.build_case_before_review(
        factory=_Factory(), scope=dict(SCOPE_DICT), frozen_scope=frozen,
        deliver=deliver, holder=holder)
    target = SimpleNamespace(ref='target-ref')
    plan = SimpleNamespace(review_id='review-1',
                           requirement=SimpleNamespace(expected_targets=SimpleNamespace(
                               targets=(target,))))
    closure('context', plan, 'request')

    assert events[1] == ('resolve', 'target-ref')
    # Delivery happens while the review id is still unset; only after it is the
    # id fixed, so the reviewer bootstrap follows a delivered report.
    assert events[2] == ('deliver', 'registered-report', None)
    assert frozen.review_id == 'review-1'
    assert holder['report_delivered'] == {'approval_id': 'submission-1'}

    frozen2 = _FrozenScope()
    refused = ENTRY.build_case_before_review(
        factory=_Factory(), scope=dict(SCOPE_DICT), frozen_scope=frozen2,
        deliver=lambda plan, report: {}, holder={})
    with pytest.raises(ENTRY.PreparationRefusal) as raised:
        refused('context', plan, 'request')
    assert raised.value.code == ENTRY.CASE_REPORT_DELIVERY_REFUSED
    assert frozen2.review_id is None


def test_execute_case_accepts_a_wire_scope_and_sends_its_dict(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)
        seen = {}
        real_get = handlers['engineering.work.get']
        real_invoke = handlers['engineering.work.invoke']

        async def work_get(payload, caller):
            seen['get'] = payload['scope']
            return await real_get(payload, caller)

        async def invoke(payload, caller):
            seen['invoke'] = payload['scope']
            return await real_invoke(payload, caller)

        handlers['engineering.work.get'] = work_get
        handlers['engineering.work.invoke'] = invoke
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
        report = ENTRY.execute_case(
            runtime=runtime, caller=object(),
            scope=WireScope(SCOPE.realm_id, SCOPE.project_id),
            parameters=_parameters(fixture), request_id='controlled-case-scope',
            case=case, receipt_path=tmp_path / '.nightly-cache' / 'scope.json')
        assert report['stage'] == ENTRY.EXECUTED_STAGE
        assert seen['get'] == {'realm_id': SCOPE.realm_id, 'project_id': SCOPE.project_id}
        assert seen['invoke'] == seen['get']
        assert fixture['transport'].sends == 1


def test_clone_leaves_a_rollback_header_the_owner_library_can_open(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    with _real_graph(tmp_path, monkeypatch) as fixture:
        library = fixture['factory'].library
        source = tmp_path / 'wal-source'
        source.mkdir()
        copied = source / 'engineering.sqlite'
        copied.write_bytes(Path(library.path).read_bytes())
        connection = sqlite3.connect(copied)
        assert str(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]).lower() == 'wal'
        connection.execute('VACUUM')
        connection.close()
        assert copied.read_bytes()[18:20] == b'\x02\x02'
        for name in REQUIRED[1:]:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as database:
                database.execute('CREATE TABLE IF NOT EXISTS frozen (value TEXT)')
        manifest = {path.relative_to(source).as_posix(): _sha(path.read_bytes())
                    for path in sorted(source.rglob('*')) if path.is_file()}
        clone = ENTRY.clone_frozen_root(source, tmp_path / 'wal-clone', manifest=manifest)
        destination = Path(clone['clone_library'])
        assert destination.read_bytes()[18:20] == b'\x01\x01'
        assert not list(Path(clone['clone_root']).rglob('*-wal'))
        from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
            EngineeringLibrary)
        opened = EngineeringLibrary.open(destination, library_id=library.library_id)
        try:
            with opened._read_connection() as probe:
                assert probe.execute('SELECT 1').fetchone()[0] == 1
        finally:
            opened.close()


def test_unconfirmed_wire_error_is_read_from_details_not_only_code(tmp_path, monkeypatch):
    class _WireUnknown(Exception):
        details = {'internalCode': 'WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED',
                   'recoveryAction': 'queryOriginalRequest'}

    class _Determined(Exception):
        details = {'internalCode': 'ACCESS_DENIED', 'recoveryAction': 'inspectRequest'}

    assert ENTRY._is_unknown(_WireUnknown()) is True
    assert ENTRY._is_unknown(_Determined()) is False
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    receipt = ENTRY.record_failure_receipt(
        tmp_path / '.nightly-cache' / 'wire.json', request_id='req-1',
        operation='engineering.work.invoke', error=_WireUnknown())
    assert receipt['stage'] == 'UNKNOWN_RECORDED_NO_RESEND'
    assert receipt['unknown_requires_reconciliation'] is True


def test_execute_case_saves_the_invoke_before_a_failing_read_back(tmp_path, monkeypatch):
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    with _real_graph(tmp_path, monkeypatch) as fixture:
        handlers = _handlers(fixture)

        async def failing_read(payload, caller):
            raise OSError('read back failed')

        handlers['engineering.operations.get'] = failing_read
        case, runtime = _case_for(fixture, tmp_path, handlers=handlers)
        receipt = tmp_path / '.nightly-cache' / 'readback.json'
        with pytest.raises(OSError):
            ENTRY.execute_case(runtime=runtime, caller=object(),
                               scope=SCOPE, parameters=_parameters(fixture),
                               request_id='controlled-case-readback', case=case,
                               receipt_path=receipt)
        assert fixture['transport'].sends == 1
        saved = json.loads(receipt.read_bytes())
        assert saved['stage'] == ENTRY.EXECUTED_READBACK_STAGE
        assert saved['result']['record_type'] == 'command_result'
        assert saved['read_back'] is None
        assert saved['read_back_error']['type'] == 'builtins.OSError'


def test_bound_case_accepts_new_runtime_state_written_after_the_build(tmp_path, monkeypatch):
    """A legitimate run writes its own state into the clone.

    The frozen copy is verified before the runtime is built; re-hashing that
    manifest afterwards would refuse every real run. The guard stays on the
    graph identity (the gated library and the product root of this clone).
    """
    _engineering_tests_on_path()
    with _real_graph(tmp_path, monkeypatch) as fixture:
        case, _runtime = _case_for(fixture, tmp_path)
        root = Path(case['clone']['clone_root'])
        (root / 'product' / 'server.lock').write_bytes(b'')
        (root / 'product' / 'state' / 'agentbox.sqlite-wal').write_bytes(b'new frames')
        (root / 'runtime-note.txt').write_bytes(b'new state')
        grant, clone = ENTRY._bound_case(case, _parameters(fixture))
        assert Path(clone['clone_root']) == root
        assert type(clone['graph_binding']) is ENTRY.CloneGraphBinding
        # A clone whose gated library left the root is still refused.
        outside = dict(case['clone'], clone_library=str(tmp_path / 'elsewhere.sqlite'))
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            ENTRY._bound_case(dict(case, clone=outside), _parameters(fixture))
        assert refused.value.code == ENTRY.RUNTIME_GRAPH_MISMATCH


def test_two_temporary_graphs_never_stand_in_for_each_other(tmp_path, monkeypatch):
    """Path equality, a caller boolean and another runtime are all refused."""
    _engineering_tests_on_path()
    from test_real_source_chain import SCOPE
    monkeypatch.setattr(ENTRY, 'NIGHTLY', tmp_path / '.nightly-cache')
    root_a, root_b = tmp_path / 'a', tmp_path / 'b'
    root_a.mkdir()
    root_b.mkdir()
    with _real_graph(root_a, monkeypatch) as graph_a, \
            _real_graph(root_b, monkeypatch) as graph_b:
        case_a, runtime_a = _case_for(graph_a, tmp_path / 'case-a',
                                      handlers=_handlers(graph_a))
        case_b, runtime_b = _case_for(graph_b, tmp_path / 'case-b',
                                      handlers=_handlers(graph_b))
        receipt = tmp_path / '.nightly-cache' / 'two-graphs.json'

        def run(runtime, case):
            return ENTRY.execute_case(runtime=runtime, caller=object(), scope=SCOPE,
                                      parameters=_parameters(graph_a),
                                      request_id='controlled-two-graphs', case=case,
                                      receipt_path=receipt)

        # 1. Another graph's runtime is not this clone's runtime.
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            run(runtime_b, case_a)
        assert refused.value.code == ENTRY.RUNTIME_GRAPH_MISMATCH

        # 2. A caller boolean plus matching paths proves nothing.
        forged = dict(case_a, clone={key: value for key, value in case_a['clone'].items()
                                     if key != 'graph_binding'})
        forged['clone']['runtime_graph_verified'] = True
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            run(runtime_a, forged)
        assert refused.value.code == ENTRY.EXECUTION_BINDING_MISMATCH

        # 3. A hand-made binding with the same paths and ids has no token.
        binding = case_a['clone']['graph_binding']
        hand = ENTRY.CloneGraphBinding(
            runtime=runtime_a, factory=binding.factory, access=binding.access,
            library_path=binding.library_path, library_id=binding.library_id,
            clone_root=binding.clone_root, product_root=binding.product_root)
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            run(runtime_a, dict(case_a, clone=dict(case_a['clone'], graph_binding=hand)))
        assert refused.value.code == ENTRY.RUNTIME_GRAPH_MISMATCH

        # 4. The other graph's Grant is not in this graph's owner records.
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            run(runtime_a, dict(case_a, grant_ref=case_b['grant_ref']))
        assert refused.value.code == ENTRY.OWNER_RECORDS_UNAVAILABLE

        # 5. A copied binding keeps the token but is not the registered object:
        #    aligning the second graph's data_root with the first must not let
        #    the gate read A's budget while B would send.
        runtime_b.data_root = Path(binding.product_root)
        copied = replace(binding, runtime=runtime_b)
        assert copied.token == binding.token
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            run(runtime_b, dict(case_a, clone=dict(case_a['clone'], graph_binding=copied)))
        assert refused.value.code == ENTRY.RUNTIME_GRAPH_MISMATCH

        # 6. The original object is still the registered one and still passes
        #    the pure gate (no execution, no send).
        grant, clone = ENTRY._bound_case(case_a, _parameters(graph_a))
        assert clone['graph_binding'] is binding

        assert graph_a['transport'].sends == 0
        assert graph_b['transport'].sends == 0


@pytest.mark.parametrize('mode', ['continue', '', None])
def test_unknown_execution_modes_are_refused_before_owner_or_effects(tmp_path, mode):
    calls = (
        lambda: ENTRY.read_case_records(factory=None, scope=None, grant_ref=None,
                                       expectations=None, mode=mode),
        lambda: ENTRY.validate_evidence_reference(tmp_path / 'not-read.json', {}, mode=mode),
        lambda: ENTRY.execute_case(runtime=object(), caller=object(), scope=object(),
            parameters={}, request_id='no-effects', case={},
            receipt_path=tmp_path / 'not-written.json', mode=mode),
    )
    for call in calls:
        with pytest.raises(ENTRY.PreparationRefusal) as refused:
            call()
        assert refused.value.code == ENTRY.CONTINUATION_SELECTOR_INVALID
    assert not (tmp_path / 'not-written.json').exists()


# Full report recovery uses original product owners. Only the temporary source
# data and the external ACP/model peer are controlled; no live library is read.
def _report_recovery_peer(native, python, *, fail_first_review=False, reject_first_review=False):
    peer = native._native_cli_peer(python)
    # The external controlled author produces the rejected original report.
    peer = peer.replace("result={'package_digest':", "result={'type':'json_object','package_digest':")
    peer = peer.replace("'type':'tool_call'", "'type':'tool_call_update'")
    peer = peer.replace("'sessionUpdate':'tool_call'", "'sessionUpdate':'tool_call_update'")
    peer = peer.replace("    if decision is not None:\n", "    if status == 'in_progress':\n        params.pop('approval',None)\n    if decision is not None:\n")
    peer = peer.replace("            command=shlex.split(os.environ['ORDESSA_APPROVED_CHECK_COMMAND'])\n"
        "            target=command[command.index('--project-root')+1]\n"
        "            path=target+'/catalog/views.py'\n", """            observation=review['original_check_observation']
            if (observation['contract'] != 'ordessa.original-check-observation/1'
                    or 'not independently authenticated execution proof' not in observation['limitation']
                    or json.loads(observation['excerpt_utf8'])['message']['role'] != 'toolResult'):
                raise RuntimeError('original limited check observation is unavailable')
            path=next(item['path'] for item in observation['files']
                      if item['path'].endswith('/catalog/views.py'))
""")
    before_review = """        correction=next((v for v in bodies if 'report_correction_plan' in v),None)
        if correction is not None:
            path=correction['allowed_read_paths'][0]
            read_update('in_progress')
            decision=callback('fixture-read','session/request_permission',
                {'approval':'file','toolCallId':'fixture-read','files':[path],
                 'toolCall':{'toolCallId':'fixture-read','kind':'read',
                             'locations':[{'path':path}]},'options':options})
            if (decision.get('outcome') or {}).get('optionId') != 'accept':
                raise RuntimeError('report correction read was not allowed once')
            with open(path) as handle:
                handle.read()
            read_update('completed','approved')
            result=json.loads(correction['rejected_report_utf8'])
            result.pop('type')
        elif any('verification_contract' in value for value in bodies):
            content=next(value for value in bodies if 'verification_contract' in value)
            result=content['report']
            required=content['verification_contract']['check_must_include']
            result['verification']=[{'check':'Supplemental report coverage. '+ '; '.join(required),
                                     'result':'not_run'}]
        elif review is not None:
"""
    peer = peer.replace('        if review is not None:\n', before_review)
    journal = """            emit({'jsonrpc':'2.0','method':'session/update','params':{
                'sessionId':session,'type':'tool_call_update','approval':'command',
                'toolCallId':'fixture-check','status':'completed','permissionDecision':'approved',
                'update':{'sessionUpdate':'tool_call_update','toolCallId':'fixture-check',
                          'status':'completed','kind':'execute'}}})
            folder=os.path.join(os.path.dirname(os.getcwd()),'profile','sessions')
            os.makedirs(folder,exist_ok=True)
            call={'type':'message','id':'check-call','parentId':None,'timestamp':'synthetic-source',
                'message':{'role':'assistant','content':[{'type':'toolCall','id':'fixture-check',
                    'name':'bash','arguments':{'command':command}}]}}
            result_message={'type':'message','id':'check-result','parentId':'check-call',
                'timestamp':'synthetic-source','message':{'role':'toolResult',
                    'toolCallId':'fixture-check','toolName':'bash','isError':False,
                    'content':[{'type':'text','text':check.stdout}]}}
            with open(os.path.join(folder,'report-origin.jsonl'),'w') as handle:
                handle.write(json.dumps(call)+'\\n'+json.dumps(result_message)+'\\n')
"""
    marker = "            result={'type':'json_object','package_digest':"
    peer = peer.replace(marker, journal + marker)
    if fail_first_review:
        peer = peer.replace("            result={'verdict':'passed'", """            binding=next(v['ordessa.declared-unit-review'] for v in bodies
                         if 'ordessa.declared-unit-review' in v)
            if '-successor-' not in binding['plan']['review_id']:
                tool='fixture-denied-review-command'
                command=os.environ['ORDESSA_APPROVED_CHECK_COMMAND']
                emit({'jsonrpc':'2.0','method':'session/update','params':{
                    'sessionId':session,'type':'tool_call_update','approval':'command',
                    'toolCallId':tool,'status':'in_progress',
                    'update':{'sessionUpdate':'tool_call_update','toolCallId':tool,'status':'in_progress'}}})
                try:
                    decision=callback(tool,'session/request_permission',{
                        'approval':'command','toolCallId':tool,'command':command,
                        'toolCall':{'toolCallId':tool,'kind':'execute','rawInput':{'command':command}},
                        'options':options})
                except RuntimeError as error:
                    if not str(error).startswith('synthetic callback refused:'):
                        raise
                    # The real bridge turns the original callback refusal
                    # into a failed/cancelled tool observation and continues.
                    decision={'outcome':{'outcome':'cancelled'}}
                if decision.get('outcome',{}).get('outcome') != 'cancelled':
                    raise RuntimeError('read-only review command was not blocked')
                emit({'jsonrpc':'2.0','method':'session/update','params':{
                    'sessionId':session,'type':'tool_call_update','approval':'command',
                    'toolCallId':tool,'status':'failed','permissionDecision':'cancelled',
                    'update':{'sessionUpdate':'tool_call_update','toolCallId':tool,'status':'failed'}}})
            result={'verdict':'passed'""")
    if reject_first_review:
        peer = peer.replace("result={'verdict':'passed'", "result={'verdict':('passed' if review.get('report_content_rework') else 'rejected')")
    compile(peer.split('\n', 1)[1], 'controlled-report-peer', 'exec')
    return peer


def _report_recovery_fixture(tmp_path, monkeypatch, *, fail_first_review=False, reject_first_review=False):
    import sys
    spec = importlib.util.spec_from_file_location('report_recovery_native_fixture',
        REPO / 'tooling/checks/server_product/test_local_library_instruction_case.py')
    _native = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = _native
    spec.loader.exec_module(_native)
    import asyncio
    from contextlib import contextmanager
    from dataclasses import asdict
    from datetime import datetime, timedelta, timezone
    import hashlib
    import json
    import os
    import shutil
    import sqlite3
    import sys
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
    from ordessa_engineering.application.contracts.work_context import WorkBinding, WorkAssociation, work_binding_projection
    from ordessa_engineering.domain.approvals.scope import ActionScope, EnvironmentRef, PathRule, RepositoryScope
    from ordessa_engineering.domain.approvals.implementation import (
        ActionBudgetSlot, WorkPackageAuthorization, WorkPackageAuthorizationIntent)
    from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef, ConversationSource, WorkPackageNotice
    from ordessa_server.composition.engineering_human_source import SOURCE_LIMITATION
    from ordessa_server.composition.engineering_chat_confirmation import INSTRUCTION_BINDING_LIMITATION
    from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
    from ordessa_units.api.manager import UnitManager
    from ordessa_units.api import UnitApiRefused
    from ordessa_execution_agents.harness.transport.environment_channel import EnvironmentProcessChannel
    from ordessa_engineering.application.contracts.dispatch_identity import unit_bootstrap_request_key
    from ordessa_engineering.application.usecases.changes.dispatch_continuation import CONTINUATION_OPERATION
    import ordessa_engineering.application.usecases.support.clock as engineering_clock

    # The ambient no_proxy carries a bracketed IPv6 literal that the JEV HTTP
    # client rejects at construction; this case performs no network call.
    monkeypatch.setenv('no_proxy', 'localhost,127.0.0.1')
    monkeypatch.setenv('NO_PROXY', 'localhost,127.0.0.1')
    module = _native._load()
    repo = tmp_path / 'public-case'
    repo.mkdir(mode=0o700)
    # Public source copies only: this gives the unmodified case its exact
    # policy/material/source-pin files, never a historical runtime or .env.
    for relative in ('methods/incremental-engineering', 'packages/engineering/src'):
        shutil.copytree(REPO / relative, repo / relative)
    for relative in ('tooling/checks/server_product/probe-work-package-generation.py',
                     'tooling/checks/server_product/local_library_check_runtime.py',
                     'apps/server/src/ordessa_server/composition/engineering_chat_confirmation.py'):
        dest = repo / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, dest)
    cache = repo / '.nightly-cache'
    cache.mkdir(mode=0o700)
    target = tmp_path / 'synthetic-catalog'
    before = {}
    for relative in module.BEFORE:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# synthetic catalog baseline\n')
        before[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    bridge = tmp_path / 'synthetic-acp-peer'
    bridge.write_text(_report_recovery_peer(_native, Path(sys.executable),
        fail_first_review=fail_first_review, reject_first_review=reject_first_review))
    bridge.chmod(0o700)
    bridge_digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
    credential = tmp_path / 'synthetic-model.env'
    credential.write_text('DEEPSEEK_API_KEY=synthetic-fixture-no-network\nOPEN_CODE_GO_API_KEY=synthetic-fixture-no-network\n')
    credential.chmod(0o600)
    import ordessa_server.composition.temporary_process_capability as model_input
    # Explicit fixture selection at the external model-input boundary. Keep
    # the real parser and finite allowlist check; no production .env is read.
    monkeypatch.setattr(model_input, 'APPROVED_OPENCODE_SOURCES', frozenset({str(credential)}))
    for key, value in {'ROOT': repo, 'TARGET': target, 'BEFORE': before,
                       'BRIDGE': bridge, 'BRIDGE_SHA': bridge_digest}.items():
        monkeypatch.setattr(module, key, value)
    case_id = 'local-source-chain'
    manifest, manifest_digest, raw, claims, versions = _native._native_cli_materials(repo, case_id)
    monkeypatch.setattr(module, 'MATERIAL_MANIFEST', manifest)
    monkeypatch.setattr(module, 'MATERIAL_MANIFEST_SHA256', manifest_digest)
    seed = tmp_path / 'synthetic-source-graph'
    seed.mkdir(mode=0o700)
    source = _native._native_cli_source_graph(module, seed, manifest, raw, claims, versions, monkeypatch)
    pi_tool = bridge.parent / 'synthetic-pi-tool'
    monkeypatch.setattr(module, 'ORIGINAL', seed)
    monkeypatch.setattr(module, 'FROZEN_PACKAGE_DIGEST', source.package_ref.digest.hex)
    work_id = 'synthetic-cli-report-recovery'
    monkeypatch.setattr(module, 'FIXED_WORK', work_id)
    registration = cache / work_id / 'registered-runtime.json'
    registration.parent.mkdir(mode=0o700)
    monkeypatch.setattr(module, 'REGISTERED_RUNTIME', registration)
    pins = tmp_path / 'public-source-pins.json'
    pins.write_text(json.dumps({str(module.M1): module.sha(module.M1),
                               str(module.M2): module.sha(module.M2)}))
    monkeypatch.setattr(module, 'PREVIOUS_SOURCE_PINS', pins)
    monkeypatch.setattr(module, 'PINNED', {str(module.M1): module.sha(module.M1),
        str(module.M2): module.sha(module.M2), str(bridge): bridge_digest,
        str(repo / 'tooling/checks/server_product/probe-work-package-generation.py'):
            module.sha(repo / 'tooling/checks/server_product/probe-work-package-generation.py')})

    # A fresh, tiny prepared Python runtime is hashed by the real check owner.
    check_root = tmp_path / 'prepared-check'
    (check_root / 'bin').mkdir(parents=True, mode=0o700)
    check_python = check_root / 'bin/python'
    shutil.copy2(Path(sys.executable).resolve(), check_python)
    check_python.chmod(0o700)
    cfg = check_root / 'pyvenv.cfg'
    cfg.write_text('home = ' + str(Path(sys.base_prefix) / 'bin') + '\ninclude-system-site-packages = false\n')
    runner = tmp_path / 'synthetic-catalog-check.py'
    runner.write_text("import argparse,pathlib\np=argparse.ArgumentParser();p.add_argument('--project-root');a=p.parse_args()\nassert pathlib.Path(a.project_root,'catalog/views.py').read_text() == '# synthetic successor edit\\n'\nprint('synthetic fixture check passed')\n")
    producer = module.load_module('synthetic_check_data', repo / 'tooling/checks/server_product/local_library_check_runtime.py')
    pinned = {str(p): module.sha(p) for p in (check_python, cfg, runner, Path('/usr/bin/env').resolve())}
    from contextlib import nullcontext
    command, _, _ = producer.fixed_catalog_check(python_executable=check_python,
        runner=runner, project_root=target, pinned_files=pinned,
        runtime_tree_digest=producer.catalog_runtime_digest(check_root),
        allowed_paths=tuple(str(target / name) for name in before),
        scope_guard=lambda **_: nullcontext())
    config = tmp_path / 'prepared-check.json'
    config.write_text(json.dumps({'python_executable': str(check_python), 'runner': str(runner),
        'pinned_files': pinned, 'runtime_tree_digest': producer.catalog_runtime_digest(check_root),
        'approved_check_command': command}))
    monkeypatch.setattr(module, 'CHECK_CONFIGURATION', config)
    monkeypatch.setattr(module, 'CHECK_CONFIGURATION_SHA256', module.sha(config))

    binding = WorkBinding(work_id, source.scope, source.method, 1,
                          (WorkAssociation('package', source.package_ref),))
    work_digest = Digest('sha256', content_digest(work_binding_projection(binding)).removeprefix('sha256:'))
    from ordessa_execution_agents.profiles import encode_revision_ref
    profile = encode_revision_ref(source.profile_ref)
    environment_ref = EnvironmentRef(source.scope.realm_id, source.profile_ref.profile_id,
        Digest('sha256', profile['contentDigest'].removeprefix('sha256:')))
    intent_id = 'synthetic-cli-native-intent'
    action_scope = ActionScope(source.scope.project_id,
        (RepositoryScope('synthetic-catalog', (PathRule('catalog', 'subtree', ('modify',)),)),),
        (environment_ref,), (), (), intent_id)
    now = datetime.now(timezone.utc)
    stamp = lambda value: value.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    authorization = WorkPackageAuthorization(scope=source.scope, intent_id=intent_id,
        work_id=work_id, work_revision=1, work_digest=work_digest,
        action_id=module.ACTION, step_id=module.STEP, package_ref=source.package_ref,
        method_ref=source.method, actions=('edit_repository', 'run_checks'),
        scope_by_action=(('edit_repository', action_scope), ('run_checks', action_scope)),
        action_budgets=(ActionBudgetSlot('edit_repository', 1), ActionBudgetSlot('run_checks', 1)),
        request_summary=json.dumps({'root': str(target), 'before_sha256': before,
                                   'allowed_operations': list(before)}),
        not_before=stamp(now - timedelta(seconds=1)), expires_at=stamp(now - timedelta(seconds=1) + timedelta(hours=4)))
    policy_raw = (repo / 'methods/incremental-engineering/policies/product-chat-confirmation.v2.yaml').read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 2,
                             Digest('sha256', hashlib.sha256(policy_raw).hexdigest()))
    instruction = 'Synthetic test instruction: edit only the temporary catalog fixture and run its exact prepared check.'
    chat_source = ConversationSource('synthetic-fixture/explicit-instruction', (),
        SOURCE_LIMITATION + '; ' + INSTRUCTION_BINDING_LIMITATION
        + '; message references unavailable; synthetic test data, not a real user reply',
        'local', stamp(now - timedelta(seconds=2)))
    notice = WorkPackageNotice('synthetic-cli-native-notice', authorization, instruction, chat_source, policy)
    intent = WorkPackageAuthorizationIntent(authorization, notice.ref, policy)
    candidate = cache / 'synthetic-candidate.json'
    invoke = {'work_id': work_id, 'action_id': module.ACTION, 'expected_revision': 1,
        'inputs': {'package': asdict(source.package_ref), 'profile': profile,
                   'reviewer_profile': profile, 'method': asdict(source.method)}}
    candidate.write_text(json.dumps({'authorization': asdict(authorization), 'intent': asdict(intent),
        'notice': asdict(notice), 'fixed_profile_ref': profile, 'actual_instruction': instruction,
        'original_business_context': 'Explicit synthetic local integration test; no production repository.',
        'new_question_or_answer_presented': False,
        'start_parameters': {'work_id': work_id, 'revision': 1, 'method_ref': asdict(source.method),
                             'associations': [{'kind': 'package', 'ref': asdict(source.package_ref)}]},
        'invoke_parameters': invoke}))

    original_load = module.load_module
    def load_exact(name, path):
        result = original_load(name, path)
        if str(path).endswith('probe-work-package-generation.py'):
            result.PI = pi_tool
            result.CASE_ID, result.ROOT = case_id, repo
            result.BRIDGE, result.BRIDGE_SHA, result.ENV_SOURCE = bridge, bridge_digest, credential
            result.wait_generation_owner_resume = lambda *_a, **_kw: (_ for _ in ()).throw(
                AssertionError('controlled owner must close without manual intervention'))
        elif Path(path) == module.M2:
            result.NIGHTLY = cache
        return result
    monkeypatch.setattr(module, 'load_module', load_exact)
    return SimpleNamespace(**locals())


def _verify_report_content_rework(f, recovery, graph, answer, sources, manifest_path,
        created, sends, original_budget, rows, monkeypatch, *, pending=False, captured_resume=False,
        native_admitted=None):
    import asyncio
    from contextlib import contextmanager
    from dataclasses import asdict
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_infrastructure.encoding import canonical_bytes
    with sqlite3.connect(graph / 'engineering.sqlite') as db:
        parent_row = db.execute("SELECT * FROM eng_commands WHERE operation='engineering.work.invoke' AND state='completed' ORDER BY rowid DESC LIMIT 1").fetchone()
        columns = [value[1] for value in db.execute('PRAGMA table_info(eng_commands)')]
        parent = dict(zip(columns, parent_row))
        original_submissions = db.execute('SELECT * FROM eng_submissions ORDER BY rowid').fetchall()
        original_reviews = db.execute('SELECT * FROM eng_reviews ORDER BY rowid').fetchall()
    library = EngineeringLibrary.open(graph / 'engineering.sqlite', library_id=f.case_id)
    try:
        blob_store = SQLiteBlobStore(library)
        raw = b'Controlled supplemental observation only; no verification was rerun.'
        supplement = asdict(blob_store.put_verified(raw, Digest('sha256', _sha(raw)), 'text/plain'))
    finally:
        library.close()
    # The original result remains a formal rejection throughout this new
    # consumption. Neither the old operation nor its Grant is reopened.
    old_result = json.loads(parent['result_bytes'])
    old_review = next(step['business']['review_ref'] for step in old_result['steps']
                      if step['operation'] == 'engineering.reviews.record')
    origin = {'parent_operation_id': parent['operation_id'],
        'expected_parent_version': parent['version'], 'review_ref': old_review,
        'submission_ref': answer['report_correction']['submission_ref']}
    class ControlledBudget:
        """No HTTP in the controlled ACP peer; real fee gates tested separately."""
        def configuration(self, role):
            assert role in {'report', 'review'}
            return None

        def require_unit_ready(self, owner, unit, role):
            assert role in {'report', 'review'}
            assert unit.snapshot()['state'] == 'confirmed'
            assert owner.records.owner_read_unit(unit.identity['unitId']) is not None

        def require_current(self):
            from datetime import datetime, timezone
            assert datetime.now(timezone.utc).isoformat() < self.expires_at

    args = dict(registration_path=f.registration, registration_sha256=_sha(f.registration.read_bytes()),
        candidate_path=f.candidate, candidate_sha256=_sha(f.candidate.read_bytes()),
        source_manifest_path=manifest_path, source_manifest_sha256=_sha(manifest_path.read_bytes()),
        sources_config={'source_selection': sources, 'origin': origin, 'supplement_refs': [supplement]},
        run_report=True, budget=ControlledBudget())
    missing = recovery.recover_registered_report_content_rework(**args,
        output=f.cache / 'content-approval-required')
    assert missing['state'] == 'approval_required' and missing['unit_created'] is False
    if captured_resume:
        from datetime import datetime, timedelta, timezone
        current = datetime.now(timezone.utc)
        budget = args['budget']
        budget.plan_digest = missing['plan_ref']['digest']['hex']
        budget.not_before = (current - timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')
        budget.expires_at = (current + timedelta(minutes=90)).isoformat().replace('+00:00', 'Z')
    assert len(created) == len(sends) == 3
    with sqlite3.connect(graph / 'engineering.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.report_content_rework.claim'").fetchone() == (0,)
    guards, guard_operations = [], []
    class ControlledApproval:
        def __init__(self, *, factory, access, blobs, scope):
            self.factory, self.access, self.blobs = factory, access, blobs
            self.scope = scope
            self._proof = None

        @contextmanager
        def guard(self, context, *, plan_ref):
            assert self.access.current_context() is context
            for operation in ('engineering.work.invoke', 'engineering.submissions.record_report',
                              'engineering.reviews.request', 'engineering.reviews.record',
                              'engineering.reviews.assign_reviewer'):
                try:
                    self.access.require(context, operation)
                    break
                except ApplicationError:
                    continue
            else:
                raise AssertionError('approval must use an actual permitted caller context')
            guard_operations.append(operation)
            raw = canonical_bytes({'contract': 'ordessa.report-content-rework-approval/1',
                'plan_ref': asdict(plan_ref), 'principal_id': context.principal_id,
                'decision': 'approved', 'not_before': '2020-01-01T00:00:00Z',
                'expires_at': '2100-01-01T00:00:00Z', 'max_uses': 1})
            if self._proof is None:
                self._proof = self.blobs.put_verified(raw, Digest('sha256', _sha(raw)), 'application/json')
            ref = self._proof
            guards.append('enter')
            try:
                yield ref
            finally:
                guards.append('exit')
    if captured_resume:
        from ordessa_server.composition.report_rework_approval import CapturedReportReworkApproval, CapturedReportReworkConsent
        from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
        from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
        class RealCapturedApproval(CapturedReportReworkApproval):
            def __init__(self, *, factory, access, blobs, scope):
                attestor = RegisteredMainAgentAttestor(access,
                    scope=WireScope(scope.realm_id, scope.project_id),
                    principal_id=access.authority.principal_id, selected_policy_ref=f.intent.policy_ref)
                capture = CapturedReportReworkConsent('isolated-thread', 'isolated-message',
                    '2026-10-18T00:00Z', 'keyi', 'Synthetic report-only fixture consent.',
                    args['budget'].plan_digest)
                super().__init__(factory=factory, access=access, blobs=blobs, scope=scope,
                    attestor=attestor, policy_ref=f.intent.policy_ref, capture=capture, budget=args['budget'])

            @contextmanager
            def guard(self, context, *, plan_ref):
                operation = next(op for op in ('engineering.work.invoke',
                    'engineering.submissions.record_report', 'engineering.reviews.request',
                    'engineering.reviews.record', 'engineering.reviews.assign_reviewer')
                    if _permitted(self.access, context, op))
                guard_operations.append(operation)
                with super().guard(context, plan_ref=plan_ref) as ref:
                    guards.append('enter')
                    try:
                        yield ref
                    finally:
                        guards.append('exit')
        def _permitted(access, context, operation):
            try:
                access.require(context, operation)
                return True
            except ApplicationError:
                return False
        ControlledApproval = RealCapturedApproval
    from ordessa_engineering.adapters.persistence.sqlite.command_journal import SQLiteCommandJournal
    original_complete = SQLiteCommandJournal.complete
    protected_commits = []
    def checked_complete(journal, key, **fields):
        entry = journal.get(key)
        if entry.operation in {'engineering.submissions.record_report', 'engineering.reviews.request',
                'engineering.reviews.record', 'engineering.report_content_rework.claim',
                'engineering.report_content_rework.tail'}:
            assert guards.count('enter') > guards.count('exit')
            if entry.operation == 'engineering.submissions.record_report':
                assert guard_operations[-1] == entry.operation
            protected_commits.append(entry.operation)
        return original_complete(journal, key, **fields)
    monkeypatch.setattr(SQLiteCommandJournal, 'complete', checked_complete)
    if pending:
        from ordessa_engineering.application.orchestration.declared_implementation_results import DeclaredImplementationResults
        original_request = DeclaredImplementationResults.request_review
        async def interrupted(*_args, **_kwargs):
            raise ApplicationError('CONTROLLED_CONTENT_REVIEW_INTERRUPTION')
        monkeypatch.setattr(DeclaredImplementationResults, 'request_review', interrupted)
        with pytest.raises(ApplicationError, match='CONTROLLED_CONTENT_REVIEW_INTERRUPTION'):
            recovery.recover_registered_report_content_rework(**args,
                approval_factory=ControlledApproval, output=f.cache / 'content-interrupted')
        monkeypatch.setattr(DeclaredImplementationResults, 'request_review', original_request)
        replay = recovery.recover_registered_report_content_rework(**args,
            approval_factory=ControlledApproval, output=f.cache / 'content-pending-query')
        assert replay['state'] == 'pending_query_only' and replay['unit_created'] is False
        assert len(created) == len(sends) == 4 and rows() == original_budget
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            assert db.execute('SELECT * FROM eng_commands WHERE operation_id=?', (parent['operation_id'],)).fetchone() == parent_row
            assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.claim'").fetchall() == [('pending',)]
            assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.tail'").fetchall() == [('pending',)]
        return
    if captured_resume:
        from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
        original_admit = EngineeringCommandAccess.admit_work_step
        @contextmanager
        def stop_before_record(self, context, operation, *, request_id):
            if operation == 'engineering.submissions.record_report':
                raise ApplicationError('ISOLATED_STOP_BEFORE_REPORT_REGISTRATION')
            with original_admit(self, context, operation, request_id=request_id) as child:
                yield child
        monkeypatch.setattr(EngineeringCommandAccess, 'admit_work_step', stop_before_record)
        stopped = f.cache / 'content-stopped'
        with pytest.raises(ApplicationError, match='ISOLATED_STOP_BEFORE_REPORT_REGISTRATION'):
            recovery.recover_registered_report_content_rework(**args,
                approval_factory=ControlledApproval, output=stopped)
        monkeypatch.setattr(EngineeringCommandAccess, 'admit_work_step', original_admit)
        assert len(created) == len(sends) == 4
        connection = sqlite3.connect(graph / 'engineering.sqlite')
        try:
            connection.row_factory = sqlite3.Row
            claim = dict(connection.execute("SELECT * FROM eng_commands WHERE operation='engineering.report_content_rework.claim'").fetchone())
            assert claim.pop('result_bytes') is None
        finally:
            connection.close()
        args['budget'].resumed_review_only = True  # Synthetic HTTP peer; real budget recovery tested separately.
        resume_args = {k: v for k, v in args.items() if k != 'run_report'}
        # The existing access binding intentionally lacks conversation-attest
        # on review byte-cut handoffs. Preserve that denial: no parent-only
        # precheck or synthetic port may pretend this real boundary passed.
        with pytest.raises(Exception) as refused:
            recovery.resume_registered_report_content_rework(**resume_args,
                previous_receipt_path=stopped / 'content-rework.json',
                previous_receipt_sha256=_sha((stopped / 'content-rework.json').read_bytes()),
                expected_claim=claim, approval_factory=ControlledApproval, output=f.cache / 'content-resumed')
        assert 'ACCESS_AUTHORITY_UNAVAILABLE' in str(refused.value)
        receipt = json.loads((f.cache / 'content-resumed/content-resume.json').read_bytes())
        assert receipt['report_prompt_sent'] is False and receipt['submitted'] is None
        assert receipt['state'] == 'interrupted_query_only'
        assert native_admitted is not None and len(native_admitted) == 4
        assert len(created) == 5  # A new reviewer exists; its prompt did not reach writer admission.
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.claim'").fetchall() == [('pending',)]
            assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.tail'").fetchall() == [('pending',)]
            assert db.execute('SELECT count(*) FROM eng_submissions').fetchone()[0] == len(original_submissions) + 1
            assert db.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == len(original_reviews)
        assert guards.count('enter') == guards.count('exit')
        assert 'engineering.reviews.assign_reviewer' in guard_operations
        assert rows() == original_budget
        with pytest.raises(recovery.CorrectionRefused):
            recovery.resume_registered_report_content_rework(**resume_args,
                previous_receipt_path=stopped / 'content-rework.json',
                previous_receipt_sha256=_sha((stopped / 'content-rework.json').read_bytes()),
                expected_claim=claim, approval_factory=ControlledApproval, output=f.cache / 'content-resume-repeat')
        assert len(native_admitted) == 4
        return
    else:
        result = recovery.recover_registered_report_content_rework(**args,
            approval_factory=ControlledApproval, output=f.cache / 'content-consumed')
    assert result['state'] == 'completed' and result['submitted'] is True
    assert result['accepted'] is True and result['disposition'] == 'accepted'
    assert len(created) == len(sends) == 5  # original + format + old review + content + new review
    new_ref = result['report_content_rework']['new_submission_ref']
    assert new_ref != origin['submission_ref']
    assert rows() == original_budget
    with sqlite3.connect(graph / 'engineering.sqlite') as db:
        assert db.execute('SELECT * FROM eng_commands WHERE operation_id=?', (parent['operation_id'],)).fetchone() == parent_row
        assert db.execute('SELECT * FROM eng_submissions ORDER BY rowid').fetchall()[:len(original_submissions)] == original_submissions
        assert db.execute('SELECT * FROM eng_reviews ORDER BY rowid').fetchall()[:len(original_reviews)] == original_reviews
        assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.claim'").fetchall() == [('completed',)]
        assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_content_rework.tail'").fetchall() == [('completed',)]
    replay = recovery.recover_registered_report_content_rework(**args,
        approval_factory=ControlledApproval, output=f.cache / 'content-replay')
    assert replay['state'] == 'completed_query' and replay['accepted'] is True
    assert len(created) == len(sends) == 5 and rows() == original_budget
    assert guards.count('enter') == guards.count('exit')
    assert {'engineering.submissions.record_report', 'engineering.reviews.request',
            'engineering.reviews.record', 'engineering.report_content_rework.claim',
            'engineering.report_content_rework.tail'} <= set(protected_commits)
    # The general review API cannot open an additional review around this tail.
    from dataclasses import replace
    from ordessa_engineering.domain.reviews.codec import encode_plan
    from ordessa_infrastructure.encoding import decode_json
    driver = recovery._load_fixed_module('controlled_extra_review_driver',
        f.repo / 'tooling/checks/server_product/probe-work-package-generation.py')
    extra_output = f.cache / 'content-extra-review'
    extra_output.mkdir(mode=0o700)
    runtime = holder = None
    try:
        runtime, holder, _ = ENTRY.open_local_library_registered_graph(graph_root=graph,
            manifest=recovery._safe_graph_manifest(graph, f.module), candidate=json.loads(f.candidate.read_bytes()),
            output=extra_output, driver=driver, case=f.module, source_selection=sources,
            review_successor_only=True, report_content_rework_approval_factory=ControlledApproval)
        with holder['factory'].begin(holder['scope'], 'read') as uow:
            claim = uow.commands.find_operation(holder['scope'],
                'report-content-rework-claim/' + _sha(sources['origin_operation_ref'].encode()),
                operation='engineering.report_content_rework.claim')
            completed = json.loads(claim.result_bytes)
            plan = uow.reviews.get_plan(completed['method_result']['review_ref']['review_id'])
        alternate = replace(plan, review_id='unapproved-content-extra-review')
        with holder['access'].admit(holder['caller'], holder['wire_scope'],
                'engineering.reviews.request', request_id='unapproved-extra-review', trace_id='controlled') as context:
            with pytest.raises(ApplicationError, match='REPORT_CONTENT_REWORK_TAIL_CONFLICT'):
                asyncio.run(holder['service'].execute('engineering.reviews.request',
                    {'plan': decode_json(encode_plan(alternate))}, context))
    finally:
        recovery._stop_runtime(runtime, holder, f.module)
    assert len(created) == len(sends) == 5 and rows() == original_budget
    # Changing supplemental content changes the plan, but cannot add a second
    # claim to the original business operation.
    changed = dict(args, sources_config=dict(args['sources_config'], supplement_refs=[]))
    with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT|REPORT_CONTENT_REWORK_CLAIM_CONFLICT'):
        recovery.recover_registered_report_content_rework(**changed,
            approval_factory=ControlledApproval, output=f.cache / 'content-extra-attempt')
    assert len(created) == len(sends) == 5 and rows() == original_budget


@pytest.mark.parametrize('review_mode', ['ordinary', 'successor', 'pending_successor', 'content_rework', 'content_pending', 'content_expired', 'content_captured_resume'])
def test_registered_report_recovery_uses_native_owners_and_replay_sends_nothing(tmp_path, monkeypatch, review_mode):
    """Real public owners and native ACP; only source data/model peer controlled."""
    from dataclasses import asdict
    import shutil
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.application.contracts.commands import CommandKey
    from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
    from ordessa_execution_agents.harness.transport.environment_channel import EnvironmentProcessChannel
    from ordessa_units.api.manager import UnitManager
    from ordessa_units.api.unit import Unit
    f = _report_recovery_fixture(tmp_path, monkeypatch,
        fail_first_review=review_mode in {'successor', 'pending_successor'},
        reject_first_review=review_mode.startswith('content_'))
    created, sends, closes, native_admitted = [], [], [], []
    original_close = Unit.close
    def close(self, *args, **kwargs):
        closes.append(self.identity['unitId'])
        return original_close(self, *args, **kwargs)
    monkeypatch.setattr(Unit, 'close', close)
    original_create = UnitManager.create
    def create(self, *args, **kwargs):
        unit = original_create(self, *args, **kwargs)
        created.append(f.module.plain(unit.identity))
        return unit
    monkeypatch.setattr(UnitManager, 'create', create)
    original_write = EnvironmentProcessChannel._write_async
    async def write(self, data, lease, **controls):
        try:
            message = json.loads(data)
        except (ValueError, TypeError):
            message = {}
        if message.get('method') == 'session/prompt':
            sends.append(message['id'])
        return await original_write(self, data, lease, **controls)
    monkeypatch.setattr(EnvironmentProcessChannel, '_write_async', write)
    original_admitted_write = EnvironmentProcessChannel._admit_and_write
    async def admitted_write(self, data, *args, **kwargs):
        if json.loads(data).get('method') == 'session/prompt':
            native_admitted.append(json.loads(data)['id'])
        return await original_admitted_write(self, data, *args, **kwargs)
    monkeypatch.setattr(EnvironmentProcessChannel, '_admit_and_write', admitted_write)
    first = f.cache / 'completed-author'
    result = f.module.main(['--candidate', str(f.candidate), '--candidate-sha256', f.module.sha(f.candidate),
                            '--output', str(first), '--run-real'])
    assert result == 1  # A completed author response is deliberately schema-invalid.
    completion = json.loads((first / 'completion.json').read_bytes())
    assert completion['runtime_stopped']
    assert len(created) == len(sends) == 1
    graph = Path(json.loads(f.registration.read_bytes())['graph'])
    library = EngineeringLibrary.open(graph / 'engineering.sqlite', library_id=f.case_id)
    factory = SQLiteUoWFactory(library)
    blobs = SQLiteBlobStore(library)
    def blob(raw, media='application/json'):
        return asdict(blobs.put_verified(raw, Digest('sha256', _sha(raw)), media))
    try:
        with factory.begin(f.source.scope, 'read') as uow:
            parent = uow.commands.get(CommandKey(f.source.scope.realm_id, 'local',
                f.work_id + '-invoke-implementation'))
            row = uow.work_dispatch.get(work_dispatch_key(f.work_id, f.module.ACTION, f.module.STEP),
                                         f.module.STEP, 1, f.source.scope)
        assert parent.state == 'pending'
        assert row['dispatch_phase'] == 'completed' and row['dispatch_version'] == 2
        observation = json.loads(blobs.read_verified(decode_blob_ref(json.loads(row['result_blob_json']))))
        rejected = json.loads(observation['summary']['text'])
        assert rejected['type'] == 'json_object'
        journal_paths = tuple(graph.glob('local-environment/unit-*/profile/sessions/report-origin.jsonl'))
        assert len(journal_paths) == 1
        journal = journal_paths[0]
        journal_raw = journal.read_bytes()
        excerpt_raw = journal_raw.splitlines(keepends=True)[-1]
        excerpt = f.cache / 'selected-original-check.jsonl'
        excerpt.write_bytes(excerpt_raw)
        tool_call = json.loads(journal_raw.splitlines()[0])['message']['content'][0]
        command = tool_call['arguments']['command']
        origin = {'parent_operation_id': parent.operation_id,
                  'execution_operation_ref': row['execution_operation_ref'],
                  'expected_parent_version': parent.version,
                  'expected_dispatch_version': row['dispatch_version'],
                  'expected_observation_revision': observation['revision']}
        sources = {'origin_operation_ref': row['execution_operation_ref'],
            'original_journal': {'path': str(journal), 'digest': {'algorithm': 'sha256', 'hex': _sha(journal_raw)}},
            'original_check_excerpt': {'path': str(excerpt), 'digest': {'algorithm': 'sha256', 'hex': _sha(excerpt_raw)}}}
        evidence = {'files': [{'path': str(f.target / name), 'blob_ref': blob((f.target / name).read_bytes(), 'text/plain')}
                              for name in f.before], 'check': {
            'origin_operation_ref': row['execution_operation_ref'], 'journal_ref': blob(journal_raw),
            'excerpt_ref': blob(excerpt_raw), 'tool_call_id': 'fixture-check',
            'command_digest': {'algorithm': 'sha256', 'hex': _sha(command.encode())},
            'limitation': 'selected original Pi journal observation; not independently authenticated execution proof'}}
    finally:
        library.close()
    registration = json.loads(f.registration.read_bytes())
    registration['state'] = 'native_completed_report_schema_blocked'
    f.registration.write_text(json.dumps(registration))
    spec = importlib.util.spec_from_file_location('native_report_recovery_driver',
        REPO / 'tooling/checks/server_product/local_library_report_correction.py')
    recovery = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recovery
    spec.loader.exec_module(recovery)
    monkeypatch.setattr(recovery, 'ROOT', f.repo)
    monkeypatch.setattr(recovery, 'NIGHTLY', f.cache)
    # The actual imported source bytes and their temporary pinned copies agree.
    for relative in recovery.SOURCE_PIN_PATHS:
        destination = f.repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)
    def load(name, path):
        if Path(path).name == 'local_library_instruction_case.py':
            return f.module
        if Path(path).name == 'run_declared_work_case.py':
            return ENTRY
        return f.module.load_module(name, path)
    monkeypatch.setattr(recovery, '_load_fixed_module', load)
    manifest_path = f.cache / 'report-source-manifest.json'
    manifest_path.write_text(json.dumps({name: _sha((f.repo / name).read_bytes())
                                         for name in recovery.SOURCE_PIN_PATHS}))
    protected = ('eng_approval_grants', 'eng_action_consumptions')
    def rows():
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            return {table: tuple(db.execute('SELECT * FROM ' + table + ' ORDER BY rowid'))
                    for table in protected}
    original_budget = rows()
    arguments = dict(registration_path=f.registration, registration_sha256=_sha(f.registration.read_bytes()),
        candidate_path=f.candidate, candidate_sha256=_sha(f.candidate.read_bytes()),
        sources_config={'source_selection': sources, 'origin': origin, 'evidence': evidence},
        source_manifest_path=manifest_path, source_manifest_sha256=_sha(manifest_path.read_bytes()),
        run_report=True)
    if review_mode in {'ordinary', 'content_rework', 'content_pending', 'content_expired', 'content_captured_resume'}:
        answer = recovery.recover_registered_graph(**arguments, output=f.cache / 'report-recovery')
    else:
        from ordessa_engineering.application.contracts.errors import ApplicationError
        from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import reference_for
        with pytest.raises(ApplicationError, match='REVIEW_READ_ONLY_SCOPE_VIOLATION'):
            recovery.recover_registered_graph(**arguments, output=f.cache / 'report-recovery')
        assert len(created) == len(sends) == 3
        failed_receipt = json.loads((f.cache / 'report-recovery/recovery.json').read_bytes())
        checkpoint_ref = failed_receipt['checkpoint_ref']
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            review_id = db.execute('SELECT review_id FROM eng_review_requests ORDER BY rowid DESC LIMIT 1').fetchone()[0]
            original_request = db.execute('SELECT * FROM eng_review_requests WHERE review_id=?', (review_id,)).fetchone()
            original_assignment = db.execute('SELECT canonical_bytes FROM eng_unit_reviewer_assignments WHERE review_id=?', (review_id,)).fetchone()[0]
            observations = [(bytes(raw), digest) for digest, raw in db.execute(
                'SELECT digest,body FROM eng_method_blobs ORDER BY rowid DESC LIMIT 20')]
        predecessor = None
        for raw, digest in observations:
            try:
                captured = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if (type(captured) is dict and captured.get('contractVersion') == 'unit-acp-turn/1'
                    and captured.get('unitRef', {}).get('unitId') == created[2]['unitId']):
                assert captured['state'] == 'completed' and _sha(raw) == digest
                predecessor = {'review_id': review_id, 'operation_ref': captured['operationRef'],
                    'expected_observation_revision': captured['revision'],
                    'observation_ref': asdict(reference_for(f.case_id, raw, Digest('sha256', digest), 'application/json'))}
                break
        assert predecessor is not None
        successor_arguments = {name: value for name, value in arguments.items() if name != 'run_report'}
        successor_arguments.update(checkpoint_ref=checkpoint_ref, predecessor_review=predecessor,
                                   run_review_successor=True)
        with pytest.raises(ApplicationError, match='SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID'):
            recovery.recover_registered_review_successor(**dict(successor_arguments,
                predecessor_review=dict(predecessor,
                    expected_observation_revision=predecessor['expected_observation_revision'] + 1)),
                output=f.cache / 'review-successor-wrong-revision')
        assert len(created) == len(sends) == 3 and rows() == original_budget
        if review_mode == 'pending_successor':
            from ordessa_engineering.application.orchestration.declared_implementation_results import DeclaredImplementationResults
            original_request_review = DeclaredImplementationResults.request_review
            async def interrupted(*_args, **_kwargs):
                raise ApplicationError('CONTROLLED_SUCCESSOR_INTERRUPTION')
            monkeypatch.setattr(DeclaredImplementationResults, 'request_review', interrupted)
            with pytest.raises(ApplicationError, match='CONTROLLED_SUCCESSOR_INTERRUPTION'):
                recovery.recover_registered_review_successor(**successor_arguments, output=f.cache / 'review-successor-interrupted')
            monkeypatch.setattr(DeclaredImplementationResults, 'request_review', original_request_review)
            with pytest.raises(ApplicationError, match='REPORT_CORRECTION_RECONCILE_REQUIRED'):
                recovery.recover_registered_review_successor(**successor_arguments, output=f.cache / 'review-successor-pending')
            assert len(created) == len(sends) == 3 and rows() == original_budget
            with sqlite3.connect(graph / 'engineering.sqlite') as db:
                assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_correction.review_successor'").fetchall() == [('pending',)]
            return
        answer = recovery.recover_registered_review_successor(**successor_arguments, output=f.cache / 'review-successor')
        assert len(created) == len(sends) == 4
        assert answer['review_recovery']['predecessor'] == predecessor
        assert answer['unit_cleanup'] == {'states': ['confirmed'], 'attempts': [1]}
        replay = recovery.recover_registered_review_successor(**successor_arguments, output=f.cache / 'review-successor-replay')
        assert replay['state'] == 'completed_query' and replay['accepted'] is True
        assert len(created) == len(sends) == 4
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            assert db.execute('SELECT * FROM eng_review_requests WHERE review_id=?', (review_id,)).fetchone() == original_request
            assert db.execute('SELECT canonical_bytes FROM eng_unit_reviewer_assignments WHERE review_id=?', (review_id,)).fetchone()[0] == original_assignment
            assert db.execute("SELECT state FROM eng_commands WHERE operation='engineering.report_correction.review_successor'").fetchall() == [('completed',)]
        assert rows() == original_budget
        return
    assert answer['submitted'] is True
    if review_mode.startswith('content_'):
        assert answer['accepted'] is False and answer['disposition'] == 'rejected'
        if review_mode == 'content_expired':
            # Advance only this final-disposition clock beyond the immutable
            # original Grant. All persisted Grant/consumption bytes remain.
            from datetime import datetime, timedelta
            from ordessa_engineering.application.orchestration import declared_implementation_results
            expires = json.loads(f.candidate.read_bytes())['authorization']['expires_at']
            after_expiry = (datetime.fromisoformat(expires.replace('Z', '+00:00'))
                + timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')
            monkeypatch.setattr(declared_implementation_results, 'clock',
                SimpleNamespace(utc_now=lambda: after_expiry))
        _verify_report_content_rework(f, recovery, graph, answer, sources, manifest_path,
            created, sends, original_budget, rows, monkeypatch,
            pending=review_mode == 'content_pending', captured_resume=review_mode == 'content_captured_resume',
            native_admitted=native_admitted)
        return
    assert answer['accepted'] is True
    assert len(created) == len(sends) == 3  # author, report correction, independent reviewer
    assert len({ref['unitId'] for ref in created}) == 3
    assert closes.count(created[1]['unitId']) == 1
    assert answer['report_unit_cleanup'] == {'states': ['confirmed'], 'attempts': [1]}
    assert rows() == original_budget
    replay = recovery.recover_registered_graph(**arguments, output=f.cache / 'report-replay')
    assert replay['state'] == 'terminal_replay_query_only'
    assert len(created) == len(sends) == 3
    assert closes.count(created[1]['unitId']) == 1
    assert rows() == original_budget
