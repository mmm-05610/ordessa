"""Real SQLite resolution counters for shared proposal/material closures."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.proposal_closure import validate_create

from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.changes.models import Change, ChangeSet, Mutation, Proposal
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.changes.errors import (from_reference_error)
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, BlobPayload
from ordessa_engineering.domain.artifacts.provenance import (ClaimRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy,
    CheckKey,
    CheckPolicy,
    CriterionSetRef,
    Observation,
    ReviewControlExpectation,
    ReviewPlan,
    ReviewRecord,
    ReviewSetExpectation,
    ReviewRequirement,
    ReviewSetKey,
    observations_digest,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, SubjectSelector, TemplateCheck, TemplateTarget,
)
_HELPER_PATH = Path(__file__).parents[1] / "application" / "test_proposal_usecases.py"
_HELPER_SPEC = importlib.util.spec_from_file_location("_proposal_usecase_test_helpers", _HELPER_PATH)
if _HELPER_SPEC is None or _HELPER_SPEC.loader is None:
    raise RuntimeError("proposal use-case test helper could not be loaded")
proposal_fixtures = importlib.util.module_from_spec(_HELPER_SPEC)
sys.modules[_HELPER_SPEC.name] = proposal_fixtures
_HELPER_SPEC.loader.exec_module(proposal_fixtures)


SCOPE = proposal_fixtures.SCOPE
LIBRARY_ID = "test.proposal-resolution"
COUNT = 28


@pytest.fixture
def environment(tmp_path: Path):
    library = EngineeringLibrary.create(
        (tmp_path / "proposal-resolution.sqlite").resolve(),
        library_id=LIBRARY_ID,
        schema_version=7,
    )
    factory = SQLiteUoWFactory(library)
    access = proposal_fixtures.SyntheticAccess()
    method_ref = proposal_fixtures._publish_method(library, tmp_path / "published-method")
    base_ref, proposed_ref, claim = proposal_fixtures._artifact_graph(factory)
    try:
        yield library, factory, access, method_ref, base_ref, proposed_ref, claim
    finally:
        library.close()


def test_repository_consumes_change_set_result_with_actual_persisted_controls(environment):
    _library, factory, access, method_ref, base_ref, proposed_ref, claim = environment
    # Historical v1 records remain readable and controllable, but current
    # ProposalUseCases.create only accepts the external-source schema2 contract.
    ref = _seed_historical_v1(factory, method_ref, base_ref, proposed_ref, claim,
                              proposal_id="change-set-result", change_id="historical-change-set")
    with factory.begin(SCOPE, "read") as uow:
        change_set = uow.proposals.validate_change_set((ref,))
        assert type(change_set) is ChangeSet
        assert change_set.proposal_refs == (ref,)
        assert uow.proposals.get_control(ref).disposition == "available"
        uow.commit()
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.control(ref, expected_version=0, disposition="withdrawn", replacement_ref=None,
            evidence=(Digest("sha256", "e" * 64),), at=proposal_fixtures.CREATED_AT,
            actor=proposal_fixtures.ACTOR, reason="synthetic control for result boundary")
        uow.commit()
    with factory.begin(SCOPE, "read") as uow:
        with pytest.raises(ReferenceError) as caught:
            uow.proposals.validate_change_set((ref,))
        assert caught.value.code == "PROPOSAL_UNAVAILABLE"
        assert from_reference_error(caught.value).code.value == "PROPOSAL_UNAVAILABLE"
        assert uow.proposals.get_control(ref).version == 1
        uow.commit()


class _ResolutionProbe:
    """Count repository SQL and wrap, rather than replace, real byte resolvers."""

    def __init__(self, library, monkeypatch):
        from ordessa_engineering.adapters.persistence.sqlite import (
            material_validation,
            snapshot_store,
        )

        self.library = library
        self.sql = []
        self.snapshot_loads = 0
        self.snapshot_blob_reads = 0
        self._read_bytes = snapshot_store.read_bytes
        original_budget_load = material_validation.load_snapshot

        def load_snapshot(*args, **kwargs):
            self.snapshot_loads += 1
            return original_budget_load(*args, **kwargs)

        def read_bytes(*args, **kwargs):
            self.snapshot_blob_reads += 1
            return self._read_bytes(*args, **kwargs)

        monkeypatch.setattr(material_validation, "load_snapshot", load_snapshot)
        monkeypatch.setattr(snapshot_store, "read_bytes", read_bytes)
        library._connection.set_trace_callback(self.sql.append)

    def reset(self):
        self.sql.clear()
        self.snapshot_loads = 0
        self.snapshot_blob_reads = 0

    def selects_from(self, table):
        needle = f"FROM {table}".upper()
        return sum(statement.lstrip().upper().startswith("SELECT") and needle in statement.upper()
                   for statement in self.sql)


def _create_from_draft(factory, access, method_ref, base_ref, proposed_ref, claim, *, request_id, template=False,
                       extra_templates=()):
    # This fixture seeds immutable historical schema1 rows directly through the
    # original repository/UoW. It deliberately does not exercise the retired v1
    # application writer or create a command-journal entry.
    templates = tuple(extra_templates)
    if template:
        templates = (proposal_fixtures._template(method_ref), *templates)
    return _seed_historical_v1(factory, method_ref, base_ref, proposed_ref, claim,
                               proposal_id=f"historical-{request_id}",
                               change_id=f"historical-change-{request_id}", templates=templates)


def _self_template(method_ref, index):
    target = TemplateTarget("primary", SubjectSelector("self_proposal"))
    return ReviewRequirementTemplate(
        SCOPE, f"resolution-self-{index}", 1, "quality", (target,), method_ref,
        CriterionSetRef("resolution-criteria", 1, Digest("sha256", "b" * 64)),
        (TemplateCheck(target, f"self-check-{index}"),), ("reviewer",), f"resolution-phase-{index}",
    )


def _assert_single_actual_material_resolution(probe, proposal_count):
    # Each Proposal row and mutation index is fetched once per distinct exact
    # ProposalRef. Shared method refs resolve through the real SQLite snapshot
    # loader and real blob reads only once within the MaterialBudget.
    assert probe.selects_from("eng_proposals") == proposal_count
    assert probe.selects_from("eng_proposal_mutations") == proposal_count
    assert probe.snapshot_loads == 1
    assert probe.snapshot_blob_reads == 2  # one captured manifest and one workflow resource


def test_many_self_templates_share_one_real_sqlite_proposal_method_and_source_resolution(
    environment, monkeypatch,
):
    library, factory, access, method_ref, base_ref, proposed_ref, claim = environment
    templates = tuple(_self_template(method_ref, index) for index in range(COUNT))
    ref = _create_from_draft(factory, access, method_ref, base_ref, proposed_ref, claim,
                             request_id="many-self-templates", extra_templates=templates)
    probe = _ResolutionProbe(library, monkeypatch)
    probe.reset()
    # Historical-v1 closure reads use the same original repository budget; this
    # assertion is about persisted-record resolution, not current proposal creation.
    with factory.begin(SCOPE, "read") as uow:
        probe.reset()
        resolved = uow.proposals.get_proposal(ref)
        assert len(resolved.review_requirement_templates) == COUNT
        _assert_single_actual_material_resolution(probe, 1)
        uow.commit()


def test_dense_supersedes_closure_reads_each_persisted_proposal_and_index_once(environment, monkeypatch):
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    proposal_count = 36
    mutation = Mutation("artifact-1", "revise", base_ref, proposed_ref)
    claim_ref = ClaimRef(base_ref, "claim-1", claim.statement_digest)
    references = []
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "dense-change", proposal_fixtures.CREATED_AT))
        for index in range(proposal_count):
            record = Proposal(
                SCOPE, f"dense-proposal-{index:02d}", proposal_fixtures.CREATED_AT,
                proposal_fixtures.ACTOR, "dense-change", "dense closure", "synthetic complete DAG",
                (mutation,), (), (claim_ref,), (), method_ref, (), None,
                tuple(references),
            )
            budget=uow.proposals.validated_budget()
            requirements=validate_create(record, uow.proposals, budget)
            references.append(uow.proposals.create_proposal(record, expected_version=index, budget=budget, requirements=requirements))
        uow.commit()

    probe = _ResolutionProbe(library, monkeypatch)
    with factory.begin(SCOPE, "read") as uow:
        probe.reset()
        leaf = uow.proposals.get_proposal(references[-1])
        assert leaf.ref == references[-1]
        _assert_single_actual_material_resolution(probe, proposal_count)
        uow.commit()


def _unvalidated_proposal(proposal_id, change_id, *, method_ref, base_ref, proposed_ref, claim, description="no closure", templates=()):
    mutation = Mutation("artifact-1", "revise", base_ref, proposed_ref)
    claim_ref = ClaimRef(base_ref, "claim-1", claim.statement_digest)
    return Proposal(
        SCOPE, proposal_id, proposal_fixtures.CREATED_AT, proposal_fixtures.ACTOR, change_id,
        "t", description, (mutation,), (), (claim_ref,), (), method_ref, templates, None, (),
    )


def _seed_historical_v1(factory, method_ref, base_ref, proposed_ref, claim, *,
                        proposal_id, change_id, templates=()):
    """Seed an explicitly historical schema1 Proposal for read/control tests."""
    record = _unvalidated_proposal(proposal_id, change_id, method_ref=method_ref,
                                   base_ref=base_ref, proposed_ref=proposed_ref,
                                   claim=claim, templates=templates)
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, change_id, proposal_fixtures.CREATED_AT))
        budget = uow.proposals.validated_budget()
        requirements = validate_create(record, uow.proposals, budget)
        ref = uow.proposals.create_proposal(record, expected_version=0,
                                            budget=budget, requirements=requirements)
        uow.commit()
    return ref


def test_proposal_create_requires_application_triggered_validation(environment):
    """Counter-example: the write primitive refuses an unvalidated create.

    The create-time business validation trigger lives in the application
    (``proposal_closure.validate_create`` on a per-operation budget);
    ``create_proposal`` accepts only a budget that carries the matching marker.
    """
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "unvalidated-change", proposal_fixtures.CREATED_AT))
        record = _unvalidated_proposal("unvalidated-proposal", "unvalidated-change",
                                       method_ref=method_ref, base_ref=base_ref,
                                       proposed_ref=proposed_ref, claim=claim)
        budget = uow.proposals.validated_budget()
        with pytest.raises(ApplicationError) as refused:
            uow.proposals.create_proposal(record, expected_version=0, budget=budget, requirements=())
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"


def test_proposal_marker_cannot_cross_uow(environment):
    """Counter-example: a marker validated in one UoW is refused in another."""
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    record = _unvalidated_proposal("cross-uow-proposal", "cross-uow-change",
                                   method_ref=method_ref, base_ref=base_ref,
                                   proposed_ref=proposed_ref, claim=claim)
    with factory.begin(SCOPE, "write") as first:
        first.proposals.create_change(Change(SCOPE, "cross-uow-change", proposal_fixtures.CREATED_AT))
        budget = first.proposals.validated_budget()
        validate_create(record, first.proposals, budget)
        first.commit()
    with factory.begin(SCOPE, "write") as second:
        with pytest.raises(ApplicationError) as refused:
            second.proposals.create_proposal(record, expected_version=0, budget=budget, requirements=())
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"


def test_proposal_marker_binds_canonical_content_not_only_the_id(environment):
    """Counter-example: same id + changed content no longer matches the marker."""
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "content-change", proposal_fixtures.CREATED_AT))
        first = _unvalidated_proposal("content-proposal", "content-change",
                                      method_ref=method_ref, base_ref=base_ref,
                                      proposed_ref=proposed_ref, claim=claim, description="first")
        budget = uow.proposals.validated_budget()
        validate_create(first, uow.proposals, budget)
        changed = _unvalidated_proposal("content-proposal", "content-change",
                                        method_ref=method_ref, base_ref=base_ref,
                                        proposed_ref=proposed_ref, claim=claim, description="changed")
        with pytest.raises(ApplicationError) as refused:
            uow.proposals.create_proposal(changed, expected_version=0, budget=budget, requirements=())
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"
        # The validated record itself still creates on the same budget.
        uow.proposals.create_proposal(first, expected_version=0, budget=budget, requirements=())
        uow.commit()


def test_same_uow_operations_need_independent_budgets(environment):
    """Counter-example: one UoW, two operations, one budget each."""
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "multi-change", proposal_fixtures.CREATED_AT))
        first = _unvalidated_proposal("multi-proposal-1", "multi-change",
                                      method_ref=method_ref, base_ref=base_ref,
                                      proposed_ref=proposed_ref, claim=claim)
        second = _unvalidated_proposal("multi-proposal-2", "multi-change",
                                       method_ref=method_ref, base_ref=base_ref,
                                       proposed_ref=proposed_ref, claim=claim)
        budget_first = uow.proposals.validated_budget()
        requirements = validate_create(first, uow.proposals, budget_first)
        uow.proposals.create_proposal(first, expected_version=0, budget=budget_first, requirements=requirements)
        # budget_first is bound to `first` only; the second operation needs its own.
        with pytest.raises(ApplicationError) as refused:
            uow.proposals.create_proposal(second, expected_version=1, budget=budget_first, requirements=())
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"
        budget_second = uow.proposals.validated_budget()
        requirements = validate_create(second, uow.proposals, budget_second)
        uow.proposals.create_proposal(second, expected_version=1, budget=budget_second, requirements=requirements)
        uow.commit()


def test_proposal_write_refuses_replaced_requirements(environment):
    """Counter-example: a substituted requirements value is refused.

    The validated requirements are bound to the proposal-content key on the
    per-operation budget; the write consumes only that bound result, so a caller
    cannot inject a different value to bypass review requirements.
    """
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    template = _self_template(method_ref, 91)
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "replaced-req-change", proposal_fixtures.CREATED_AT))
        record = _unvalidated_proposal("replaced-req-proposal", "replaced-req-change",
                                       method_ref=method_ref, base_ref=base_ref,
                                       proposed_ref=proposed_ref, claim=claim, templates=(template,))
        budget = uow.proposals.validated_budget()
        requirements = validate_create(record, uow.proposals, budget)
        assert requirements, "the validated result must carry the review requirement"
        with pytest.raises(ApplicationError) as refused:
            uow.proposals.create_proposal(record, expected_version=0, budget=budget,
                                          requirements=(object(),))
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"
        # The exact validated result is accepted (normal path).
        uow.proposals.create_proposal(record, expected_version=0, budget=budget,
                                      requirements=requirements)
        uow.commit()


def test_proposal_write_refuses_emptied_requirements(environment):
    """Counter-example: emptying the requirements cannot drop review creation."""
    library, factory, _access, method_ref, base_ref, proposed_ref, claim = environment
    template = _self_template(method_ref, 92)
    with factory.begin(SCOPE, "write") as uow:
        uow.proposals.create_change(Change(SCOPE, "emptied-req-change", proposal_fixtures.CREATED_AT))
        record = _unvalidated_proposal("emptied-req-proposal", "emptied-req-change",
                                       method_ref=method_ref, base_ref=base_ref,
                                       proposed_ref=proposed_ref, claim=claim, templates=(template,))
        budget = uow.proposals.validated_budget()
        requirements = validate_create(record, uow.proposals, budget)
        assert requirements
        with pytest.raises(ApplicationError) as refused:
            uow.proposals.create_proposal(record, expected_version=0, budget=budget, requirements=())
        assert refused.value.code == "PROPOSAL_VALIDATION_REQUIRED"
        uow.commit()


def _proposal_review_records(uow, proposal_ref, method_ref, count):
    target = Target("primary", proposal_ref)
    key = CheckKey(target, "proposal-review-check")
    requirement = ReviewRequirement(
        SCOPE, "proposal-target-requirement", 1, "quality", TargetSet((target,)), method_ref,
        CriterionSetRef("proposal-target-criteria", 1, Digest("sha256", "c" * 64)),
        (key,), ("reviewer",), "proposal-target-phase",
    )
    set_key = uow.reviews.ensure_requirement(requirement)
    records = []
    for index in range(count):
        review_id = f"proposal-target-review-{index}"
        plan = ReviewPlan(review_id, requirement, (CheckPolicy(key, True, True),),
                          AggregationPolicy(), ("reviewer",))
        request = uow.reviews.create_plan(plan)
        observations = (Observation(key, "pass", (), "synthetic structured observation"),)
        evidence = VerifiedReviewerEvidence(
            SCOPE, proposal_fixtures.ACTOR, ("reviewer",), "synthetic-verifier", "1", 1,
            plan.request_digest, Digest("sha256", hashlib.sha256(review_id.encode()).hexdigest()),
            observations_digest(observations), Digest("sha256", "e" * 64),
        )
        record = ReviewRecord(
            RecordIdentity(SCOPE, review_id, proposal_fixtures.CREATED_AT, proposal_fixtures.ACTOR),
            plan, evidence, observations,
        )
        uow.reviews.insert_review(record, expected_request_version=request.version, fence=request.fence)
        records.append(record)
    return set_key, tuple(records)


def test_review_readset_expectations_and_control_group_share_proposal_target_budget(environment, monkeypatch):
    library, factory, access, method_ref, base_ref, proposed_ref, claim = environment
    proposal_ref = _create_from_draft(factory, access, method_ref, base_ref, proposed_ref, claim,
                                      request_id="proposal-for-reviews")
    review_count = 7
    with factory.begin(SCOPE, "write") as uow:
        set_key, records = _proposal_review_records(uow, proposal_ref, method_ref, review_count)
        uow.commit()

    set_expectation = ReviewSetExpectation(set_key, review_count)
    control_expectations = tuple(ReviewControlExpectation(record.ref, 0) for record in records)
    probe = _ResolutionProbe(library, monkeypatch)

    with factory.begin(SCOPE, "read") as uow:
        probe.reset()
        snapshot = uow.reviews.read_set(set_key)
        assert len(snapshot.reviews) == review_count
        _assert_single_actual_material_resolution(probe, 1)
        uow.commit()

    with factory.begin(SCOPE, "read") as uow:
        probe.reset()
        uow.reviews.check_expectations((set_expectation,), control_expectations)
        _assert_single_actual_material_resolution(probe, 1)
        uow.commit()

    with factory.begin(SCOPE, "write") as uow:
        probe.reset()
        changed = uow.reviews.control_group(
            control_expectations, state="voided", reason="synthetic bounded control test",
            evidence=(Digest("sha256", "f" * 64),),
        )
        assert len(changed.reviews) == review_count
        assert all(item.control.state == "voided" for item in changed.reviews)
        _assert_single_actual_material_resolution(probe, 1)
        uow.commit()


def test_replacement_control_combines_two_real_evidence_closures_under_one_budget_and_rolls_back(
    environment,
):
    library, factory, access, method_ref, base_ref, proposed_ref, claim = environment
    proposal_ref = _create_from_draft(factory, access, method_ref, base_ref, proposed_ref, claim,
                                      request_id="proposal-for-large-review-replacement")
    evidence_per_review = 17
    raw_bytes = 2 * 1024 * 1024
    blob_store = SQLiteBlobStore(library)
    blob_refs = {"old": [], "replacement": []}
    for group_index, group in enumerate(("old", "replacement")):
        for index in range(evidence_per_review):
            marker = bytes((group_index, index))
            raw = marker + b"x" * (raw_bytes - len(marker))
            digest = Digest("sha256", hashlib.sha256(raw).hexdigest())
            blob_refs[group].append(blob_store.put_verified(raw, digest, "application/octet-stream"))

    evidence_revision_refs = {"old": [], "replacement": []}
    with factory.begin(SCOPE, "write") as uow:
        for group in ("old", "replacement"):
            for index, blob_ref in enumerate(blob_refs[group]):
                artifact_id = f"{group}-review-evidence-{index:02d}"
                uow.engineering.create(Artifact(SCOPE, artifact_id, "evidence", proposal_fixtures.CREATED_AT))
                revision = ArtifactRevision(
                    SCOPE, artifact_id, artifact_id+":revision", proposal_fixtures.CREATED_AT,
                    proposal_fixtures.ACTOR,
                    BlobPayload("application/octet-stream", "synthetic-review-evidence/1", blob_ref),
                    schema_version=2,
                )
                verify_material(revision, uow.engineering.validated_budget())
                evidence_revision_refs[group].append(
                    uow.engineering.append_revision(revision, expected_version=0),
                )

        target = Target("primary", proposal_ref)
        check = CheckKey(target, "large-review-evidence-check")
        requirement = ReviewRequirement(
            SCOPE, "large-review-evidence-requirement", 1, "quality", TargetSet((target,)), method_ref,
            CriterionSetRef("large-review-evidence-criteria", 1, Digest("sha256", "c" * 64)),
            (check,), ("reviewer",), "large-evidence-control-phase",
        )
        uow.reviews.ensure_requirement(requirement)
        records = {}
        for group in ("old", "replacement"):
            review_id = f"large-evidence-{group}"
            plan = ReviewPlan(
                review_id, requirement, (CheckPolicy(check, True, True),),
                AggregationPolicy(), ("reviewer",),
            )
            request = uow.reviews.create_plan(plan)
            observations = (Observation(
                check, "pass", tuple(evidence_revision_refs[group]),
                "synthetic structured pass with captured evidence references",
            ),)
            evidence = VerifiedReviewerEvidence(
                SCOPE, proposal_fixtures.ACTOR, ("reviewer",), "synthetic-large-evidence-verifier", "1", 1,
                plan.request_digest, Digest("sha256", hashlib.sha256(review_id.encode()).hexdigest()),
                observations_digest(observations), Digest("sha256", "e" * 64),
            )
            record = ReviewRecord(
                RecordIdentity(SCOPE, review_id, proposal_fixtures.CREATED_AT, proposal_fixtures.ACTOR),
                plan, evidence, observations,
            )
            uow.reviews.insert_review(record, expected_request_version=request.version, fence=request.fence)
            records[group] = record
        uow.commit()

    # Each immutable response closure is 34 MiB and must remain readable alone.
    for group in ("old", "replacement"):
        with factory.begin(SCOPE, "read") as uow:
            resolved = uow.reviews.get_review(records[group].ref)
            assert resolved.record == records[group]
            uow.commit()

    expected = (ReviewControlExpectation(records["old"].ref, 0),)
    replacement_ref = records["replacement"].ref
    set_key = ReviewSetKey.for_requirement(records["old"].plan.requirement)
    review_ids = (records["old"].plan.review_id, records["replacement"].plan.review_id)
    placeholders = ",".join("?" for _ in review_ids)
    with factory.begin(SCOPE, "write") as uow:
        prefix = (SCOPE.realm_id, SCOPE.project_id)
        before_controls = tuple(uow._access.execute(
            f"SELECT review_id,state,version,canonical_bytes FROM eng_review_controls "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id",
            prefix + review_ids,
        ).fetchall())
        before_events = tuple(uow._access.execute(
            f"SELECT review_id,version,canonical_bytes FROM eng_review_control_events "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id,version",
            prefix + review_ids,
        ).fetchall())
        before_set_version = uow._access.execute(
            "SELECT set_version FROM eng_review_sets WHERE realm_id=? AND project_id=? AND set_digest=?",
            prefix + (set_key.digest.hex,),
        ).fetchone()
        assert before_set_version == (2,)

        with pytest.raises(ApplicationError) as refused:
            with uow.isolate():
                uow.reviews.control_group(
                    expected, state="replaced", reason="synthetic combined-budget refusal",
                    evidence=(Digest("sha256", "f" * 64),), replacement_ref=replacement_ref,
                )
        assert refused.value.code == "MATERIAL_LIMIT"

        after_controls = tuple(uow._access.execute(
            f"SELECT review_id,state,version,canonical_bytes FROM eng_review_controls "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id",
            prefix + review_ids,
        ).fetchall())
        after_events = tuple(uow._access.execute(
            f"SELECT review_id,version,canonical_bytes FROM eng_review_control_events "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id,version",
            prefix + review_ids,
        ).fetchall())
        after_set_version = uow._access.execute(
            "SELECT set_version FROM eng_review_sets WHERE realm_id=? AND project_id=? AND set_digest=?",
            prefix + (set_key.digest.hex,),
        ).fetchone()
        assert after_controls == before_controls
        assert after_events == before_events
        assert after_set_version == before_set_version
        uow.commit()


    # The application must persist a finite business refusal and replay it
    # without acquiring the authority guard again or changing review controls.
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases

    class SyntheticReviewControl:
        calls = 0

        @contextmanager
        def guard_control(self, context, expectations, **parameters):
            assert not library._connection.in_transaction
            self.calls += 1
            yield (Digest("sha256", "f" * 64),)
            assert not library._connection.in_transaction

    guard = SyntheticReviewControl()
    application = ReviewUseCases(factory, access, None, control=guard)
    context = proposal_fixtures._ctx(request_id="combined-review-budget-refusal")
    arguments = dict(state="replaced", reason="synthetic combined-budget refusal",
                     replacement_ref=replacement_ref)
    rejected = application.control_reviews(expected, context, **arguments)
    assert rejected.status == "rejected"
    assert rejected.result == {"code": "MATERIAL_LIMIT"}
    assert application.control_reviews(expected, context, **arguments) == rejected
    assert application.get_command(context) == rejected
    assert guard.calls == 1
    with factory.begin(SCOPE, "read") as uow:
        entry = uow.commands.get(context.key)
        assert entry.state == "rejected" and entry.result_bytes == rejected.result_bytes
        assert tuple(uow._access.execute(
            f"SELECT review_id,state,version,canonical_bytes FROM eng_review_controls "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id",
            prefix + review_ids,
        ).fetchall()) == before_controls
        assert tuple(uow._access.execute(
            f"SELECT review_id,version,canonical_bytes FROM eng_review_control_events "
            f"WHERE realm_id=? AND project_id=? AND review_id IN ({placeholders}) ORDER BY review_id,version",
            prefix + review_ids,
        ).fetchall()) == before_events
        assert uow._access.execute(
            "SELECT set_version FROM eng_review_sets WHERE realm_id=? AND project_id=? AND set_digest=?",
            prefix + (set_key.digest.hex,),
        ).fetchone() == before_set_version
        uow.commit()
