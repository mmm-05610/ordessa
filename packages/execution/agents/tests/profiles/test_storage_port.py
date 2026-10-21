"""Same-owner port interaction and real synthetic SQLite CAS transactions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite, DomainRevisionConflict
from ordessa_agents.profiles.management.sqlite_store import SqliteProfileStore
from ordessa_agents.profiles.management.ports import ProfileStorePort
from ordessa_agents.profiles import ProfileService
from ordessa_agents.profiles.management.compatibility import PROFILE_RECORDS as CATALOG, REVISION_RECORDS as MANIFESTS
from ordessa_agents.profiles.definitions.codec import encode_content
from profile_owner_fixtures import Admission, Validator

class Policy:
    def admit_invoke(self, *args): return True
    def admit_object_access(self, *args): return True


class RecordingStore(SqliteProfileStore):
    def __init__(self, path):
        super().__init__(path)
        self.changes = []

    def commit_domain_change(self, request, digest, writes, result):
        self.changes.append((request, digest, writes))
        return super().commit_domain_change(request, digest, writes, result)


def test_service_uses_same_owner_atomic_writes_and_keeps_history(tmp_path):
    store = RecordingStore(tmp_path / "temporary.sqlite")
    admission = Admission(Policy(), "port-test")
    try:
        service = ProfileService(store, admission, Validator())
        assert isinstance(service._profile_store, ProfileStorePort)
        assert service._profile_store is store
        manifest = {"schemaVersion": "1", "harnessDefinitionRef": {
            "environmentNamespace": "port-test", "definitionId": "opaque"}, "declarations": []}
        first = service.create(profile_id="main", name="Main", content=manifest,
                               request=service.request_key("first"))
        second = service.revise("main", content={**manifest, "metadata": {"intent": "updated"}},
            expected_version=1, base_revision=first.current_revision,
            request=service.request_key("second"))
        assert service._admission is admission
        assert [[(w.namespace, w.record_id, w.expected_revision) for w in writes]
            for _, _, writes in store.changes] == [
                [(CATALOG, "main", 0), (MANIFESTS, "main@1", 0)],
                [(CATALOG, "main", 1), (MANIFESTS, "main@2", 0)]]
        assert encode_content(service.get_revision(first.current_revision).content) == manifest
        assert service.get("main") == second
        archived = service.archive("main", expected_version=2,
                                   request=service.request_key("archive"))
        assert service.list() == ()
        assert service.list(include_archived=True) == (archived,)
        assert encode_content(service.get_revision(first.current_revision).content) == manifest
    finally:
        store.close()


def test_same_owner_concurrent_writers_compare_versions_atomically_and_rollback(tmp_path):
    path = tmp_path / "race.sqlite"
    first = SqliteProfileStore(path)
    barrier = Barrier(2)
    def commit(store, identity):
        barrier.wait(timeout=5)
        request = RequestKey("race", "synthetic", identity)
        try:
            store.commit_domain_change(request, identity, (
                DomainWrite(MANIFESTS, identity, 0, {"candidate": identity}),
                DomainWrite(CATALOG, "same", 0, {"winner": identity}),
            ), {"winner": identity})
            return identity
        except DomainRevisionConflict:
            return None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(commit, first, "one"), executor.submit(commit, first, "two")]
            results = [future.result(timeout=10) for future in futures]
        assert results.count(None) == 1
        winner = next(value for value in results if value)
        loser = "one" if winner == "two" else "two"
        assert first.read_domain("race", CATALOG, "same")["value"] == {"winner": winner}
        assert first.read_domain("race", MANIFESTS, loser) is None
        assert first.read_domain_result(RequestKey("race", "synthetic", loser), loser) is None
    finally:
        first.close()


def test_profile_validation_refusal_is_before_any_record_or_request_commit(tmp_path):
    from ordessa_agents.profiles.definitions.errors import ProfileValidationError
    store=SqliteProfileStore(tmp_path/'validation.sqlite');validator=Validator();validator.refuse=True
    admission=Admission(Policy(),'validation')
    service=ProfileService(store,admission,validator)
    manifest={'schemaVersion':'1','harnessDefinitionRef':{'environmentNamespace':'validation','definitionId':'opaque'},'declarations':[]}
    try:
        with pytest.raises(ProfileValidationError):
            service.create(profile_id='main',name='Main',content=manifest,request=service.request_key('refused'))
        assert len(validator.contents)==1
        assert store.list_profiles('validation')==()
        assert store._conn.execute('SELECT count(*) FROM profile_requests').fetchone()[0]==0
        validator.refuse=False
        created=service.create(profile_id='main',name='Main',content=manifest,request=service.request_key('accepted'))
        validator.refuse=True
        assert service.create(profile_id='main',name='Main',content=manifest,request=service.request_key('accepted'))==created
        assert len(validator.contents)==2  # replay cannot revalidate or create side effects
    finally:store.close()


def test_new_profile_store_refuses_existing_unit_database_without_mutating_it(tmp_path):
    import sqlite3
    from ordessa_agents.profiles.definitions.errors import ProfileStoreUnavailable
    path=tmp_path/'historical-unit.sqlite'
    conn=sqlite3.connect(path);conn.execute('CREATE TABLE env_domain_records(original TEXT)');conn.commit();conn.close()
    before=path.read_bytes()
    with pytest.raises(ProfileStoreUnavailable):SqliteProfileStore(path)
    assert path.read_bytes()==before


def test_separate_profile_connections_keep_cas_and_request_result_atomic(tmp_path):
    path=tmp_path/'independent.sqlite';stores=[SqliteProfileStore(path),SqliteProfileStore(path)];barrier=Barrier(2)
    def write(index):
        barrier.wait(timeout=5)
        try:
            return stores[index].commit_domain_change(RequestKey('race','fixture','request-'+str(index)),str(index),(
                DomainWrite(MANIFESTS,str(index),0,{'candidate':index}),
                DomainWrite(CATALOG,'same',0,{'winner':index}),),{'winner':index})
        except DomainRevisionConflict:return None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(write,range(2)))
        assert results.count(None)==1
        winner=next(x['winner'] for x in results if x is not None);loser=1-winner
        assert stores[0].read_domain('race',CATALOG,'same')['value']=={'winner':winner}
        assert stores[0].read_domain('race',MANIFESTS,str(loser)) is None
        assert stores[0].read_domain_result(RequestKey('race','fixture','request-'+str(loser)),str(loser)) is None
    finally:
        for store in stores:store.close()


def test_concurrent_first_profile_database_opens_initialize_one_schema_version(tmp_path):
    path=tmp_path/'first-open.sqlite';barrier=Barrier(4)
    def open_store(_):
        barrier.wait(timeout=5)
        store=SqliteProfileStore(path)
        try:return store._conn.execute('SELECT version FROM profile_store_meta').fetchall()
        finally:store.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(open_store,range(4)))
    assert results==[[(1,)]]*4
    final=SqliteProfileStore(path)
    try:assert final.available()
    finally:final.close()
