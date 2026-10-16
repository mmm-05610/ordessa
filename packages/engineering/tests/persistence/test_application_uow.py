"""Real SQLite acceptance for the application UoW and its repositories."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

import sqlite3
import threading
from pathlib import Path

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite import engineering_library as library_module
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandKey, ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.codec import encode_revision
from ordessa_engineering.domain.artifacts.models import (
    Artifact, ArtifactRevision, InlinePayload,
)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)


LIBRARY_ID = "test.application-uow"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
ACTOR = ActorRef("test-actor", "human", "test-issuer")


@pytest.mark.parametrize("mode", [[], {}, None, True, "unsupported"])
def test_invalid_mode_is_a_stable_application_refusal(tmp_path, mode):
    library, factory = _open(tmp_path / "invalid-mode.sqlite")
    try:
        with pytest.raises(ApplicationError, match="INVALID_ARGUMENT"):
            factory.begin(Scope("realm", "project"), mode)
        assert not library._connection.in_transaction
    finally:
        library.close()


@pytest.mark.parametrize("mode", ["read", "write"])
def test_constructor_failure_releases_transaction_and_invalidates_access(tmp_path, monkeypatch, mode):
    from ordessa_engineering.adapters.persistence.sqlite import artifact_repository
    library, factory = _open(tmp_path / "constructor-failure.sqlite")
    captured = []

    def fail_repository(access):
        captured.append(access)
        raise ValueError("synthetic constructor failure")

    uow = factory.begin(Scope("realm", "project"), mode)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(artifact_repository, "SQLiteArtifactRepository", fail_repository)
            with pytest.raises(ValueError, match="synthetic constructor failure"):
                uow.__enter__()
        assert not library._connection.in_transaction
        assert library._connection.execute("PRAGMA query_only").fetchone()[0] == 0
        with pytest.raises(ApplicationError, match="UOW_NOT_ACTIVE"):
            captured[0].execute("SELECT 1")
        with pytest.raises(ApplicationError, match="UOW_REUSED"):
            uow.__enter__()
        with factory.begin(Scope("realm", "project")) as next_uow:
            next_uow.engineering.create(_artifact(next_uow.scope))
            next_uow.commit()
    finally:
        library.close()


def test_access_constructor_failure_also_rolls_back_entered_manager(tmp_path, monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite import unit_of_work
    library, factory = _open(tmp_path / "access-constructor-failure.sqlite")

    def fail_access(*args):
        raise ValueError("synthetic access failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(unit_of_work, "_RepositoryAccess", fail_access)
            with pytest.raises(ValueError, match="synthetic access failure"):
                with factory.begin(Scope("realm", "project")):
                    pytest.fail("must not enter")
        assert not library._connection.in_transaction
        with factory.begin(Scope("realm", "project")) as uow:
            uow.commit()
    finally:
        library.close()


@pytest.mark.parametrize("mode", [[], None, True, "unsupported"])
def test_direct_uow_constructor_refuses_invalid_mode(tmp_path, mode):
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteEngineeringUoW
    library, _factory = _open(tmp_path / "direct-constructor.sqlite")
    try:
        with pytest.raises(ApplicationError, match="INVALID_ARGUMENT"):
            SQLiteEngineeringUoW(library, Scope("realm", "project"), mode)
        assert not library._connection.in_transaction
    finally:
        library.close()


@pytest.mark.parametrize("business_error", [False, True])
def test_read_cleanup_failure_closes_library_and_preserves_primary(tmp_path, monkeypatch, business_error):
    base = library_module._LibraryConnection
    cleanup = RuntimeError("synthetic query_only restore failure")

    class Connection(base):
        armed = False

        def execute(self, sql, *args, **kwargs):
            if self.armed and sql == "PRAGMA query_only=0":
                raise cleanup
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(library_module, "_LibraryConnection", Connection)
    path = tmp_path / "read-cleanup.sqlite"
    library, factory = _open(path)
    connection = library._connection
    primary = ApplicationError("SYNTHETIC_BUSINESS_REFUSAL")
    with pytest.raises(ApplicationError) as failed:
        with factory.begin(Scope("realm", "project"), "read") as uow:
            connection.armed = True
            if business_error:
                raise primary
            uow.commit()
    assert failed.value.code == "TRANSACTION_UNCERTAIN"
    assert failed.value.retry == "reconcile"
    assert failed.value.__cause__ is cleanup
    assert failed.value.primary is (primary if business_error else None)
    assert library._closed
    with pytest.raises(ApplicationError, match="UOW_NOT_ACTIVE"):
        uow.engineering.get_artifact("missing")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    reopened = library_module.EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        with SQLiteUoWFactory(reopened).begin(Scope("realm", "project"), "read") as recovered:
            recovered.commit()
    finally:
        reopened.close()


def test_read_rollback_lost_reply_is_a_finite_error_even_if_second_rollback_succeeds(tmp_path, monkeypatch):
    base = library_module._LibraryConnection
    failure = RuntimeError("synthetic rollback lost reply")

    class Connection(base):
        armed = False

        def rollback(self):
            if self.armed:
                self.armed = False
                raise failure
            return super().rollback()

    monkeypatch.setattr(library_module, "_LibraryConnection", Connection)
    path = tmp_path / "read-rollback.sqlite"
    library, factory = _open(path)
    connection = library._connection
    with pytest.raises(ApplicationError) as failed:
        with factory.begin(Scope("realm", "project"), "read") as uow:
            connection.armed = True
            uow.commit()
    assert failed.value.code == "TRANSACTION_UNCERTAIN"
    assert failed.value.retry == "reconcile"
    assert failed.value.primary is failure and failed.value.__cause__ is failure
    assert library._closed
    with pytest.raises(ApplicationError, match="UOW_NOT_ACTIVE"):
        uow.engineering.get_artifact("missing")
    reopened = library_module.EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert reopened._connection.execute("SELECT count(*) FROM eng_commands").fetchone()[0] == 0
    finally:
        reopened.close()


def _open(path: Path):
    library = EngineeringLibrary.create(
        path.resolve(), library_id=LIBRARY_ID, schema_version=4,
    )
    return library, SQLiteUoWFactory(library)


def _artifact(scope: Scope, artifact_id: str = "artifact-1", *, kind: str = "plan") -> Artifact:
    return Artifact(scope, artifact_id, kind, CREATED_AT)


def _revision(
    scope: Scope, revision_id: str, *, artifact_id: str = "artifact-1",
    value: str | None = None,
    parents: tuple[ArtifactRevisionRef, ...] = (),
) -> ArtifactRevision:
    return ArtifactRevision(
        scope=scope,
        artifact_id=artifact_id,
        revision_id=revision_id,
        created_at=CREATED_AT,
        created_by=ACTOR,
        payload=InlinePayload.from_value(
            "application/json", "urn:test:artifact", {"value": value or revision_id},
        ),
        parent_revision_refs=parents,
    )


def _key(scope: Scope, request_id: str = "request-1") -> CommandKey:
    return CommandKey(scope.realm_id, "principal-1", request_id)


def _digest(fill: str = "a") -> Digest:
    return Digest("sha256", fill * 64)


def _append(uow, revision: ArtifactRevision, expected_version: int):
    verify_material(revision, uow.engineering.validated_budget())
    return uow.engineering.append_revision(revision, expected_version=expected_version)


def _seed_revision(uow, revision: ArtifactRevision) -> None:
    """Insert a well-formed immutable revision for graph-scale reader tests."""
    raw = encode_revision(revision)
    uow._access.execute(
        "INSERT INTO eng_artifact_revisions "
        "(realm_id, project_id, revision_id, artifact_id, digest, schema_version, canonical_bytes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (revision.scope.realm_id, revision.scope.project_id, revision.revision_id,
         revision.artifact_id, revision.digest.hex, revision.schema_version, raw),
    )
    for parent in revision.parent_revision_refs:
        uow._access.execute(
            "INSERT INTO eng_revision_parents "
            "(realm_id, project_id, artifact_id, revision_id, parent_revision_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (revision.scope.realm_id, revision.scope.project_id, revision.artifact_id,
             revision.revision_id, parent.revision_id),
        )


def test_artifact_fact_and_command_reservation_rollback_together_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "atomic.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)

    # Both repositories share the UoW's one active Library transaction. Exit
    # without explicit commit must roll back both the fact and journal row.
    try:
        with factory.begin(scope, "write") as uow:
            uow.engineering.create(_artifact(scope))
            revision = _revision(scope, "revision-1")
            _append(uow, revision, expected_version=0)
            reservation = uow.commands.reserve(
                _key(scope), project_id=scope.project_id, operation="artifact.create",
                operation_id="operation-1", request_digest=_digest(),
            )
            assert reservation.created is True
    finally:
        library.close()

    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    reopened_factory = SQLiteUoWFactory(reopened)
    with reopened_factory.begin(scope, "read") as uow:
        with pytest.raises(ApplicationError) as missing:
            uow.engineering.get_artifact("artifact-1")
        assert missing.value.code == "NOT_FOUND"
        assert uow.commands.get(_key(scope)) is None
        uow.commit()
    reopened.close()


def test_isolate_rolls_back_business_fact_but_keeps_reservation(tmp_path: Path) -> None:
    path = tmp_path / "isolate.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)

    with factory.begin(scope, "write") as uow:
        reservation = uow.commands.reserve(
            _key(scope), project_id=scope.project_id, operation="artifact.create",
            operation_id="operation-isolated", request_digest=_digest("b"),
        )
        assert reservation.created
        with pytest.raises(ApplicationError) as refused:
            with uow.isolate():
                uow.engineering.create(_artifact(scope, "isolated-artifact"))
                _append(uow, _revision(scope, "isolated-revision", artifact_id="isolated-artifact"), 0)
                raise ApplicationError("BUSINESS_REFUSED")
        assert refused.value.code == "BUSINESS_REFUSED"
        with pytest.raises(ApplicationError) as absent:
            uow.engineering.get_artifact("isolated-artifact")
        assert absent.value.code == "NOT_FOUND"
        assert uow.commands.get(_key(scope)) == reservation.entry
        uow.commit()

    library.close()
    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    factory = SQLiteUoWFactory(reopened)
    with factory.begin(scope, "read") as uow:
        assert uow.commands.get(_key(scope)) == reservation.entry
        with pytest.raises(ApplicationError) as absent:
            uow.engineering.get_artifact("isolated-artifact")
        assert absent.value.code == "NOT_FOUND"
        uow.commit()
    reopened.close()


@pytest.mark.parametrize("failure_point", ["rollback_to", "release_after_success"])
def test_uncertain_isolate_cleanup_poisons_uow_and_forces_full_rollback(
    tmp_path: Path, failure_point: str,
) -> None:
    path = tmp_path / f"poison-{failure_point}.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)
    uow = factory.begin(scope, "write")
    with uow:
        access = uow._access
        original_execute = access.execute

        def injected_execute(sql, parameters=()):
            if failure_point == "rollback_to" and sql == "ROLLBACK TO engineering_mutation":
                raise ApplicationError("SYNTHETIC_ROLLBACK_FAILURE")
            result = original_execute(sql, parameters)
            if failure_point == "release_after_success" and sql == "RELEASE engineering_mutation":
                raise ApplicationError("SYNTHETIC_RELEASE_REPLY_LOST")
            return result

        access.execute = injected_execute
        with pytest.raises(ApplicationError) as uncertain:
            with uow.isolate():
                uow.engineering.create(_artifact(scope, "poisoned-artifact"))
                raise ApplicationError("BUSINESS_REFUSED")
        assert uncertain.value.code == "TRANSACTION_UNCERTAIN"

        # The savepoint outcome is uncertain: repositories are invalidated and
        # an explicit commit must fail closed so the enclosing UoW rolls back.
        with pytest.raises(ApplicationError) as leaked:
            uow.engineering.get_artifact("poisoned-artifact")
        assert leaked.value.code == "UOW_NOT_ACTIVE"
        with pytest.raises(ApplicationError) as commit_error:
            uow.commit()
        assert commit_error.value.code == "TRANSACTION_UNCERTAIN"

    library.close()
    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    reopened_factory = SQLiteUoWFactory(reopened)
    with reopened_factory.begin(scope, "read") as read_uow:
        with pytest.raises(ApplicationError) as absent:
            read_uow.engineering.get_artifact("poisoned-artifact")
        assert absent.value.code == "NOT_FOUND"
        read_uow.commit()
    reopened.close()


def test_reserve_duplicate_returns_original_operation_and_key_reuse_conflicts(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "commands.sqlite")
    scope_a = Scope("realm-1", "project-1")
    scope_b = Scope("realm-1", "project-2")
    key = _key(scope_a, "same-request")

    with factory.begin(scope_a, "write") as uow:
        first = uow.commands.reserve(
            key, project_id=scope_a.project_id, operation="artifact.create",
            operation_id="operation-original", request_digest=_digest("c"),
        )
        assert first.created is True
        uow.commit()

    with factory.begin(scope_a, "write") as uow:
        duplicate = uow.commands.reserve(
            key, project_id=scope_a.project_id, operation="artifact.create",
            operation_id="operation-retry", request_digest=_digest("c"),
        )
        assert duplicate.created is False
        assert duplicate.entry.operation_id == "operation-original"
        result_bytes = canonical_bytes({"artifact_id": "artifact-1", "created": True})
        completed = uow.commands.complete(
            key, expected_version=0, result_bytes=result_bytes,
        )
        assert completed.state == "completed" and completed.version == 1
        assert uow.commands.complete(
            key, expected_version=0, result_bytes=result_bytes,
        ) == completed
        with pytest.raises(ApplicationError) as stale:
            uow.commands.complete(
                key, expected_version=1,
                result_bytes=canonical_bytes({"artifact_id": "changed"}),
            )
        assert stale.value.code == "VERSION_CONFLICT"
        uow.commit()

    conflicting_claims = (
        (scope_b, scope_b.project_id, "artifact.create", _digest("c")),
        (scope_a, scope_a.project_id, "artifact.update", _digest("c")),
        (scope_a, scope_a.project_id, "artifact.create", _digest("d")),
    )
    for selected_scope, project_id, operation, request_digest in conflicting_claims:
        with pytest.raises(ApplicationError) as conflict:
            with factory.begin(selected_scope, "write") as uow:
                uow.commands.reserve(
                    key, project_id=project_id, operation=operation,
                    operation_id="operation-conflicting", request_digest=request_digest,
                )
                uow.commit()
        assert conflict.value.code == "REQUEST_IDENTITY_CONFLICT"

    library.close()


def test_read_only_rejects_both_artifact_and_journal_writes(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "readonly.sqlite")
    scope = Scope("realm-1", "project-1")

    with factory.begin(scope, "read") as uow:
        with pytest.raises(ApplicationError) as artifact_error:
            uow.engineering.create(_artifact(scope))
        assert artifact_error.value.code == "READ_ONLY_UOW"
        with pytest.raises(ApplicationError) as journal_error:
            uow.commands.reserve(
                _key(scope), project_id=scope.project_id, operation="artifact.create",
                operation_id="operation-read-only", request_digest=_digest("e"),
            )
        assert journal_error.value.code == "READ_ONLY_UOW"
        uow.commit()

    library.close()


def test_repository_handles_leaked_after_uow_exit_are_unavailable(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "leak.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope, "write") as uow:
        engineering = uow.engineering
        commands = uow.commands
        uow.commit()

    with pytest.raises(ApplicationError) as artifact_error:
        engineering.get_artifact("artifact-1")
    assert artifact_error.value.code == "UOW_NOT_ACTIVE"
    with pytest.raises(ApplicationError) as command_error:
        commands.get(_key(scope))
    assert command_error.value.code == "UOW_NOT_ACTIVE"
    library.close()


def test_revision_parent_closure_multigeneration_and_head_is_not_adopted(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "parents.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        root_a = _revision(scope, "root-a")
        ref_a = _append(uow, root_a, 0)
        root_b = _revision(scope, "root-b", value="second root")
        ref_b = _append(uow, root_b, 1)

        missing = ArtifactRevisionRef(scope.realm_id, scope.project_id, "artifact-1",
                                     "missing-parent", _digest("f"))
        with pytest.raises(ApplicationError) as absent:
            _append(uow, _revision(scope, "missing-child", parents=(missing,)), 2)
        assert absent.value.code == "NOT_FOUND"

        bad_digest = ArtifactRevisionRef(scope.realm_id, scope.project_id, "artifact-1",
                                         ref_a.revision_id, _digest("0"))
        with pytest.raises(ApplicationError) as wrong:
            _append(uow, _revision(scope, "wrong-digest-child", parents=(bad_digest,)), 2)
        assert wrong.value.code == "RECORD_CORRUPT"

        merge = _revision(scope, "merge", value="merged", parents=(ref_a, ref_b))
        merge_ref = _append(uow, merge, 2)
        leaf = _revision(scope, "leaf", value="multi-generation", parents=(merge_ref,))
        leaf_ref = _append(uow, leaf, 3)
        uow.commit()

    with factory.begin(scope, "read") as uow:
        resolved = uow.engineering.resolve_revision(leaf_ref)
        assert resolved == leaf
        assert resolved.parent_revision_refs == (merge_ref,)
        merge_resolved = uow.engineering.resolve_revision(merge_ref)
        assert merge_resolved.parent_revision_refs == tuple(sorted(
            (ref_a, ref_b), key=lambda ref: (ref.revision_id, ref.digest.hex),
        ))
        artifact = uow.engineering.get_artifact("artifact-1")
        assert artifact.version == 4
        assert artifact.head_revision_id is None
        uow.commit()
    library.close()


def test_two_independent_connections_compare_and_swap_artifact_version(tmp_path: Path) -> None:
    path = tmp_path / "cas.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        root = _revision(scope, "root")
        root_ref = _append(uow, root, 0)
        uow.commit()
    library.close()

    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str | None]] = []
    lock = threading.Lock()

    def contender(revision_id: str) -> None:
        connection = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
        try:
            local_factory = SQLiteUoWFactory(connection)
            revision = _revision(scope, revision_id, parents=(root_ref,))
            barrier.wait(timeout=15)
            try:
                with local_factory.begin(scope, "write") as uow:
                    _append(uow, revision, expected_version=1)
                    uow.commit()
                outcome = ("committed", None)
            except ApplicationError as exc:
                outcome = ("refused", exc.code)
            with lock:
                outcomes.append(outcome)
        finally:
            connection.close()

    workers = [
        threading.Thread(target=contender, args=("cas-a",)),
        threading.Thread(target=contender, args=("cas-b",)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
    assert all(not worker.is_alive() for worker in workers), "CAS writers did not finish"
    assert sorted(outcomes) == [("committed", None), ("refused", "VERSION_CONFLICT")]

    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    local_factory = SQLiteUoWFactory(reopened)
    with local_factory.begin(scope, "read") as uow:
        artifact = uow.engineering.get_artifact("artifact-1")
        assert artifact.version == 2
        assert artifact.head_revision_id is None
        uow.commit()
    reopened.close()


def test_read_set_checks_artifact_version_and_rejects_unimplemented_kinds(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "read-set.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        uow.commit()

    with factory.begin(scope, "read") as uow:
        uow.engineering.check_read_set(ReadSet(scope, (ReadVersion("artifact", "artifact-1", 0),)))
        with pytest.raises(ApplicationError) as changed:
            uow.engineering.check_read_set(ReadSet(scope, (ReadVersion("artifact", "artifact-1", 1),)))
        assert changed.value.code == "READ_SET_CHANGED"
        with pytest.raises(ApplicationError) as unsupported:
            uow.engineering.check_read_set(ReadSet(scope, (ReadVersion("proposal", "proposal-1", 0),)))
        assert unsupported.value.code == "UNSUPPORTED_READ_KIND"
        uow.commit()
    library.close()


def test_commit_success_with_lost_reply_requires_reopen_and_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "commit-lost-reply.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)
    library.close()

    base_connection = library_module._LibraryConnection

    class CommitAppliedButReplyLost(base_connection):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_next_commit_reply", False):
                self.lose_next_commit_reply = False
                self.applied_commit_count = getattr(self, "applied_commit_count", 0) + 1
                raise sqlite3.OperationalError("synthetic lost COMMIT reply")
            return result

    monkeypatch.setattr(library_module, "_LibraryConnection", CommitAppliedButReplyLost)
    uncertain_library = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    uncertain_factory = SQLiteUoWFactory(uncertain_library)
    connection = uncertain_library._connection
    connection.lose_next_commit_reply = True
    uow = uncertain_factory.begin(scope, "write")
    with pytest.raises(ApplicationError) as uncertain:
        with uow:
            uow.engineering.create(_artifact(scope, "committed-before-lost-reply"))
            saved = _revision(scope, "committed-revision", artifact_id="committed-before-lost-reply")
            saved_ref = _append(uow, saved, expected_version=0)
            reservation = uow.commands.reserve(
                _key(scope, "lost-reply-request"), project_id=scope.project_id,
                operation="artifact.create", operation_id="lost-reply-operation",
                request_digest=_digest("b"),
            )
            assert reservation.created is True
            uow.commit()
    assert uncertain.value.code == "COMMIT_UNKNOWN"
    assert connection.applied_commit_count == 1
    assert uncertain_library._closed is True

    # Reopen is the reconciliation boundary: the durable transaction is
    # visible exactly once, and no automatic retry creates another command.
    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    reopened_factory = SQLiteUoWFactory(reopened)
    with reopened_factory.begin(scope, "read") as read_uow:
        artifact = read_uow.engineering.get_artifact("committed-before-lost-reply")
        assert artifact.version == 1
        assert read_uow.engineering.resolve_revision(saved_ref) == saved
        assert read_uow.commands.get(_key(scope, "lost-reply-request")) == reservation.entry
        assert read_uow._access.execute(
            "SELECT count(*) FROM eng_commands WHERE operation_id=?",
            ("lost-reply-operation",),
        ).fetchone() == (1,)
        assert read_uow._access.execute(
            "SELECT count(*) FROM eng_artifact_revisions WHERE revision_id=?",
            ("committed-revision",),
        ).fetchone() == (1,)
        read_uow.commit()
    reopened.close()


def test_explicit_rollback_makes_later_commit_unavailable_and_persists_nothing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rollback-only.sqlite"
    scope = Scope("realm-1", "project-1")
    library, factory = _open(path)
    uow = factory.begin(scope, "write")
    with uow:
        uow.engineering.create(_artifact(scope, "must-rollback"))
        uow.commands.reserve(
            _key(scope, "rollback-only-request"), project_id=scope.project_id,
            operation="artifact.create", operation_id="rollback-only-operation",
            request_digest=_digest("c"),
        )
        assert uow.rollback() is None
        with pytest.raises(ApplicationError) as refused:
            uow.commit()
        assert refused.value.code == "UOW_NOT_ACTIVE"
    library.close()

    reopened = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    reopened_factory = SQLiteUoWFactory(reopened)
    with reopened_factory.begin(scope, "read") as read_uow:
        with pytest.raises(ApplicationError) as absent:
            read_uow.engineering.get_artifact("must-rollback")
        assert absent.value.code == "NOT_FOUND"
        assert read_uow.commands.get(_key(scope, "rollback-only-request")) is None
        read_uow.commit()
    reopened.close()


def test_revision_ancestor_closure_resolves_beyond_python_recursion_depth(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "deep-ancestry.sqlite")
    scope = Scope("realm-1", "project-1")
    depth = 1_105
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        parent = None
        for index in range(depth):
            parents = () if parent is None else (parent.ref,)
            record = _revision(scope, f"deep-{index:04d}", parents=parents)
            _seed_revision(uow, record)
            parent = record
        assert parent is not None
        leaf_ref = parent.ref
        uow.commit()

    with factory.begin(scope, "read") as uow:
        resolved = uow.engineering.resolve_revision(leaf_ref)
        assert resolved.revision_id == f"deep-{depth - 1:04d}"
        assert resolved.parent_revision_refs[0].revision_id == f"deep-{depth - 2:04d}"
        uow.commit()
    library.close()


def test_diamond_closure_rechecks_same_ancestor_id_with_conflicting_digest(
    tmp_path: Path,
) -> None:
    library, factory = _open(tmp_path / "diamond-conflict.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        root = _revision(scope, "shared-root")
        _seed_revision(uow, root)
        fake_root = ArtifactRevisionRef(
            scope.realm_id, scope.project_id, "artifact-1", root.revision_id, _digest("0"),
        )
        left = _revision(scope, "left-branch", parents=(root.ref,))
        right = _revision(scope, "right-branch", parents=(fake_root,))
        _seed_revision(uow, left)
        _seed_revision(uow, right)
        leaf = _revision(scope, "diamond-leaf", parents=(left.ref, right.ref))
        _seed_revision(uow, leaf)

        with pytest.raises(ApplicationError) as corrupt:
            uow.engineering.resolve_revision(leaf.ref)
        assert corrupt.value.code == "RECORD_CORRUPT"
        uow.commit()
    library.close()


def test_artifact_version_i64_exhaustion_is_typed_and_writes_nothing(tmp_path: Path) -> None:
    library, factory = _open(tmp_path / "version-exhaustion.sqlite")
    scope = Scope("realm-1", "project-1")
    max_i64 = (1 << 63) - 1
    with factory.begin(scope, "write") as uow:
        uow.engineering.create(_artifact(scope))
        uow._access.execute(
            "UPDATE eng_artifacts SET version=? WHERE realm_id=? AND project_id=? AND artifact_id=?",
            (max_i64, scope.realm_id, scope.project_id, "artifact-1"),
        )
        with pytest.raises(ApplicationError) as exhausted:
            _append(uow, _revision(scope, "must-not-append"), expected_version=max_i64)
        assert exhausted.value.code == "VERSION_EXHAUSTED"
        assert uow._access.execute(
            "SELECT count(*) FROM eng_artifact_revisions WHERE revision_id=?",
            ("must-not-append",),
        ).fetchone() == (0,)
        assert uow.engineering.get_artifact("artifact-1").version == max_i64
        uow.commit()
    library.close()


def test_read_transaction_is_physically_query_only_and_write_state_restored(tmp_path):
    library, factory = _open(tmp_path / "query-only.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope, "read") as uow:
        assert uow._access.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(ApplicationError) as denied:
            uow._access.execute("INSERT INTO eng_artifacts VALUES (?, ?, ?, ?, ?, NULL, 0)",
                (scope.realm_id, scope.project_id, "accidental-write", "plan", CREATED_AT))
        assert denied.value.code == "STORAGE_UNAVAILABLE"
    assert library._connection.execute("PRAGMA query_only").fetchone() == (0,)
    with factory.begin(scope) as uow:
        uow.engineering.create(_artifact(scope))
        uow.commit()
    library.close()


def test_active_repository_refuses_another_thread_without_losing_owner_transaction(tmp_path):
    library, factory = _open(tmp_path / "thread.sqlite")
    scope = Scope("realm-1", "project-1")
    failures = []
    with factory.begin(scope) as uow:
        uow.engineering.create(_artifact(scope))
        def foreign_read():
            try:
                uow.engineering.get_artifact("artifact-1")
            except ApplicationError as exc:
                failures.append(exc.code)
        thread = threading.Thread(target=foreign_read)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert failures == ["UOW_NOT_ACTIVE"]
        assert uow.engineering.get_artifact("artifact-1").version == 0
        uow.commit()
    library.close()


def test_dense_ancestor_graph_refuses_budget_exhaustion_without_partial_write(tmp_path):
    library, factory = _open(tmp_path / "dense.sqlite")
    scope = Scope("realm-1", "project-1")
    with factory.begin(scope) as uow:
        uow.engineering.create(_artifact(scope))
        records = []
        for index in range(151):
            record = _revision(scope, f"dense-{index:03d}", parents=tuple(r.ref for r in records))
            _seed_revision(uow, record)
            records.append(record)
        uow.commit()
    with factory.begin(scope) as uow:
        with pytest.raises(ApplicationError) as exhausted:
            uow.engineering.resolve_revision(records[-1].ref)
        assert exhausted.value.code == "ANCESTRY_LIMIT"
        with pytest.raises(ApplicationError) as append_refusal:
            _append(uow, _revision(scope, "never-appended", parents=(records[-1].ref,)), 0)
        assert append_refusal.value.code == "ANCESTRY_LIMIT"
        assert uow._access.execute("SELECT count(*) FROM eng_artifact_revisions").fetchone() == (151,)
        assert uow.engineering.get_artifact("artifact-1").version == 0
    library.close()
