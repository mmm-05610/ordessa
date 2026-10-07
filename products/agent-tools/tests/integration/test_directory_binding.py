"""Temporary real Workspace DB, shared Environment store and filesystem.

No production contribution admission, native process, service or model claim.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
import time

import pytest

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from ordessa_server.idempotency import IdempotentRecords
from ordessa_workspace.records import WorkspaceRecords
from ordessa_workspace.public import DirectoryBindingService, DirectoryGrant, LocalDirectoryRealm, ProjectRef
from pacthold.agents.public import DirectoryBindingRef
from pacthold.public import Environment
from ordessa_persistence_sqlite.product_database import Database


class Authority:
    def __init__(self, principal, project):
        self.grant = DirectoryGrant(principal, project, ("read", "write", "execute"), "grant-1", time.time() + 600)
        self.allowed = True
        self.asked = []

    def authorize(self, principal, project_ref, purposes):
        self.asked.append((principal, project_ref, purposes))
        return self.grant if self.allowed else None

    def revalidate(self, principal, project_ref, grant):
        self.asked.append((principal, project_ref, grant.purposes))
        return self.grant if self.allowed else None


@pytest.fixture
def fixture(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    database = Database(tmp_path / "workspace.sqlite")
    database.initialize()
    records = WorkspaceRecords(database, IdempotentRecords(database))
    _, row = records.upsert_by_location(env_kind="local", env_host="fixture-host", remote_user=None,
                                      normalized_path=str(project), connection_id=None)
    project_ref = ProjectRef("binding-test", row["id"], row["version"])
    store = SqliteStorePort(tmp_path / "environment.sqlite")
    fingerprint = ProtectedFingerprintHmac({"fixture": b"binding-test-key"}, active_key_id="fixture")
    # The service gets the same port object already backing this Environment;
    # it has no access to Environment internals and opens no independent DB.
    environment = Environment("binding-test", store=store, fingerprint_port=fingerprint, principal_scope="fixture-user")
    authority = Authority("fixture-user", project_ref)
    options = dict(environment_namespace="binding-test", principal_scope="fixture-user", store=store,
                   fingerprint_port=fingerprint, records=records, authority_port=authority,
                   realm=LocalDirectoryRealm("fixture-host", "fixture-fs", "fixture-native"))
    service = DirectoryBindingService(**options)
    yield service, options, project_ref, project, authority, database, environment
    environment.close()
    store.close()


def key(name="issue", principal="fixture-user", environment="binding-test"):
    return RequestKey(environment, principal, name)


def issue(fixture, purposes=("read", "execute"), request=None):
    service, _, project, *_ = fixture
    return service.issue(request or key(), project, purposes)


def test_real_binding_replay_restart_and_authorized_evidence(fixture):
    service, options, project_ref, project, authority, _, _ = fixture
    ref = issue(fixture)
    assert isinstance(ref, DirectoryBindingRef)
    evidence = service.revalidate(ref, "fixture-user", ("execute",))
    observed = project.stat()
    assert (evidence.device, evidence.inode) == (observed.st_dev, observed.st_ino)
    assert evidence.canonical_path == str(project.resolve())
    assert evidence.project_ref == project_ref
    assert evidence.realm == options["realm"]
    assert DirectoryBindingRef.from_dict(evidence.to_dict()["bindingRef"]) == ref
    assert service.issue(key(), project_ref, ("execute", "read")) == ref
    restarted = DirectoryBindingService(**options)
    assert restarted.revalidate(ref, "fixture-user", ("read",)).binding_ref == ref
    assert len(options["store"].list_domain("binding-test", "workspace.directory-bindings")) == 1
    assert authority.asked


def test_two_store_connections_share_one_binding_claim(fixture):
    service, options, project_ref, project, _, _, _ = fixture
    store2 = SqliteStorePort(project.parent / "environment.sqlite", allow_takeover=True)
    try:
        second = DirectoryBindingService(**{**options, "store": store2})
        with ThreadPoolExecutor(max_workers=2) as pool:
            refs = list(pool.map(lambda owner: owner.issue(key(), project_ref, ("read",)), (service, second)))
        assert refs[0] == refs[1]
        assert len(options["store"].list_domain("binding-test", "workspace.directory-bindings")) == 1
    finally:
        store2.close()


def test_same_request_changed_purposes_conflicts(fixture):
    issue(fixture)
    with pytest.raises(IdentityMismatchError):
        issue(fixture, purposes=("read",))


@pytest.mark.parametrize("swap", ["project", "purposes", "same_content"])
def test_replay_cannot_be_swapped_to_another_valid_binding(fixture, swap):
    _, options, project_a, directory, _, _, _ = fixture
    if swap == "project":
        other = directory.parent / "other-project"
        other.mkdir()
        _, row = options["records"].upsert_by_location(env_kind="local", env_host="fixture-host", remote_user=None,
                                                      normalized_path=str(other), connection_id=None)
        project_b = ProjectRef("binding-test", row["id"], row["version"])
    else:
        project_b = project_a
    class MultipleProjectAuthority:
        grants = {project: DirectoryGrant("fixture-user", project, ("read", "execute"), "grant-1", time.time() + 600)
                  for project in (project_a, project_b)}
        def authorize(self, principal, project, purposes):
            return self.grants[project]
        def revalidate(self, principal, project, grant):
            return self.grants[project]
    service = DirectoryBindingService(**{**options, "authority_port": MultipleProjectAuthority()})
    ref_a = service.issue(key("a"), project_a, ("read",))
    ref_b = service.issue(key("b"), project_b, ("read", "execute") if swap == "purposes" else ("read",))
    assert service.revalidate(ref_b, "fixture-user", ("read",)).binding_ref == ref_b
    # Corrupt only this temporary store's concluded receipt while preserving
    # A's protected request digest. B is a genuinely valid, authorized binding.
    with sqlite3.connect(directory.parent / "environment.sqlite") as connection:
        encoded = connection.execute("SELECT receipt FROM env_requests WHERE request_id='a'").fetchone()[0]
        receipt = json.loads(encoded)
        receipt["domain_result"] = ref_b.to_dict()
        connection.execute("UPDATE env_requests SET receipt=? WHERE request_id='a'", (json.dumps(receipt),))
    assert ref_a != ref_b
    with pytest.raises(IdentityMismatchError, match="fixed issuance request"):
        service.issue(key("a"), project_a, ("read",))


@pytest.mark.parametrize("missing", ["authority_port", "fingerprint_port", "store"])
def test_absent_resource_never_signs_binding(fixture, missing):
    _, options, project_ref, *_ = fixture
    service = DirectoryBindingService(**{**options, missing: None})
    with pytest.raises(GuaranteeUnavailableError):
        service.issue(key(), project_ref, ("read",))
    assert options["store"].list_domain("binding-test", "workspace.directory-bindings") == ()


def test_os_access_does_not_grant_execute(fixture):
    _, options, _, _, authority, _, _ = fixture
    authority.grant = replace(authority.grant, purposes=("read",))
    with pytest.raises(AdmissionRefusedError):
        issue(fixture, purposes=("execute",))
    assert options["store"].list_domain("binding-test", "workspace.directory-bindings") == ()


def test_binding_purpose_never_expands_to_authority_superset(fixture):
    service, _, _, _, authority, _, _ = fixture
    assert "execute" in authority.grant.purposes
    ref = issue(fixture, purposes=("read",))
    assert service.revalidate(ref, "fixture-user", ("read",)).purposes == ("read",)
    with pytest.raises(AdmissionRefusedError):
        service.revalidate(ref, "fixture-user", ("execute",))


def test_authority_revocation_revision_and_expiry_do_not_renew(fixture, monkeypatch):
    service, _, _, _, authority, _, _ = fixture
    ref = issue(fixture)
    authority.allowed = False
    with pytest.raises(AdmissionRefusedError):
        service.revalidate(ref, "fixture-user", ("execute",))
    with pytest.raises(AdmissionRefusedError):
        issue(fixture)
    authority.allowed = True
    original = authority.grant
    authority.grant = replace(original, authority_revision="grant-2")
    with pytest.raises(IdentityMismatchError):
        service.revalidate(ref, "fixture-user", ("execute",))
    authority.grant = replace(original, expires_at=original.expires_at + 600)
    with pytest.raises(IdentityMismatchError):
        service.revalidate(ref, "fixture-user", ("execute",))
    monkeypatch.setattr(time, "time", lambda: original.expires_at + 1)
    with pytest.raises(AdmissionRefusedError):
        service.revalidate(ref, "fixture-user", ("execute",))


@pytest.mark.parametrize("change", ["version", "archived", "host", "remote", "missing_host"])
def test_project_and_local_host_changes_refuse(fixture, change):
    service, _, project_ref, _, _, database, _ = fixture
    ref = issue(fixture)
    field, value = {"version": ("version", 2), "archived": ("archived_at", "fixture-archived"),
                    "host": ("env_host", "different-host"), "remote": ("env_kind", "ssh"), "missing_host": ("env_host", None)}[change]
    with database.transaction() as connection:
        connection.execute("UPDATE server_workspaces SET " + field + "=? WHERE id=?", (value, project_ref.project_id))
    with pytest.raises((GuaranteeUnavailableError, IdentityMismatchError)):
        service.revalidate(ref, "fixture-user", ("read",))


def test_directory_replacement_and_symlink_alias_change_refuse(fixture, tmp_path):
    service, _, project_ref, project, _, database, _ = fixture
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    with database.transaction() as connection:
        connection.execute("UPDATE server_workspaces SET normalized_path=? WHERE id=?", (str(alias), project_ref.project_id))
    ref = issue(fixture)
    assert service.revalidate(ref, "fixture-user", ("read",)).canonical_path == str(project)
    different = tmp_path / "different"
    different.mkdir()
    alias.unlink()
    alias.symlink_to(different, target_is_directory=True)
    with pytest.raises(IdentityMismatchError):
        service.revalidate(ref, "fixture-user", ("read",))
    alias.unlink()
    alias.symlink_to(project, target_is_directory=True)
    project.rename(tmp_path / "old")
    project.mkdir()
    with pytest.raises(IdentityMismatchError):
        service.revalidate(ref, "fixture-user", ("read",))


def test_principal_namespace_realm_and_forged_ref_refuse(fixture):
    service, options, _, _, _, _, _ = fixture
    with pytest.raises(AdmissionRefusedError):
        issue(fixture, request=key(principal="other-user"))
    with pytest.raises(IdentityMismatchError):
        issue(fixture, request=key(environment="foreign"))
    ref = issue(fixture)
    with pytest.raises(AdmissionRefusedError):
        service.revalidate(ref, "other-user", ("read",))
    with pytest.raises(IdentityMismatchError):
        service.revalidate(replace(ref, content_digest="sha256:" + "0" * 64), "fixture-user", ("read",))
    with pytest.raises(IdentityMismatchError):
        DirectoryBindingService(**{**options, "realm": LocalDirectoryRealm("different-host", "fixture-fs", "fixture-native")}).revalidate(ref, "fixture-user", ("read",))


def test_authority_exception_text_is_not_diagnostic(fixture):
    service, _, project, *_ = fixture
    class BrokenAuthority:
        def authorize(self, *args):
            raise RuntimeError("credential-do-not-expose")
        def revalidate(self, *args):
            raise RuntimeError("credential-do-not-expose")
    service.authority_port = BrokenAuthority()
    with pytest.raises(AdmissionRefusedError) as raised:
        service.issue(key(), project, ("read",))
    assert "credential-do-not-expose" not in str(raised.value)
