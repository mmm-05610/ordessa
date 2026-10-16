"""Real SQLite acceptance for artifact command use cases; no production auth claim."""
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.command_journal import SQLiteCommandJournal
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.contracts.commands import CommandContext, ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)


LIBRARY_ID = "test.artifact-usecases"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
TEST_ACTOR = ActorRef("test-human", "human", "synthetic-test-issuer")


class SyntheticAccess:
    """Test adapter that allows calls; it is not production authentication."""

    def __init__(self):
        self.calls = []

    def require(self, context, operation):
        self.calls.append((context, operation))


@pytest.fixture
def environment(tmp_path: Path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(
        path, library_id=LIBRARY_ID, schema_version=6,
    )
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    try:
        yield library, factory, ArtifactUseCases(factory, access), access
    finally:
        library.close()


def _scope(project_id: str = "project-1") -> Scope:
    return Scope("realm-1", project_id)


def _context(scope: Scope, request_id: str = "request-1") -> CommandContext:
    return CommandContext(
        scope=scope,
        principal_id="principal-1",
        authenticated_actor=TEST_ACTOR,
        request_id=request_id,
        received_at=CREATED_AT,
        trace_id="trace-1",
    )


def _initial(value="initial"):
    return {
        "media_type": "application/json",
        "schema_id": "urn:test:artifact",
        "inline_value": {"value": value},
    }


def _create_parameters(**extra):
    return {"kind": "plan", **extra}


def _parent_dict(ref: dict) -> dict:
    return ref


def _revision_ref(value: dict) -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        value["realm_id"], value["project_id"], value["artifact_id"],
        value["revision_id"], Digest(**value["digest"]),
    )


def _row_count(library, table: str) -> int:
    assert table in {"eng_artifacts", "eng_artifact_revisions", "eng_commands"}
    return library._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _append_parameters(artifact_id: str, *, expected_version: int,
                       parents=(), value="append"):
    return {
        "artifact_id": artifact_id,
        "expected_version": expected_version,
        "parents": list(parents),
        "payload": _initial(value),
    }


def test_create_initial_append_and_same_request_retries_are_atomic_and_do_not_move_head(
    environment,
):
    library, factory, usecases, _access = environment
    scope = _scope()
    create_context = _context(scope, "create-once")
    created = usecases.create(_create_parameters(initial=_initial()), create_context)

    assert created.status == "completed"
    assert created.result["artifact"]["head_revision_id"] is None
    assert created.result["artifact"]["version"] == 1
    assert created.result["revision_ref"] is not None
    assert _row_count(library, "eng_artifacts") == 1
    assert _row_count(library, "eng_artifact_revisions") == 1
    artifact_id = created.result["artifact"]["artifact_id"]
    initial_ref = _revision_ref(created.result["revision_ref"])
    artifact = usecases.get_artifact(artifact_id, create_context)
    assert artifact.head_revision_id is None and artifact.version == 1

    created_again = usecases.create(_create_parameters(initial=_initial()), create_context)
    assert created_again.operation_id == created.operation_id
    assert created_again.result == created.result
    assert _row_count(library, "eng_artifacts") == 1
    assert _row_count(library, "eng_artifact_revisions") == 1

    append_context = _context(scope, "append-once")
    append_params = _append_parameters(
        artifact_id, expected_version=1, parents=(_parent_dict(created.result["revision_ref"]),),
    )
    appended = usecases.append_revision(append_params, append_context)
    assert appended.status == "completed"
    appended_ref = _revision_ref(appended.result["revision_ref"])
    artifact_after_append = usecases.get_artifact(artifact_id, append_context)
    assert artifact_after_append.version == 2
    assert artifact_after_append.head_revision_id is None
    with factory.begin(scope, "read") as uow:
        assert uow.engineering.resolve_revision(initial_ref).ref == initial_ref
        assert uow.engineering.resolve_revision(appended_ref).parent_revision_refs == (initial_ref,)
        uow.commit()

    appended_again = usecases.append_revision(append_params, append_context)
    assert appended_again.operation_id == appended.operation_id
    assert appended_again.result == appended.result
    assert _row_count(library, "eng_artifact_revisions") == 2
    assert usecases.get_artifact(artifact_id, append_context).version == 2


@pytest.mark.parametrize("conflict", ["parameters", "project", "operation"])
def test_same_request_key_rejects_changed_parameters_project_or_operation(environment, conflict):
    _library, _factory, usecases, _access = environment
    scope = _scope()
    context = _context(scope, f"conflict-{conflict}")
    first = usecases.create(_create_parameters(), context)
    assert first.status == "completed"

    with pytest.raises(ApplicationError) as caught:
        if conflict == "parameters":
            usecases.create({"kind": "specification"}, context)
        elif conflict == "project":
            usecases.create(_create_parameters(), _context(_scope("project-2"), context.request_id))
        else:
            usecases.append_revision(
                _append_parameters("missing-artifact", expected_version=0), context,
            )
    assert caught.value.code == "REQUEST_IDENTITY_CONFLICT"


def test_business_cas_refusal_is_journaled_without_appending_revision(environment):
    library, _factory, usecases, _access = environment
    scope = _scope()
    create_context = _context(scope, "cas-create")
    created = usecases.create(_create_parameters(initial=_initial()), create_context)
    artifact_id = created.result["artifact"]["artifact_id"]
    revision_count = _row_count(library, "eng_artifact_revisions")

    rejected = usecases.append_revision(
        _append_parameters(artifact_id, expected_version=0),
        _context(scope, "cas-stale"),
    )
    assert rejected.status == "rejected"
    assert rejected.result == {"code": "VERSION_CONFLICT"}
    assert _row_count(library, "eng_artifact_revisions") == revision_count
    assert usecases.get_artifact(artifact_id, create_context).version == 1
    refusal = usecases.get_command(_context(scope, "cas-stale"))
    assert refusal == rejected


@pytest.mark.parametrize("field", ["sources", "claims", "blob"])
def test_unimplemented_input_fields_are_rejected_without_being_discarded(environment, field):
    library, _factory, usecases, _access = environment
    scope = _scope()
    context = _context(scope, f"unsupported-{field}")
    with pytest.raises(ApplicationError) as caught:
        usecases.create(_create_parameters(**{field: [{"untrusted": True}]}), context)
    assert caught.value.code == "INVALID_INPUT"
    assert _row_count(library, "eng_artifacts") == 0
    assert _row_count(library, "eng_commands") == 0
    with pytest.raises(ApplicationError) as absent:
        usecases.get_command(context)
    assert absent.value.code == "COMMAND_NOT_FOUND"


def test_phantom_read_set_is_a_durable_business_refusal(environment):
    library, _factory, usecases, _access = environment
    scope = _scope()
    context = _context(scope, "phantom-read")
    reads = ReadSet(scope, (ReadVersion("artifact", "not-yet-present", 0),))
    result = usecases.create(_create_parameters(initial=_initial()), context, read_set=reads)

    assert result.status == "rejected"
    assert result.result == {"code": "READ_SET_CHANGED"}
    assert _row_count(library, "eng_artifacts") == 0
    assert _row_count(library, "eng_artifact_revisions") == 0
    assert usecases.get_command(context) == result


def test_human_actor_without_access_authority_is_rejected_before_any_facts(environment):
    library, _factory, _usecases, access = environment
    scope = _scope()
    context = _context(scope, "human-is-not-proof")
    unavailable = ArtifactUseCases(_factory, access=None)
    with pytest.raises(ApplicationError) as caught:
        unavailable.create(_create_parameters(initial=_initial()), context)
    assert caught.value.code == "ACCESS_AUTHORITY_UNAVAILABLE"
    assert _row_count(library, "eng_artifacts") == 0
    assert _row_count(library, "eng_artifact_revisions") == 0
    assert _row_count(library, "eng_commands") == 0
    assert access.calls == []


def test_completed_command_and_artifact_are_readable_after_reopen(tmp_path: Path):
    path = (tmp_path / "reopen.sqlite").resolve()
    scope = _scope()
    context = _context(scope, "reopen-request")
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    first_usecases = ArtifactUseCases(SQLiteUoWFactory(library), SyntheticAccess())
    created = first_usecases.create(_create_parameters(initial=_initial()), context)
    library.close()

    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        usecases = ArtifactUseCases(SQLiteUoWFactory(reopened), SyntheticAccess())
        assert usecases.get_command(context) == created
        artifact_id = created.result["artifact"]["artifact_id"]
        artifact = usecases.get_artifact(artifact_id, context)
        assert artifact.version == 1
        assert artifact.head_revision_id is None
        replay = usecases.create(_create_parameters(initial=_initial()), context)
        assert replay == created
    finally:
        reopened.close()


def test_command_completion_storage_failure_rolls_back_reservation_and_business_rows(
    tmp_path: Path, monkeypatch,
):
    path = (tmp_path / "failed-complete.sqlite").resolve()
    scope = _scope()
    context = _context(scope, "complete-storage-failure")
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    factory = SQLiteUoWFactory(library)
    usecases = ArtifactUseCases(factory, SyntheticAccess())

    def fail_complete(self, *args, **kwargs):
        self.access.require_write()
        raise ApplicationError("STORAGE_UNAVAILABLE", retry="reconcile")

    monkeypatch.setattr(SQLiteCommandJournal, "complete", fail_complete)
    try:
        with pytest.raises(ApplicationError) as caught:
            usecases.create(_create_parameters(initial=_initial()), context)
        assert caught.value.code == "STORAGE_UNAVAILABLE"
        assert _row_count(library, "eng_artifacts") == 0
        assert _row_count(library, "eng_artifact_revisions") == 0
        assert _row_count(library, "eng_commands") == 0
    finally:
        library.close()

    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        with SQLiteUoWFactory(reopened).begin(scope, "read") as uow:
            assert uow.commands.get(context.key) is None
            assert uow._access.execute("SELECT COUNT(*) FROM eng_artifacts").fetchone() == (0,)
            assert uow._access.execute(
                "SELECT COUNT(*) FROM eng_artifact_revisions").fetchone() == (0,)
            uow.commit()
    finally:
        reopened.close()


def test_usecase_commit_lost_reply_reopen_query_and_replay_recover_original_result(tmp_path, monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
    path = tmp_path / "actual-usecase-unknown.sqlite"
    original = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    original.close()
    connection_type = storage._LibraryConnection
    class LostCommit(connection_type):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_reply", False):
                self.lose_reply = False
                raise RuntimeError("synthetic committed reply loss")
            return result
    monkeypatch.setattr(storage, "_LibraryConnection", LostCommit)
    library = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    usecases = ArtifactUseCases(SQLiteUoWFactory(library), SyntheticAccess())
    context = _context(_scope(), "actual-unknown")
    library._connection.lose_reply = True
    with pytest.raises(ApplicationError) as unknown:
        usecases.create(_create_parameters(initial=_initial()), context)
    assert unknown.value.code == "COMMIT_UNKNOWN" and unknown.value.retry == "reconcile"
    assert library._closed
    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        restored = ArtifactUseCases(SQLiteUoWFactory(reopened), SyntheticAccess())
        saved = restored.get_command(context)
        assert saved.status == "completed"
        assert restored.create(_create_parameters(initial=_initial()), context) == saved
        assert _row_count(reopened, "eng_commands") == 1
        assert _row_count(reopened, "eng_artifacts") == 1
        assert _row_count(reopened, "eng_artifact_revisions") == 1
    finally:
        reopened.close()


def test_request_digest_schema_pin_and_detached_payloads_are_enforced(environment, monkeypatch):
    import json
    from ordessa_infrastructure.encoding import canonical_bytes
    from ordessa_engineering.application.usecases import artifacts as owner
    library, _, usecases, _ = environment
    ctx = _context(_scope(), "schema-binding")
    parameters = _create_parameters(initial=_initial())
    first = usecases.create(parameters, ctx)
    detached = first.result
    detached["artifact"]["kind"] = "corrupted-client-copy"
    assert first.result["artifact"]["kind"] == "plan"
    schema_copy = owner.input_schema("engineering.artifacts.create")
    schema_copy["additionalProperties"] = True
    assert owner.input_schema("engineering.artifacts.create")["additionalProperties"] is False
    schema = json.loads(owner._SCHEMA_BYTES["engineering.artifacts.create"])
    schema["description"] = "different exact schema bytes"
    monkeypatch.setitem(owner._SCHEMA_BYTES, "engineering.artifacts.create", canonical_bytes(schema))
    with pytest.raises(ApplicationError) as conflict:
        usecases.create(parameters, ctx)
    assert conflict.value.code == "REQUEST_IDENTITY_CONFLICT"
    assert _row_count(library, "eng_commands") == 1
    assert _row_count(library, "eng_artifacts") == 1


def test_existing_pending_command_is_reconciled_without_reexecuting(environment):
    from ordessa_engineering.domain.common.models.values import (Digest)
    from ordessa_engineering.application.contracts.commands import request_digest
    from ordessa_engineering.application.usecases import artifacts as owner
    import hashlib
    library, factory, usecases, _ = environment
    ctx = _context(_scope(), "previous-pending")
    operation = "engineering.artifacts.create"
    parameters = _create_parameters(initial=_initial())
    schema = owner.input_schema(operation)
    digest = request_digest(operation, ctx, parameters, [], input_schema_id=schema["$id"],
        input_schema_digest=Digest("sha256", hashlib.sha256(owner._SCHEMA_BYTES[operation]).hexdigest()),
        interface_version="2")
    with factory.begin(ctx.scope) as uow:
        uow.commands.reserve(ctx.key, project_id=ctx.scope.project_id, operation=operation,
            operation_id="original-pending", request_digest=digest)
        uow.commit()
    answer = usecases.create(parameters, ctx)
    assert answer.status == "pending" and answer.result is None
    assert answer.operation_id == "original-pending"
    assert _row_count(library, "eng_commands") == 1
    assert _row_count(library, "eng_artifacts") == 0
