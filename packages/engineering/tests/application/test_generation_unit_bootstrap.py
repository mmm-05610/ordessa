"""Work-scoped Unit bootstrap fence on the original command journal.

These tests exercise the persistence boundary with a real schema-17 SQLite
library. The side-effect counter stands for the Unit owner; no Unit, process,
model or external provider is started here.
"""
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import WorkBinding
from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
    DeclaredGenerationDispatch,
)
from ordessa_engineering.application.usecases.queries.works import WorkQueries
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import decode_json


SCOPE = Scope("bootstrap-realm", "bootstrap-project")
WORK_ID = "bootstrap-work"
PROFILE = {"realm_id": SCOPE.realm_id, "project_id": SCOPE.project_id,
           "profile_id": "profile-1", "version": 1}
OWNER_IDENTITY = "sha256:" + "a" * 64
UNIT_REF = {"environmentNamespace": "environment-1", "unitId": "unit-1",
            "ownerProviderRef": {"provider": "local", "owner": "owner-1"},
            "sourceRevision": "revision-1"}


class _Access:
    def __init__(self):
        self.calls = []

    def require(self, context, operation):
        self.calls.append((context, operation))


def _context(*, request_id="request-1", principal_id="principal-1", scope=SCOPE):
    return CommandContext(scope, principal_id, ActorRef("actor-1", "service", "issuer-1"),
                          request_id, "2026-10-15T10:00:00.000000Z", "trace-1")


def _binding(*, work_id=WORK_ID, scope=SCOPE, revision=1):
    return WorkBinding(work_id, scope,
        MethodRef("method-1", "2.7.2", 2, Digest("sha256", "b" * 64)),
        revision, ())


def _dispatch(factory, access=None):
    return DeclaredGenerationDispatch(factory, access or _Access(), blobs=None,
        execution=None, review_admission=None, method_guard=None)


@pytest.fixture
def journal(tmp_path):
    path = (tmp_path / "generation-unit-bootstrap.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="unit-bootstrap-test", schema_version=17)
    try:
        yield path, library, SQLiteUoWFactory(library)
    finally:
        if not library._closed:
            library.close()


def test_pending_bootstrap_commits_before_side_effect_and_fences_every_reentry(journal):
    path, library, factory = journal
    dispatch = _dispatch(factory)
    side_effects = []

    reservation = dispatch.reserve_unit_bootstrap(
        _context(), _binding(), PROFILE, OWNER_IDENTITY)
    assert reservation.created is True
    assert reservation.entry.state == "pending"
    side_effects.append("one-unit-create")

    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
        dispatch.reserve_unit_bootstrap(_context(), _binding(), PROFILE, OWNER_IDENTITY)
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
        dispatch.reserve_unit_bootstrap(
            _context(request_id="request-2"), _binding(), PROFILE, OWNER_IDENTITY)
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
        dispatch.reserve_unit_bootstrap(
            _context(request_id="request-3", principal_id="principal-2"),
            _binding(), PROFILE, OWNER_IDENTITY)
    assert side_effects == ["one-unit-create"]

    library.close()
    reopened = EngineeringLibrary.open(path, library_id="unit-bootstrap-test")
    try:
        reopened_factory = SQLiteUoWFactory(reopened)
        with reopened_factory.begin(SCOPE, "read") as uow:
            entry = uow.commands.find_operation(
                SCOPE, reservation.entry.operation_id,
                operation="engineering.execution.unit-bootstrap")
        assert entry is not None and entry.state == "pending"
        assert entry.key == reservation.entry.key
        with pytest.raises(ApplicationError,
                           match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
            _dispatch(reopened_factory).reserve_unit_bootstrap(
                _context(request_id="request-after-reopen"), _binding(), PROFILE,
                OWNER_IDENTITY)
        assert side_effects == ["one-unit-create"]
    finally:
        reopened.close()


def test_completed_bootstrap_reuses_only_the_exact_pins_and_real_unit_ref(journal):
    _path, library, factory = journal
    dispatch = _dispatch(factory)
    context = _context()
    reservation = dispatch.reserve_unit_bootstrap(context, _binding(), PROFILE, OWNER_IDENTITY)
    created_units = [UNIT_REF]
    dispatch.complete_unit_bootstrap(context, reservation, UNIT_REF)

    reused = dispatch.reserve_unit_bootstrap(context, _binding(), PROFILE, OWNER_IDENTITY)
    assert reused.created is False
    assert decode_json(reused.entry.result_bytes) == {"unit_ref": UNIT_REF}
    assert created_units == [UNIT_REF]

    variants = (
        (_binding(revision=2), PROFILE, OWNER_IDENTITY),
        (_binding(), {**PROFILE, "version": 2}, OWNER_IDENTITY),
        (_binding(), PROFILE, "sha256:" + "c" * 64),
    )
    for binding, profile, identity in variants:
        with pytest.raises(ApplicationError,
                           match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
            dispatch.reserve_unit_bootstrap(context, binding, profile, identity)
    with pytest.raises(ApplicationError,
                       match="WORK_ACTION_GENERATION_UNIT_BINDING_MISMATCH"):
        dispatch.complete_unit_bootstrap(context, reservation,
            {**UNIT_REF, "unitId": "substituted-unit"})
    library.close()


def test_bootstrap_refuses_a_work_from_another_scope_and_work_get_projects_unknown(journal):
    _path, library, factory = journal
    dispatch = _dispatch(factory)
    other_scope = Scope("bootstrap-other-realm", "bootstrap-other-project")
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_UNIT_BINDING_INVALID"):
        dispatch.reserve_unit_bootstrap(_context(), _binding(scope=other_scope), PROFILE,
                                        OWNER_IDENTITY)

    context = _context()
    pending = dispatch.reserve_unit_bootstrap(context, _binding(), PROFILE, OWNER_IDENTITY)
    reader = object.__new__(WorkQueries)
    reader.factory = factory
    assert reader._generation_bootstrap(context, WORK_ID) == {
        "operation_id": pending.entry.operation_id,
        "state": "pending", "request_id": pending.entry.key.request_id,
        "unknown_requires_reconciliation": True, "retry_allowed": False,
    }
    library.close()
