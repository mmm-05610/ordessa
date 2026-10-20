"""Exact authorship-source correlation on the original Engineering SQLite.

The W10 caller is an authenticated instance service principal. These tests
prove source correlation, not that the principal represents a human.
"""
from dataclasses import asdict
from pathlib import Path
import sys

import pytest

import ordessa_interfaces
_REPO = Path(__file__).resolve().parents[4]
ordessa_interfaces.__path__.append(str(_REPO / "packages/interfaces/system-access/src/ordessa_interfaces"))
sys.path.insert(0, str(_REPO / "packages/interfaces/system-access/bindings/src"))
import ordessa_interfaces.system_access as _system_access
_system_access.__path__.append(str(_REPO / "packages/interfaces/contracts/src/ordessa_interfaces/system_access"))

from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_system_access_bindings import EngineeringCommandAccess

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.review_authorship import (
    ConfiguredMaterialSubmission,
    SQLiteReviewAuthorshipSource,
)
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.review_authorship import ReviewAuthorship
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan,
    ReviewRequirement,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_infrastructure.encoding import canonical_bytes

from test_proposal_usecases import SCOPE, SyntheticAccess, _ctx
from test_reviewer_assignments_schema15 import _TestManagement, _publish_with_identity_constraint


WIRE_SCOPE = WireScope(SCOPE.realm_id, SCOPE.project_id)
TOKEN = "review-authorship-fixture-token"
CREATE = "engineering.artifacts.create"
APPEND = "engineering.artifacts.append_revision"
REVIEW = "engineering.reviews.request"
TIME = "2026-10-12T12:00:00.000000Z"


class _NoSelectedSubmission:
    """This branch fixture explicitly selects material authorship."""
    def __init__(self, factory):
        self.factory = factory

    def resolve_review_submission(self, context, method_ref, phase_key):
        return None


def _plan(method_ref, target_refs):
    targets = TargetSet(tuple(Target("primary" if index == 0 else "support", ref)
                              for index, ref in enumerate(target_refs)))
    keys = tuple(CheckKey(target, "authorship-source-check") for target in targets.targets)
    requirement = ReviewRequirement(
        SCOPE, "authorship-source-requirement", 1, "quality", targets, method_ref,
        CriterionSetRef("authorship-standard", 1, Digest("sha256", "a" * 64)),
        keys, ("reviewer",), "source_review",
    )
    return ReviewPlan("authorship-source-plan", requirement,
        tuple(CheckPolicy(key, True, True) for key in keys), AggregationPolicy(), ("reviewer",))


@pytest.fixture
def env(tmp_path):
    library = EngineeringLibrary.create((tmp_path / "review-authorship.sqlite").resolve(),
        library_id="review-authorship-source-test", schema_version=15)
    try:
        factory = SQLiteUoWFactory(library)
        snapshot, method_ref, store = _publish_with_identity_constraint(library, tmp_path / "method")
        management = MethodUseCases(factory, SyntheticAccess(), store, _TestManagement())
        management.adopt(method_ref, _ctx(), expected_version=0)
        authority = InstanceAccessAuthority(lambda: TOKEN, principal_id="source-instance",
            legacy_principal=None, grants=(AccessGrant(WIRE_SCOPE, (CREATE, APPEND, REVIEW)),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate("Bearer " + TOKEN)
        artifacts = ArtifactUseCases(factory, access)
        control = SQLiteMethodControl(factory, store)

        def execute(operation, request_id, parameters):
            with access.admit(caller, WIRE_SCOPE, operation,
                              request_id=request_id, trace_id="review-authorship-test") as context:
                return artifacts.create(parameters, context) if operation == CREATE else artifacts.append_revision(parameters, context)

        initial = {
            "media_type": "application/json", "schema_id": "urn:test:review-authorship",
            "inline_value": {"source": "formal material submission"},
        }
        created = execute(CREATE, "create-review-material", {
            "kind": "plan", "initial": initial, "method_refs": [asdict(method_ref)],
        })
        assert created.status == "completed"
        first_ref = ArtifactRevisionRef(
            created.result["revision_ref"]["realm_id"], created.result["revision_ref"]["project_id"],
            created.result["revision_ref"]["artifact_id"], created.result["revision_ref"]["revision_id"],
            Digest(**created.result["revision_ref"]["digest"]),
        )
        parent = asdict(first_ref)
        appended = execute(APPEND, "append-review-material", {
            "artifact_id": first_ref.artifact_id, "expected_version": 1,
            "parents": [parent], "payload": initial, "method_refs": [asdict(method_ref)],
        })
        assert appended.status == "completed"
        second_raw = appended.result["revision_ref"]
        second_ref = ArtifactRevisionRef(
            second_raw["realm_id"], second_raw["project_id"], second_raw["artifact_id"],
            second_raw["revision_id"], Digest(**second_raw["digest"]),
        )
        with access.admit(caller, WIRE_SCOPE, REVIEW,
                          request_id="review-source-read", trace_id="review-authorship-test") as review_context:
            yield locals()
    finally:
        library.close()


def test_w10_create_and_append_receipts_bind_exact_revisions_without_claiming_human(env):
    e = env
    material = (
        ConfiguredMaterialSubmission(e["first_ref"],
            CommandKey(SCOPE.realm_id, "source-instance", "create-review-material")),
        ConfiguredMaterialSubmission(e["second_ref"],
            CommandKey(SCOPE.realm_id, "source-instance", "append-review-material")),
    )
    source = SQLiteReviewAuthorshipSource(e["factory"], e["control"],
        review_bindings=_NoSelectedSubmission(e["factory"]), material_submissions=material)
    plan = _plan(e["method_ref"], (e["first_ref"], e["second_ref"]))
    result = source.resolve_authorship(e["review_context"], plan, (e["first_ref"], e["second_ref"]))
    assert result.source_kind == "authenticated_material_submitter"
    assert result.author_unit_ref is None
    assert len(result.material_proofs) == 2
    proofs = {proof.revision_ref: proof for proof in result.material_proofs}
    assert set(proofs) == {e["first_ref"], e["second_ref"]}
    assert proofs[e["first_ref"]].operation == CREATE
    assert proofs[e["second_ref"]].operation == APPEND
    assert all(proof.submitter_principal_id == "source-instance" for proof in proofs.values())
    assert e["review_context"].authenticated_actor.actor_kind == "service"


def test_unconfigured_revision_and_uncompleted_receipt_are_not_authorship(env):
    e = env
    key = CommandKey(SCOPE.realm_id, "source-instance", "unrecorded-review-source")
    source = SQLiteReviewAuthorshipSource(e["factory"], e["control"],
        review_bindings=_NoSelectedSubmission(e["factory"]),
        material_submissions=(ConfiguredMaterialSubmission(e["second_ref"], key),))
    with pytest.raises(ApplicationError) as missing:
        source.resolve_authorship(e["review_context"], _plan(e["method_ref"], (e["second_ref"],)), (e["second_ref"],))
    assert missing.value.code == "REVIEW_AUTHOR_SOURCE_UNAVAILABLE"

    pending_key = CommandKey(SCOPE.realm_id, "source-instance", "pending-review-source")
    with e["factory"].begin(SCOPE) as uow:
        uow.commands.reserve(pending_key, project_id=SCOPE.project_id, operation=CREATE,
            operation_id="pending-review-source-operation", request_digest=Digest("sha256", "c" * 64))
        uow.commit()
    pending_source = SQLiteReviewAuthorshipSource(e["factory"], e["control"],
        review_bindings=_NoSelectedSubmission(e["factory"]),
        material_submissions=(ConfiguredMaterialSubmission(e["second_ref"], pending_key),))
    with pytest.raises(ApplicationError) as pending:
        pending_source.resolve_authorship(e["review_context"],
            _plan(e["method_ref"], (e["second_ref"],)), (e["second_ref"],))
    assert pending.value.code == "REVIEW_AUTHOR_SOURCE_UNAVAILABLE"


def test_receipt_must_name_the_configured_revision_and_matching_principal(env):
    e = env
    wrong_ref_source = SQLiteReviewAuthorshipSource(e["factory"], e["control"],
        review_bindings=_NoSelectedSubmission(e["factory"]),
        material_submissions=(ConfiguredMaterialSubmission(e["first_ref"],
            CommandKey(SCOPE.realm_id, "source-instance", "append-review-material")),))
    with pytest.raises(ApplicationError) as wrong_ref:
        wrong_ref_source.resolve_authorship(e["review_context"],
            _plan(e["method_ref"], (e["first_ref"],)), (e["first_ref"],))
    assert wrong_ref.value.code == "REVIEW_AUTHOR_SOURCE_MISMATCH"

    # Seed a deliberately misattributed completed journal row: it claims the
    # real ref, but its principal differs from the immutable revision actor.
    other_key = CommandKey(SCOPE.realm_id, "other-principal", "misattributed-source")
    from ordessa_infrastructure.encoding import canonical_bytes
    with e["factory"].begin(SCOPE) as uow:
        reservation = uow.commands.reserve(other_key, project_id=SCOPE.project_id,
            operation=APPEND, operation_id="misattributed-source-operation",
            request_digest=Digest("sha256", "d" * 64))
        uow.commands.complete(other_key, expected_version=reservation.entry.version,
            result_bytes=canonical_bytes({"revision_ref": asdict(e["second_ref"])}))
        uow.commit()
    wrong_principal_source = SQLiteReviewAuthorshipSource(e["factory"], e["control"],
        review_bindings=_NoSelectedSubmission(e["factory"]),
        material_submissions=(ConfiguredMaterialSubmission(e["second_ref"], other_key),))
    with pytest.raises(ApplicationError) as wrong_principal:
        wrong_principal_source.resolve_authorship(e["review_context"],
            _plan(e["method_ref"], (e["second_ref"],)), (e["second_ref"],))
    assert wrong_principal.value.code == "REVIEW_AUTHOR_SOURCE_MISMATCH"


def test_human_source_tag_is_not_a_supported_authorship_fact(env):
    e = env
    with pytest.raises(ApplicationError) as unsupported:
        ReviewAuthorship(SCOPE, e["method_ref"], (e["second_ref"],), "human")
    assert unsupported.value.code == "REVIEW_AUTHOR_SOURCE_UNSUPPORTED"


def test_native_authorship_requires_original_submission_and_completed_dispatch(tmp_path):
    from submission_wait_business_fixture import build_submission_wait_fixture

    e = build_submission_wait_fixture(tmp_path)
    try:
        source = SQLiteReviewAuthorshipSource(e["factory"], e["controls"],
            review_bindings=e["bindings"])
        refs = tuple(ref for ref in e["submission"].output_refs
                     if isinstance(ref, ArtifactRevisionRef))
        result = source.resolve_authorship(e["context"], e["plan"], refs)
        assert result.source_kind == "native_unit"
        assert result.material_proofs == ()
        assert result.author_unit_ref["unitId"] == e["submission"].execution_ref.unit_id
        assert result.author_unit_ref["environmentNamespace"] == e["submission"].execution_ref.environment_namespace
        assert e["native"]["synthetic_native_facts"] is True
    finally:
        e["library"].close()

