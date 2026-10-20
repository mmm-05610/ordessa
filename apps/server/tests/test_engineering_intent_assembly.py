"""Same-graph wiring for the original Engineering intent admission router."""
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.review_sources import ConfiguredReviewPhase, SQLiteReviewBindings
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.application.assembly import build_submission_acceptance_admission
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_server.composition.engineering_intent_assembly import (
    build_engineering_intent_admission_router,
)


def _graph(tmp_path, suffix):
    library = EngineeringLibrary.create(
        (tmp_path / f"intent-{suffix}.sqlite").resolve(),
        library_id=f"intent-{suffix}", schema_version=15)
    factory = SQLiteUoWFactory(library)
    methods = SQLiteMethodControl(factory, SQLiteSnapshotStore(library))
    bindings = SQLiteReviewBindings(
        factory, methods, scope=Scope("intent-realm", "intent-project"),
        proposal_ref=ProposalRef("intent-realm", "intent-project", "change", "proposal",
            Digest("sha256", "b" * 64)),
        phases=(ConfiguredReviewPhase(
            "selected-intent-phase", ("reviewer",), workflow_node_id="selected-intent-phase"),),
    )
    acceptance = build_submission_acceptance_admission(
        factory, method_control=methods, bindings=bindings)
    return library, factory, methods, bindings, acceptance


def test_router_uses_original_builders_and_same_factory_methods_bindings(tmp_path):
    library, factory, methods, bindings, _acceptance = _graph(tmp_path, "selected")
    try:
        router = build_engineering_intent_admission_router(
            factory, method_control=methods, bindings=bindings)
        assert router.factory is factory
        assert router.methods is methods
        assert callable(router.guard_intent)
    finally:
        library.close()


def test_router_refuses_acceptance_admission_from_foreign_owner_graph(tmp_path):
    first = _graph(tmp_path, "first")
    second = _graph(tmp_path, "second")
    try:
        with pytest.raises(ApplicationError, match="INTENT_ADMISSION_AUTHORITY_MISMATCH"):
            build_engineering_intent_admission_router(
                first[1], method_control=first[2], bindings=first[3],
                acceptance_admission=second[4])
    finally:
        first[0].close()
        second[0].close()
