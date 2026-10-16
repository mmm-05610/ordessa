"""Same-owner port interaction and real synthetic SQLite CAS transactions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite, DomainRevisionConflict
from ordessa_units.public import SqliteUnitStore
from ordessa_execution_agents.profiles.management.ports import ProfileStorePort
from ordessa_execution_agents.profiles import ProfileService
from ordessa_execution_agents.profiles.management.compatibility import PROFILE_RECORDS as CATALOG, REVISION_RECORDS as MANIFESTS
from ordessa_execution_agents.profiles.definitions.codec import encode_content
from agent_tools_fixtures.profile_unit_owner import make_profile_unit_owner, close_profile_unit_owner

class Policy:
    def admit_invoke(self, *args): return True
    def admit_object_access(self, *args): return True


class RecordingStore(SqliteUnitStore):
    def __init__(self, path):
        super().__init__(path)
        self.changes = []

    def commit_domain_change(self, request, digest, writes, result):
        self.changes.append((request, digest, writes))
        return super().commit_domain_change(request, digest, writes, result)


def test_service_uses_same_owner_atomic_writes_and_keeps_history(tmp_path):
    store = RecordingStore(tmp_path / "temporary.sqlite")
    env, harness_catalog, material_catalog = make_profile_unit_owner(store, Policy(), "port-test")
    try:
        service = ProfileService(env)
        assert isinstance(service._profile_store, ProfileStorePort)
        assert service._profile_store._owner() is store
        manifest = {"schemaVersion": "1", "harnessDefinitionRef": {
            "environmentNamespace": "port-test", "definitionId": "opaque"}, "declarations": []}
        first = service.create(profile_id="main", name="Main", content=manifest,
                               request=service.request_key("first"))
        second = service.revise("main", content={**manifest, "metadata": {"intent": "updated"}},
            expected_version=1, base_revision=first.current_revision,
            request=service.request_key("second"))
        assert env._store is store
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
        close_profile_unit_owner(env, harness_catalog, material_catalog, store)


def test_same_owner_concurrent_writers_compare_versions_atomically_and_rollback(tmp_path):
    path = tmp_path / "race.sqlite"
    first = SqliteUnitStore(path)
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
