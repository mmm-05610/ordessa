"""Schema11 repository baseline UoW/storage acceptance with explicitly synthetic access."""
import hashlib

import pytest

from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.usecases.packages.implementation import ImplementationUseCases
from ordessa_engineering.domain.changes.repository_baseline import RepositoryFile, seal_repository_baseline
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest


SCOPE = Scope('realm-implementation-storage', 'project-implementation-storage')
OTHER_SCOPE = Scope('realm-other', 'project-other')
ACTOR = ActorRef('synthetic-human', 'human', 'test-only-access')
RECEIVED_AT = '2026-10-10T12:30:00.000000Z'


class ExplicitSyntheticAccess:
    """Fixture grants test calls only; it is not a production trusted-human authority."""
    def require(self, context, operation):
        assert type(context) is CommandContext
        assert operation.startswith('engineering.')


def _context(request_id, scope=SCOPE):
    return CommandContext(scope, 'principal-fixture', ACTOR, request_id, RECEIVED_AT,
                          'trace-implementation-storage')


def _new_library(path, library_id='implementation-storage', schema_version=11):
    return EngineeringLibrary.create(path.resolve(), library_id=library_id,
                                     schema_version=schema_version)


def _baseline(blobs, *, scope=SCOPE, content=b'baseline bytes', vcs='none', commit_id=None,
              overlay=None, repository_id='repo-main'):
    ref = blobs.put_verified(content, Digest('sha256', hashlib.sha256(content).hexdigest()),
                             'application/octet-stream')
    return seal_repository_baseline(scope, repository_id, vcs, commit_id,
                                    (RepositoryFile('src/main.py', ref),), overlay)


@pytest.fixture
def library_and_factory(tmp_path):
    library = _new_library((tmp_path.resolve() / 'implementation.sqlite').resolve())
    try:
        yield library, SQLiteUoWFactory(library)
    finally:
        if not library._closed:
            library.close()


def test_baseline_freeze_read_retry_and_changed_request_use_original_authorities(
        library_and_factory):
    library, factory = library_and_factory
    blob_store = SQLiteBlobStore(library)
    baseline = _baseline(blob_store)
    usecases = ImplementationUseCases(factory, ExplicitSyntheticAccess())
    context = _context('baseline-freeze-1')

    first = usecases.freeze_baseline(baseline, context)
    assert first.status == 'completed'
    assert first.result['baseline_ref']['tree_digest']['hex'] == baseline.ref.tree_digest.hex
    assert usecases.freeze_baseline(baseline, context) == first
    with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT'):
        usecases.freeze_baseline(_baseline(blob_store, content=b'changed bytes'), context)

    restored = usecases.read_baseline(baseline.ref, _context('baseline-read'))
    assert restored == baseline
    with factory.begin(SCOPE, 'read') as uow:
        assert uow.authority_id == blob_store.authority_id
        assert uow.implementation.resolve_repository_baseline(baseline.ref) == baseline
        assert uow.implementation.read_blob(baseline.files[0].blob_ref) == b'baseline bytes'
        uow.commit()


def test_invalid_blob_scope_git_and_missing_access_fail_closed(library_and_factory, tmp_path):
    library, factory = library_and_factory
    usecases = ImplementationUseCases(factory, ExplicitSyntheticAccess())
    context = _context('bad-baseline')

    from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import object_id
    missing_hash = hashlib.sha256(b'missing').hexdigest()
    missing_ref = BlobRef(Digest('sha256', missing_hash), len(b'missing'),
                          'application/octet-stream', object_id(library.library_id, missing_hash))
    missing = seal_repository_baseline(SCOPE, 'repo-main', 'none', None,
                                       (RepositoryFile('src/main.py', missing_ref),))
    with pytest.raises(ApplicationError, match='IMPLEMENTATION_BLOB_NOT_FOUND'):
        usecases.freeze_baseline(missing, context)

    foreign = _new_library((tmp_path.resolve() / 'foreign.sqlite').resolve(),
                           library_id='foreign-authority')
    try:
        foreign_ref = SQLiteBlobStore(foreign).put_verified(
            b'foreign bytes', Digest('sha256', hashlib.sha256(b'foreign bytes').hexdigest()),
            'application/octet-stream')
        foreign_baseline = seal_repository_baseline(SCOPE, 'repo-main', 'none', None,
            (RepositoryFile('src/main.py', foreign_ref),))
        with pytest.raises(ApplicationError, match='IMPLEMENTATION_BLOB_REF_INVALID'):
            usecases.freeze_baseline(foreign_baseline, _context('foreign-blob'))
    finally:
        foreign.close()

    foreign_scope = _baseline(SQLiteBlobStore(library), scope=OTHER_SCOPE)
    with pytest.raises(ApplicationError, match='SCOPE_MISMATCH'):
        usecases.freeze_baseline(foreign_scope, _context('foreign-scope'))

    git = _baseline(SQLiteBlobStore(library), content=b'git snapshot', vcs='git', commit_id='a' * 40)
    with pytest.raises(ApplicationError, match='REPOSITORY_CHECKOUT_SOURCE_UNAVAILABLE'):
        usecases.freeze_baseline(git, _context('unattested-git'))
    with pytest.raises(ApplicationError, match='REPOSITORY_CHECKOUT_SOURCE_UNAVAILABLE'):
        with factory.begin(SCOPE) as uow:
            uow.implementation.create_repository_baseline(git)

    with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
        ImplementationUseCases(factory, None).freeze_baseline(
            _baseline(SQLiteBlobStore(library), content=b'no default access'),
            _context('no-access'))


def test_schema10_open_does_not_migrate_and_implementation_port_refuses(library_and_factory, tmp_path):
    library, _ = library_and_factory
    path = (tmp_path.resolve() / 'legacy-schema10.sqlite').resolve()
    legacy = _new_library(path, library_id='schema10', schema_version=10)
    try:
        reopened = EngineeringLibrary.open(path, library_id='schema10')
        try:
            assert reopened._schema_version == 10
            with pytest.raises(ApplicationError, match='IMPLEMENTATION_SCHEMA_REQUIRED'):
                with SQLiteUoWFactory(reopened).begin(SCOPE, 'read') as uow:
                    _ = uow.implementation
        finally:
            reopened.close()
    finally:
        legacy.close()


def test_explicit_schema10_migration_preserves_material_and_receipt(tmp_path):
    path = (tmp_path.resolve() / 'schema10.sqlite').resolve()
    backup_path = (tmp_path.resolve() / 'schema10-backup.sqlite').resolve()
    library = _new_library(path, library_id='schema10-migration', schema_version=10)
    try:
        artifact = ArtifactUseCases(SQLiteUoWFactory(library), ExplicitSyntheticAccess())
        created = artifact.create(
            {'kind': 'plan', 'initial': {'media_type': 'application/json',
             'schema_id': 'urn:test:preserved-material', 'inline_value': {'body': 'preserve'} }},
            _context('before-migration'))
        assert created.status == 'completed'
        before = tuple(library._connection.execute(
            'SELECT realm_id,project_id,revision_id,artifact_id,digest,schema_version,canonical_bytes '
            'FROM eng_artifact_revisions ORDER BY realm_id,project_id,revision_id'))
        receipt = migrations.migrate_schema10(library, backup_path=backup_path)
        assert receipt.applied and receipt.target_version == 11
        after = tuple(library._connection.execute(
            'SELECT realm_id,project_id,revision_id,artifact_id,digest,schema_version,canonical_bytes '
            'FROM eng_artifact_revisions ORDER BY realm_id,project_id,revision_id'))
        assert after == before
        replay = migrations.migrate_schema10(library, backup_path=backup_path)
        assert not replay.applied and replay.target_version == 11

        reopened = EngineeringLibrary.open(path, library_id='schema10-migration')
        try:
            assert reopened._schema_version == 11
            with SQLiteUoWFactory(reopened).begin(SCOPE, 'read') as uow:
                assert uow.implementation
                uow.commit()
        finally:
            reopened.close()

        backup = EngineeringLibrary.open(backup_path, library_id='schema10-migration')
        try:
            assert backup._schema_version == 10
            assert tuple(backup._connection.execute(
                'SELECT revision_id,digest,schema_version,canonical_bytes '
                'FROM eng_artifact_revisions ORDER BY revision_id')) == tuple(
                (r[2], r[4], r[5], r[6]) for r in before)
        finally:
            backup.close()
    finally:
        library.close()


def test_rollback_invalidates_repository_handle_and_read_uow_rejects_write(library_and_factory):
    library, factory = library_and_factory
    baseline = _baseline(SQLiteBlobStore(library))
    with factory.begin(SCOPE) as uow:
        repository = uow.implementation
        uow.rollback()
    with pytest.raises(ApplicationError, match='UOW_NOT_ACTIVE'):
        repository.resolve_repository_baseline(baseline.ref)

    with factory.begin(SCOPE, 'read') as read_uow:
        with pytest.raises(ApplicationError, match='READ_ONLY_UOW'):
            read_uow.implementation.create_repository_baseline(baseline)
