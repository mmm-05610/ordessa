"""Controlled history bytes + real admitted Environment/ProfileService; no native effects."""
from __future__ import annotations

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite, DomainRevisionConflict
from ordessa_execution_agents.profiles import (
    HistoricalProfileIdentityMismatch, ProfileAccessRefused, ProfileRevisionRef,
    ProfileRevisionConflict,
    ProfileValidationError, encode_content,
)
from ordessa_units.public import unit_services
from pacthold.public import Environment
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_server.bootstrap.migrations.harness_profile_history import (
    HarnessProfileHistoryReader, CapturedHarnessProfile, validated_capture,
)
from ordessa_server.bootstrap.migrations.harness_profile_import import import_harness_profile


class ControlledPolicy:
    def __init__(self):
        self.allow = True
        self.actions = []
        self.callback = None

    def admit_invoke(self, principal, action, guarantee):
        self.actions.append((principal, action, guarantee))
        if self.callback:
            self.callback()
        return self.allow

    def admit_object_access(self, *args):
        return self.allow


@pytest.fixture
def owner(tmp_path):
    store = SqliteStorePort(tmp_path / 'modern.sqlite')
    policy = ControlledPolicy()
    env = Environment('history-import', policy=policy, principal_scope='controlled', store=store,
                      fingerprint_port=ProtectedFingerprintHmac(
                          {'test': b'controlled-history-import-key'}, active_key_id='test'), resource_extension_snapshot=_test_resource_snapshot)
    profiles = unit_services(env).profiles
    yield env, store, policy, profiles
    env.close()
    store.close()


def write_history(tmp_path, *, disabled=False):
    # Independently authored old-format envelope, not written by the legacy runtime.
    value = {'profile_id': 'Original-1', 'harness_type': 'claude-code',
             'provider_id': 'harness-profile', 'name': 'Original', 'schema_version': 1,
             'revision': 3, 'disabled': disabled, 'credential_source_ref': None,
             'capability_refs': [], 'session_overlay_policy': {'mode': 'execution-local'},
             'import_provenance': {'source': 'controlled'}, 'native_payload': {'settings': {'color': 'blue'}}}
    canonical = json.dumps({k: v for k, v in value.items() if k not in {'digest', 'revision'}},
                           sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    value['digest'] = 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()
    root = tmp_path / 'historical'
    target = root / 'claude-code' / 'Original-1' / 'revisions' / '3' / 'envelope.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n')
    return root, target, value


def accepted_content():
    # Deliberate opaque declaration-free preservation: never claims native execution support.
    return {'schemaVersion': '1', 'harnessDefinitionRef': {
        'environmentNamespace': 'history-import', 'definitionId': 'caller-accepted-opaque'},
        'declarations': [], 'metadata': {'purpose': 'explicit audit'}}


def capture(tmp_path, *, disabled=False):
    root, path, value = write_history(tmp_path, disabled=disabled)
    return HarnessProfileHistoryReader(root).capture('claude-code', 'Original-1', 3,
                                                     expected_digest=value['digest']), path, value


def create(profiles, source, request='create', *, content=None):
    return import_harness_profile(profiles=profiles, captured=source,
        profile_id='imported', name='Imported', content=accepted_content() if content is None else content,
        request=profiles.request_key(request))


def test_reader_constructs_and_imports_without_source_writes_or_default_discovery(tmp_path):
    missing = tmp_path / 'absent'
    reader = HarnessProfileHistoryReader(missing)
    assert not missing.exists()
    assert reader.list() == ()
    assert not missing.exists()
    for retired in ('put', 'save', 'create', 'resolve', 'ref'):
        assert not hasattr(reader, retired)
    with pytest.raises(KeyError, match='PROFILE_NOT_FOUND'):
        reader.get('claude-code', 'Original-1', 3)


def test_original_identity_digest_and_bytes_capture_are_verified(tmp_path):
    source, path, value = capture(tmp_path)
    original = path.read_bytes()
    reader = HarnessProfileHistoryReader(path.parents[4])
    assert reader.get('claude-code', 'Original-1', 3) == value
    assert reader.list('claude-code') == (value,)
    assert validated_capture(source) == value
    assert source.raw_bytes == original
    assert source.digest == value['digest']
    assert path.read_bytes() == original
    for forged in (replace(source, harness_type='hermes'), replace(source, profile_id='foreign'),
                   replace(source, revision=4)):
        with pytest.raises(ValueError, match='PROFILE_IDENTITY_MISMATCH'):
            validated_capture(forged)
    with pytest.raises(ValueError, match='PROFILE_DIGEST_DRIFT'):
        validated_capture(replace(source, digest='sha256:' + '0' * 64))
    drifted = json.loads(source.raw_bytes)
    drifted['native_payload']['settings']['color'] = 'red'
    with pytest.raises(ValueError, match='PROFILE_DIGEST_DRIFT'):
        validated_capture(replace(source, raw_bytes=json.dumps(drifted).encode()))
    path.write_text(json.dumps(drifted))
    with pytest.raises(ValueError, match='PROFILE_DIGEST_DRIFT'):
        reader.get('claude-code', 'Original-1', 3)


def test_symlink_disabled_and_path_escape_fail_closed(tmp_path, owner):
    source, path, value = capture(tmp_path, disabled=True)
    assert validated_capture(source)['disabled'] is True  # history may be audited, never enabled by import
    with pytest.raises(ValueError, match='PROFILE_DISABLED'):
        create(owner[3], source)
    assert owner[1].list_domain('history-import', 'agents.profile-catalog') == ()
    external = tmp_path / 'external.json'
    external.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(external)
    reader = HarnessProfileHistoryReader(path.parents[4])
    with pytest.raises(ValueError, match='PROFILE_SYMLINK_FORBIDDEN'):
        reader.get('claude-code', 'Original-1', 3)
    with pytest.raises(ValueError, match='PROFILE_SYMLINK_FORBIDDEN'):
        reader.capture('claude-code', 'Original-1', 3, expected_digest=value['digest'])
    with pytest.raises(ValueError, match='INVALID_PROFILE_ID'):
        reader.get('../escape', 'Original-1', 3)


def test_import_uses_only_captured_bytes_and_real_original_store(tmp_path, owner, monkeypatch):
    source, path, value = capture(tmp_path)
    env, store, _, profiles = owner
    before = path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('import attempted source filesystem IO')
    with monkeypatch.context() as patch:
        for operation in ('read_bytes', 'read_text', 'open', 'mkdir'):
            patch.setattr(Path, operation, forbidden)
        result = create(profiles, source)
    content = encode_content(profiles.get_revision(result.current_revision).content)
    assert content['declarations'] == []
    assert content['harnessDefinitionRef'] == accepted_content()['harnessDefinitionRef']
    assert content['metadata']['historicalHarnessProfile'] == value
    assert result.profile_id == 'imported'
    assert result.current_revision.digest != source.digest  # distinct algorithms, never aliases
    assert env._store is store
    assert path.read_bytes() == before
    assert store.read_domain(env.environment_id, 'agents.profile-manifests', 'imported@1') is not None


def test_replay_dual_cas_and_current_name_do_not_replace_history(tmp_path, owner):
    source, _, _ = capture(tmp_path)
    env, store, _, profiles = owner
    first = create(profiles, source)
    renamed = profiles.rename('imported', name='New name', expected_version=1,
                              request=profiles.request_key('rename'))
    assert create(profiles, source) == first
    with pytest.raises(ProfileRevisionConflict):
        import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name=None,
            content=accepted_content(), request=profiles.request_key('stale'),
            expected_version=1, base_revision=first.current_revision)
    second = import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name=None,
        content={**accepted_content(), 'metadata': {'purpose': 'second'}}, request=profiles.request_key('revise'),
        expected_version=renamed.version, base_revision=first.current_revision)
    profiles.rename('imported', name='Later name', expected_version=second.version,
                    request=profiles.request_key('later'))
    replay = import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name=None,
        content={**accepted_content(), 'metadata': {'purpose': 'second'}}, request=profiles.request_key('revise'),
        expected_version=renamed.version, base_revision=first.current_revision)
    assert replay == second
    assert profiles.get_revision(first.current_revision).ref == first.current_revision
    with pytest.raises(ProfileRevisionConflict):
        create(profiles, source, content={**accepted_content(), 'metadata': {'purpose': 'changed'}})


def test_foreign_principal_environment_ref_and_policy_refuse_without_writes(tmp_path, owner):
    source, _, _ = capture(tmp_path)
    env, store, policy, profiles = owner
    with pytest.raises(ProfileAccessRefused):
        import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name='Imported',
            content=accepted_content(), request=RequestKey(env.environment_id, 'foreign', 'foreign-principal'))
    with pytest.raises(HistoricalProfileIdentityMismatch) as mismatch:
        import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name='Imported',
            content=accepted_content(), request=RequestKey('foreign', 'controlled', 'foreign-environment'))
    assert mismatch.value.code == 'IDENTITY_MISMATCH'
    with pytest.raises(HistoricalProfileIdentityMismatch, match='fixed base Profile identity differs'):
        import_harness_profile(profiles=profiles, captured=source, profile_id='imported', name=None,
            content=accepted_content(), request=profiles.request_key('foreign-ref'), expected_version=1,
            base_revision=ProfileRevisionRef('foreign', 'imported', 1, 'sha256:' + '0' * 64))
    policy.allow = False
    with pytest.raises(ProfileAccessRefused):
        create(profiles, source)
    assert store.list_domain(env.environment_id, 'agents.profile-catalog') == ()
    assert store.list_domain(env.environment_id, 'agents.profile-manifests') == ()


def test_real_sql_transaction_rolls_back_catalog_revision_and_request_receipt(tmp_path):
    class ConflictingStore(SqliteStorePort):
        def commit_domain_change(self, request, digest, writes, result):
            self.last_request, self.last_digest = request, digest
            return super().commit_domain_change(request, digest, (*writes,
                DomainWrite('agents.profile-catalog', 'absent-conflict', 7, {'blocked': True})), result)
    source, _, _ = capture(tmp_path)
    store = ConflictingStore(tmp_path / 'rollback.sqlite')
    env = Environment('history-import', policy=ControlledPolicy(), principal_scope='controlled', store=store,
        fingerprint_port=ProtectedFingerprintHmac({'test': b'controlled-rollback'}, active_key_id='test'), resource_extension_snapshot=_test_resource_snapshot)
    try:
        with pytest.raises(DomainRevisionConflict):
            create(unit_services(env).profiles, source)
        assert store.list_domain(env.environment_id, 'agents.profile-catalog') == ()
        assert store.list_domain(env.environment_id, 'agents.profile-manifests') == ()
        assert store.read_domain_result(store.last_request, store.last_digest) is None
    finally:
        env.close()
        store.close()


def test_provenance_cannot_be_replaced_and_is_frozen_before_admission_callback(tmp_path, owner):
    source, _, value = capture(tmp_path)
    _, _, policy, profiles = owner
    with pytest.raises(ValueError, match='historical provenance must not be supplied'):
        create(profiles, source, content={**accepted_content(), 'metadata': {'historicalHarnessProfile': {}}})
    body = accepted_content()
    policy.callback = lambda: body['metadata'].update({'purpose': 'callback mutation'})
    result = create(profiles, source, content=body)
    policy.callback = None
    stored = encode_content(profiles.get_revision(result.current_revision).content)
    assert stored['metadata']['purpose'] == 'explicit audit'
    assert stored['metadata']['historicalHarnessProfile'] == value


def test_mutated_carrier_and_unbounded_or_secret_metadata_are_not_trusted(tmp_path, owner):
    source, _, value = capture(tmp_path)
    _, store, policy, profiles = owner
    object.__setattr__(source, 'digest', 'sha256:' + '0' * 64)
    with pytest.raises(ValueError, match='PROFILE_DIGEST_DRIFT'):
        create(profiles, source)
    assert policy.actions == []
    assert store.list_domain('history-import', 'agents.profile-catalog') == ()
    source, _, _ = capture(tmp_path / 'second')
    for body in ({**accepted_content(), 'metadata': {'apiKey': 'plaintext'}},
                 {**accepted_content(), 'metadata': {'too_large': 'x' * 262144}}):
        with pytest.raises(ProfileValidationError):
            create(profiles, source, content=body)
    assert policy.actions == []
    assert store.list_domain('history-import', 'agents.profile-manifests') == ()


def test_history_modules_import_without_creating_files_or_services(tmp_path):
    import os
    import subprocess
    import sys

    script = """
from pathlib import Path
import sqlite3

def forbidden(*args, **kwargs):
    raise AssertionError('module import attempted data IO')
for name in ('mkdir', 'read_text', 'read_bytes', 'open'):
    setattr(Path, name, forbidden)
sqlite3.connect = forbidden
import ordessa_server.bootstrap.migrations.harness_profile_history as reader
import ordessa_server.bootstrap.migrations.harness_profile_import as importer
assert reader.PROVIDER_ID == 'harness-profile'
assert reader.CONTRACT_ID == 'agent-box.profile@1'
"""
    environment = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'WINDIR'}}
    environment.update(HOME=str(tmp_path), TMPDIR=str(tmp_path),
                       PYTHONPATH=os.pathsep.join(str(p) for p in sys.path if p),
                       E2E_REAL_CODEX='0', E2E_REAL_PI='0')
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


def test_caller_declarations_are_captured_without_invented_provider_support(tmp_path, owner):
    source, _, _ = capture(tmp_path)
    body = accepted_content()
    body['declarations'] = [{'declarationId': 'caller-choice', 'configurationKind': 'opaque.caller',
        'schemaVersion': 'caller/1', 'action': 'value', 'requirement': 'optional', 'payload': {'choice': 'captured'}}]
    created = create(owner[3], source, content=body)
    stored = encode_content(owner[3].get_revision(created.current_revision).content)
    assert stored['declarations'] == body['declarations']
    assert stored['harnessDefinitionRef'] == body['harnessDefinitionRef']
    # This is storage only; neither a Unit nor an execution request was created.
    assert owner[2].actions == [('controlled', 'pacthold.agents.profiles.create', 'reliable')]


def test_history_reader_rejects_symlink_revision_ancestors_before_read(tmp_path):
    root, path, value = write_history(tmp_path)
    external = tmp_path / 'outside-revisions'
    path.parent.parent.rename(external)
    (root / 'claude-code' / 'Original-1' / 'revisions').symlink_to(external, target_is_directory=True)
    reader = HarnessProfileHistoryReader(root)
    with pytest.raises(ValueError, match='PROFILE_SYMLINK_FORBIDDEN'):
        reader.get('claude-code', 'Original-1', 3)
    with pytest.raises(ValueError, match='PROFILE_SYMLINK_FORBIDDEN'):
        reader.capture('claude-code', 'Original-1', 3, expected_digest=value['digest'])
    assert (external / '3' / 'envelope.json').is_file()


def test_list_and_latest_reject_revisions_symlink_before_enumeration(tmp_path, monkeypatch):
    from pathlib import Path
    from ordessa_server.bootstrap.migrations.harness_profile_history import HarnessProfileHistoryReader
    import pytest
    root = tmp_path / "history"
    directory = root / "claude-code" / "demo"
    directory.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (directory / "revisions").symlink_to(external, target_is_directory=True)
    original = Path.iterdir
    visited = []
    def guarded(path):
        visited.append(path)
        if path == directory / "revisions" or path == external:
            raise AssertionError("external revision directory enumerated")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", guarded)
    reader = HarnessProfileHistoryReader(root)
    with pytest.raises(ValueError, match="PROFILE_SYMLINK_FORBIDDEN"):
        reader.list("claude-code")
    with pytest.raises(ValueError, match="PROFILE_SYMLINK_FORBIDDEN"):
        reader.get("claude-code", "demo")
    assert directory / "revisions" not in visited
    assert external not in visited


def test_list_invalid_harness_id_refuses_before_directory_observation(tmp_path, monkeypatch):
    reader = HarnessProfileHistoryReader(tmp_path / 'history')
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid ID caused directory observation')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'iterdir', forbidden)
        patch.setattr(Path, 'is_dir', forbidden)
        for invalid in ('../outside', '../../outside', '/outside', ''):
            with pytest.raises(ValueError, match='INVALID_PROFILE_ID'):
                reader.list(invalid)


# Historical projection is a read-only view of the same admitted modern revision.
from ordessa_execution_agents.profiles import ProfileNotFound
from ordessa_server.bootstrap.migrations.harness_profile_projection import (
    HistoricalHarnessRef, read_imported_historical_revision,
    select_current_imported_historical, read_captured_historical,
    resolve_captured_historical,
)


def test_imported_exact_history_view_uses_modern_immutable_revision_and_acl(tmp_path, owner):
    source, _, old = capture(tmp_path)
    env, store, policy, profiles = owner
    created = create(profiles, source)
    expected = HistoricalHarnessRef('claude-code', 'Original-1', 3, old['digest'])
    view = read_imported_historical_revision(
        profiles=profiles, modern_ref=created.current_revision, expected=expected)
    assert view.modern_ref == created.current_revision
    assert view.envelope() == old
    assert view.historical_ref.digest != view.modern_ref.digest
    view.envelope()['name'] = 'mutated copy'
    assert read_imported_historical_revision(
        profiles=profiles, modern_ref=created.current_revision, expected=expected).envelope() == old
    assert select_current_imported_historical(
        profiles=profiles, profile_id='imported', expected=expected).modern_ref == created.current_revision
    with pytest.raises(ValueError, match='PROFILE_DIGEST_DRIFT'):
        read_imported_historical_revision(profiles=profiles, modern_ref=created.current_revision,
            expected=HistoricalHarnessRef('claude-code', 'Original-1', 3, 'sha256:' + '0'*64))
    policy.allow = False
    with pytest.raises(ProfileAccessRefused):
        read_imported_historical_revision(profiles=profiles, modern_ref=created.current_revision,
                                          expected=expected)


def test_archived_current_selection_refuses_but_exact_history_audit_survives(tmp_path, owner):
    source, _, old = capture(tmp_path)
    _, store, _, profiles = owner
    created = create(profiles, source)
    expected = HistoricalHarnessRef('claude-code', 'Original-1', 3, old['digest'])
    profiles.archive('imported', expected_version=created.version,
                     request=profiles.request_key('archive-imported'))
    with pytest.raises(ProfileAccessRefused, match='archived'):
        select_current_imported_historical(profiles=profiles, profile_id='imported',
                                           expected=expected)
    assert read_imported_historical_revision(profiles=profiles,
        modern_ref=created.current_revision, expected=expected).envelope() == old
    assert store.read_domain(profiles.environment_namespace, 'agents.profile-manifests',
                             'imported@1') is not None


def test_disabled_historical_exact_ref_refuses_without_import_or_fallback(tmp_path, owner):
    source, path, old = capture(tmp_path, disabled=True)
    _, store, _, profiles = owner
    expected = HistoricalHarnessRef('claude-code', 'Original-1', 3, old['digest'])
    assert read_captured_historical(captured=source, expected=expected).envelope() == old
    with pytest.raises(ValueError, match='PROFILE_DISABLED'):
        resolve_captured_historical(captured=source, expected=expected)
    with pytest.raises(ValueError, match='PROFILE_DISABLED'):
        create(profiles, source)
    assert store.list_domain(profiles.environment_namespace, 'agents.profile-catalog') == ()
    with pytest.raises(ProfileNotFound):
        select_current_imported_historical(profiles=profiles, profile_id='Original-1',
                                           expected=expected)
    assert path.exists()  # source is explicit history only, never a fallback


def test_current_historical_projection_refuses_disabled_metadata_even_when_syntactically_valid(tmp_path, owner):
    source, _, old = capture(tmp_path, disabled=True)
    _, store, _, profiles = owner
    content = accepted_content()
    content['metadata'] = {'historicalHarnessProfile': old}
    created = profiles.create(profile_id='manual-disabled', name='Manual disabled', content=content,
                              request=profiles.request_key('manual-disabled'))
    expected = HistoricalHarnessRef('claude-code', 'Original-1', 3, old['digest'])
    assert read_imported_historical_revision(profiles=profiles,
        modern_ref=created.current_revision, expected=expected).envelope()['disabled'] is True
    with pytest.raises(ValueError, match='PROFILE_DISABLED'):
        select_current_imported_historical(profiles=profiles, profile_id='manual-disabled',
                                           expected=expected)
    assert store.read_domain(profiles.environment_namespace, 'agents.profile-catalog',
                             'manual-disabled') is not None
