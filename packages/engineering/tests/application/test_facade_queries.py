"""Facade to real SQLite, including reopen/rollback and authenticated reads.

The access port is synthetic; these tests do not claim production admission.
"""
import asyncio
from dataclasses import asdict

import pytest

from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.commands import CommandContext, CommandKey, ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.common.models.identity import (ActorRef, Scope)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)


SCOPE = Scope("realm-facade", "project-facade")
AT = "2026-10-09T12:00:00.000000Z"


def context(request_id, *, principal="principal", scope=SCOPE):
    return CommandContext(scope, principal, ActorRef("human", "human", "test"),
                          request_id, AT, "trace")


class Access:
    def __init__(self):
        self.calls = []
        self.allowed_context = None

    def require(self, ctx, operation):
        if self.allowed_context is not None and ctx is not self.allowed_context:
            raise ApplicationError("ACCESS_DENIED")
        self.calls.append((ctx, operation))


@pytest.fixture
def environment(tmp_path):
    path = (tmp_path / "facade.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="facade-test", schema_version=7)
    access = Access()
    factory = SQLiteUoWFactory(library)
    try:
        yield path, library, factory, access, EngineeringService(factory, access)
    finally:
        library.close()


def execute(facade, operation, parameters, ctx, **kwargs):
    return asyncio.run(facade.execute(operation, parameters, ctx, **kwargs))


def query(facade, name, parameters, ctx):
    return asyncio.run(facade.query(name, parameters, ctx))


def initial():
    return {"media_type": "application/json", "schema_id": "urn:synthetic:artifact",
            "inline_value": {"synthetic": True}}


def test_create_append_exact_read_retry_and_reopen(environment):
    path, library, _factory, access, facade = environment
    params = {"kind": "plan", "initial": initial()}
    created = execute(facade, "engineering.artifacts.create", params, context("create"))
    assert created.status == "completed"
    assert execute(facade, "engineering.artifacts.create", params, context("create")) == created
    artifact_id = created.result["artifact"]["artifact_id"]
    ref = created.result["revision_ref"]
    read_ctx = context("independent-read-request")
    access.allowed_context = read_ctx
    assert query(facade, "engineering.commands.get", {"request_id": "create"}, read_ctx) == created
    assert access.calls[-1] == (read_ctx, "engineering.commands.get")
    resolved = query(facade, "engineering.references.resolve", {"ref": ref}, read_ctx)
    assert asdict(resolved.ref) == ref
    access.allowed_context = None
    append = {"artifact_id": artifact_id, "expected_version": 1,
              "parents": [ref], "payload": initial()}
    appended = execute(facade, "engineering.artifacts.append_revision", append, context("append"),
                       read_set=ReadSet(SCOPE, (ReadVersion("artifact", artifact_id, 1),)))
    assert appended.status == "completed"
    library.close()
    reopened = EngineeringLibrary.open(path, library_id="facade-test")
    try:
        facade = EngineeringService(SQLiteUoWFactory(reopened), access)
        assert execute(facade, "engineering.artifacts.append_revision", append, context("append"),
                       read_set=ReadSet(SCOPE, (ReadVersion("artifact", artifact_id, 1),))) == appended
        artifact = query(facade, "engineering.artifacts.get", {"artifact_id": artifact_id}, read_ctx)
        assert artifact.version == 2 and artifact.head_revision_id is None
        assert reopened._connection.execute("SELECT count(*) FROM eng_artifact_revisions").fetchone()[0] == 2
    finally:
        reopened.close()


def test_read_set_refusal_commits_only_original_rejection(environment):
    _path, library, _factory, _access, facade = environment
    created = execute(facade, "engineering.artifacts.create", {"kind": "plan", "initial": initial()}, context("create"))
    artifact_id = created.result["artifact"]["artifact_id"]
    params = {"artifact_id": artifact_id, "expected_version": 1, "parents": [], "payload": initial()}
    rejected = execute(facade, "engineering.artifacts.append_revision", params, context("stale"),
                       read_set=ReadSet(SCOPE, (ReadVersion("artifact", artifact_id, 0),)))
    assert rejected.status == "rejected" and rejected.result == {"code": "READ_SET_CHANGED"}
    assert library._connection.execute("SELECT count(*) FROM eng_artifact_revisions").fetchone()[0] == 1
    assert query(facade, "engineering.commands.get", {"request_id": "stale"}, context("read")) == rejected


def test_storage_failure_rolls_back_entire_command(environment, monkeypatch):
    path, library, _factory, access, facade = environment
    from ordessa_engineering.adapters.persistence.sqlite.artifact_repository import SQLiteArtifactRepository
    original = SQLiteArtifactRepository.append_revision

    def fail_after_real_append(repository, revision, *, expected_version):
        original(repository, revision, expected_version=expected_version)
        # Test-only fault injection: a real duplicate PK in the same SQLite
        # transaction, after both artifact and revision have been written.
        repository.access.execute(
            "INSERT INTO eng_artifacts SELECT * FROM eng_artifacts "
            "WHERE realm_id=? AND project_id=? AND artifact_id=?",
            (revision.scope.realm_id, revision.scope.project_id, revision.artifact_id))

    monkeypatch.setattr(SQLiteArtifactRepository, "append_revision", fail_after_real_append)
    with pytest.raises(ApplicationError) as failed:
        execute(facade, "engineering.artifacts.create", {"kind": "plan", "initial": initial()}, context("fault"))
    assert failed.value.code == "STORAGE_CONSTRAINT"
    assert not library._connection.in_transaction
    library.close()
    reopened = EngineeringLibrary.open(path, library_id="facade-test")
    try:
        for table in ("eng_artifacts", "eng_artifact_revisions", "eng_commands"):
            assert reopened._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        with pytest.raises(ApplicationError, match="COMMAND_NOT_FOUND"):
            query(EngineeringService(SQLiteUoWFactory(reopened), access),
                  "engineering.commands.get", {"request_id": "fault"}, context("read"))
    finally:
        reopened.close()


def test_pending_recovery_after_reopen_is_read_only(environment):
    path, library, factory, access, _facade = environment
    with factory.begin(SCOPE) as uow:
        uow.commands.reserve(CommandKey(SCOPE.realm_id, "principal", "pending"),
                             project_id=SCOPE.project_id, operation="engineering.artifacts.create",
                             operation_id="original-operation", request_digest=Digest("sha256", "a" * 64))
        uow.commit()
    library.close()
    reopened = EngineeringLibrary.open(path, library_id="facade-test")
    try:
        result = query(EngineeringService(SQLiteUoWFactory(reopened), access),
                       "engineering.commands.get", {"request_id": "pending"}, context("read"))
        assert result.operation_id == "original-operation"
        assert result.status == "pending" and result.result is None
        assert reopened._connection.execute("SELECT version FROM eng_commands").fetchone()[0] == 0
        assert reopened._connection.execute("SELECT count(*) FROM eng_artifacts").fetchone()[0] == 0
    finally:
        reopened.close()


def test_facade_preserves_commit_unknown_then_recovers_durable_result(environment, monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
    path, library, _factory, access, facade = environment
    original_commit = storage._LibraryConnection.commit
    failure = RuntimeError("synthetic commit lost reply")

    def lost_reply(connection):
        original_commit(connection)
        raise failure

    parameters = {"kind": "plan", "initial": initial()}
    with monkeypatch.context() as patch:
        patch.setattr(storage._LibraryConnection, "commit", lost_reply)
        with pytest.raises(ApplicationError) as failed:
            execute(facade, "engineering.artifacts.create", parameters, context("uncertain"))
    assert failed.value.code == "COMMIT_UNKNOWN" and failed.value.retry == "reconcile"
    assert library._closed
    reopened = EngineeringLibrary.open(path, library_id="facade-test")
    try:
        restored_facade = EngineeringService(SQLiteUoWFactory(reopened), access)
        original = query(restored_facade, "engineering.commands.get", {"request_id": "uncertain"}, context("read"))
        assert original.status == "completed"
        assert execute(restored_facade, "engineering.artifacts.create", parameters, context("uncertain")) == original
        for table in ("eng_artifacts", "eng_artifact_revisions", "eng_commands"):
            assert reopened._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("principal,scope,code", [
    ("other", SCOPE, "COMMAND_NOT_FOUND"),
    ("principal", Scope(SCOPE.realm_id, "other-project"), "SCOPE_MISMATCH"),
    ("principal", Scope("other-realm", SCOPE.project_id), "COMMAND_NOT_FOUND"),
])
def test_command_queries_cannot_cross_authenticated_identity(environment, principal, scope, code):
    _path, _library, _factory, _access, facade = environment
    execute(facade, "engineering.artifacts.create", {"kind": "plan"}, context("create"))
    with pytest.raises(ApplicationError) as failed:
        query(facade, "engineering.commands.get", {"request_id": "create"}, context("read", principal=principal, scope=scope))
    assert failed.value.code == code


def test_exact_read_rejects_wrong_digest_scope_and_unavailable_owner(environment):
    _path, _library, _factory, _access, facade = environment
    result = execute(facade, "engineering.artifacts.create", {"kind": "plan", "initial": initial()}, context("create"))
    ref = result.result["revision_ref"]
    for changed, code in (({**ref, "digest": {"algorithm": "sha256", "hex": "0" * 64}}, "RECORD_CORRUPT"),
                          ({**ref, "project_id": "other-project"}, "SCOPE_MISMATCH")):
        with pytest.raises(ApplicationError) as failed:
            query(facade, "engineering.references.resolve", {"ref": changed}, context("read"))
        assert failed.value.code == code
    unavailable = {"kind": "submission", "realm_id": SCOPE.realm_id, "project_id": SCOPE.project_id,
                   "submission_id": "missing", "digest": {"algorithm": "sha256", "hex": "a" * 64}}
    with pytest.raises(ApplicationError, match="REFERENCE_OWNER_UNAVAILABLE"):
        query(facade, "engineering.references.resolve", {"ref": unavailable}, context("read"))


@pytest.mark.parametrize("operation,code", [
    ("engineering.executions.dispatch", "DISPATCH_AUTHORITY_UNAVAILABLE"),
    # request now has a closed host contract; an empty plan remains invalid
    # and must not reserve a command or dispatch a reviewer.
    ("engineering.reviews.request", "INVALID_INPUT"),
    ("engineering.approvals.record_consent", "OPERATION_UNAVAILABLE"),
    ("os.system", "OPERATION_UNAVAILABLE"),
])
def test_missing_contracts_never_dispatch_or_reserve(environment, operation, code):
    _path, library, _factory, _access, facade = environment
    with pytest.raises(ApplicationError, match=code):
        execute(facade, operation, {}, context("unavailable"))
    assert library._connection.execute("SELECT count(*) FROM eng_commands").fetchone()[0] == 0


def test_queries_keep_closed_inputs_and_require_admission(environment):
    _path, _library, factory, access, facade = environment
    with pytest.raises(ApplicationError, match="INVALID_INPUT"):
        query(facade, "engineering.commands.get", {"request_id": "r", "principal_id": "other"}, context("read"))
    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        query(EngineeringService(factory, None), "engineering.artifacts.get", {"artifact_id": "a"}, context("read"))
    access.allowed_context = context("different-context")
    with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
        execute(facade, "engineering.artifacts.create", {"kind": "plan"}, context("create"))


def test_read_version_uses_sqlite_cas_range():
    assert ReadVersion("artifact", "a", (1 << 63) - 1).version == (1 << 63) - 1
    with pytest.raises(ReferenceError, match="INVALID_VERSION"):
        ReadVersion("artifact", "a", 1 << 63)
