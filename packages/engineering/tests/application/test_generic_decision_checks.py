"""Generic Decision adapter boundary tests.

The UnitRecords, binding resolver, and reviewer authority are synthetic test
doubles from ``test_unit_review_source``. They establish association and guard
behavior only; they do not represent a production reviewer or native model.
"""
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_unit_review_source import _source
from test_method_control_admission import env
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import (
    CheckSourceAdmission, FrozenCheckRequest,
)
from ordessa_engineering.application.orchestration.decision_checks import (
    GenericDecisionCheckSource,
)
from ordessa_engineering.methods.definitions.models.identity import ResourceRef


def _adapter(env, monkeypatch):
    source, ctx, plan, _request, standard, raw, owner = _source(env)
    question_ref = ResourceRef("decision.questions", "a" * 64, "decision")
    source.bindings.binding = replace(source.bindings.binding,
        decision_question_refs=(question_ref,),decision_input_slots=('fixed-delivery',))
    binding=source.bindings.binding
    captured = SimpleNamespace(blob_ref=raw, query_digest="sha256:" + "f" * 64)
    answers = tuple(source.bindings.decode_response(binding, {"answers": []},
        plan=plan, standard=standard))

    # The shared UnitReviewCheckSource's source bytes and reviewer authority
    # are covered in its own tests. This adapter test substitutes only the
    # capture boundary because the base method fixture has no Decision resource.
    def capture(_context, plan, _request, _standard, _snapshot, _raw):
        binding = source.bindings.binding
        answers = tuple(source.bindings.decode_response(binding, {"answers": []},
            plan=plan, standard=_standard))
        return binding, captured, answers

    monkeypatch.setattr(source, "_capture", capture)
    def pinned_questions(_snapshot, plan, _standard, keys):
        if (type(keys) is not tuple or not keys or len(set(keys)) != len(keys)
                or not set(keys) <= set(plan.check_keys)):
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        return (question_ref,)

    monkeypatch.setattr(GenericDecisionCheckSource, "_questions",
        staticmethod(pinned_questions))
    monkeypatch.setattr(GenericDecisionCheckSource,'_input_slots',
        staticmethod(lambda snapshot,refs:('fixed-delivery',)))
    return (GenericDecisionCheckSource(source), source, ctx, plan, standard,
            raw, owner, binding, question_ref)


def test_missing_source_or_reviewer_authority_refuses(env):
    source, *_ = _source(env, authority=False)
    with pytest.raises(ApplicationError, match="DECISION_SOURCE_AUTHORITY_UNAVAILABLE"):
        GenericDecisionCheckSource(source)


def test_verification_requires_exact_question_refs_and_subset_of_full_plan(env, monkeypatch):
    adapter, source, ctx, plan, standard, raw, _owner, binding, question_ref = _adapter(env, monkeypatch)
    frozen = FrozenCheckRequest(plan.plan_digest, 1, 1)
    subset = (plan.check_keys[0],)

    source.bindings.binding = replace(binding, decision_question_refs=())
    with pytest.raises(ApplicationError, match="DECISION_QUESTION_BINDING_UNAVAILABLE"):
        adapter.verify_checks(ctx, plan, frozen, raw, standard=standard, check_keys=subset)

    source.bindings.binding = replace(binding, decision_input_slots=('unrelated-slot',))
    with pytest.raises(ApplicationError, match="DECISION_INPUT_BINDING_UNAVAILABLE"):
        adapter.verify_checks(ctx, plan, frozen, raw, standard=standard, check_keys=subset)

    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_INVALID"):
        adapter.verify_checks(ctx, plan, frozen, raw, standard=standard,
                              check_keys=(object(),))


def test_full_native_proof_is_preserved_while_only_selected_answers_are_returned(env, monkeypatch):
    adapter, source, ctx, plan, standard, raw, owner, _binding, _question_ref = _adapter(env, monkeypatch)
    frozen = FrozenCheckRequest(plan.plan_digest, 1, 1)
    subset = (plan.check_keys[0],)
    observed = []
    # Keep the test's source boundary stub while recording its full-plan input.
    binding = source.bindings.binding
    captured = SimpleNamespace(blob_ref=raw, query_digest="sha256:" + "f" * 64)
    answers = tuple(source.bindings.decode_response(binding, {"answers": []},
        plan=plan, standard=standard))
    source._capture = lambda context, captured_plan, request, *args, **kwargs: (
        observed.append((captured_plan, request, (request.version,request.fence))) or (binding, captured, answers))

    result = adapter.verify_checks(ctx, plan, frozen, raw, standard=standard, check_keys=subset)
    assert tuple(answer.check_key for answer in result.answers) == subset
    assert observed and observed[0][0] == plan
    assert observed[0][0].check_keys == plan.check_keys
    assert observed[0][2] == (frozen.request_version,frozen.fence)
    assert result.provenance_digest
    assert not owner.held


def test_guard_reverifies_same_full_proof_and_rejects_revocation_or_changed_raw(env, monkeypatch):
    adapter, source, ctx, plan, standard, raw, owner, binding, _question_ref = _adapter(env, monkeypatch)
    frozen = FrozenCheckRequest(plan.plan_digest, 1, 1)
    subset = (plan.check_keys[0],)
    response = adapter.verify_checks(ctx, plan, frozen, raw, standard=standard, check_keys=subset)
    admission = CheckSourceAdmission(plan, frozen, raw, subset, response)

    with adapter.guard_checks(ctx, (admission,)):
        assert owner.held
    assert not owner.held

    owner.revoked = True
    with pytest.raises(ApplicationError, match="UNIT_REVIEWER_REVOKED"):
        with adapter.guard_checks(ctx, (admission,)):
            pass
    owner.revoked = False

    import hashlib
    from ordessa_engineering.domain.common.models.values import Digest
    changed_bytes = b"changed"
    changed_raw = source.blobs.put_verified(changed_bytes, Digest(
        "sha256", hashlib.sha256(changed_bytes).hexdigest()), "text/plain")
    changed = replace(admission, raw_response_ref=changed_raw)
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_PROOF_CHANGED"):
        with adapter.guard_checks(ctx, (changed,)):
            pass


def test_frozen_request_must_correlate_to_unchanged_full_plan(env, monkeypatch):
    adapter, _source, ctx, plan, standard, raw, _owner, _binding, _ref = _adapter(env, monkeypatch)
    frozen = FrozenCheckRequest(plan.plan_digest.__class__("sha256", "0" * 64), 1, 1)
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_INVALID"):
        adapter.verify_checks(ctx, plan, frozen, raw, standard=standard,
                              check_keys=(plan.check_keys[0],))


def _compile_candidate():
    """Compile the checked-in candidate against actual detached descriptors only."""
    from ordessa_engineering.application.api.service import EngineeringService
    from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
    from ordessa_engineering.application.orchestration.check_capabilities import (
        invariant_review_check_capabilities, mechanical_review_check_capabilities,
    )
    from ordessa_engineering.application.orchestration.decision_checks import generic_decision_check_capability
    from ordessa_engineering.methods import compile_method, load_method
    from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

    root = Path(__file__).resolve().parents[4] / "methods/incremental-engineering/candidates/2.6.0"
    dispatch = next(item for item in owner_capabilities()
                    if item.capability_id == "engineering.executions.dispatch")
    descriptors = (
        *EngineeringService.operation_capabilities().capabilities,
        dispatch,
        *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities,
        generic_decision_check_capability(),
    )
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    # Detached descriptors only let the test exercise the real compiler shape;
    # they are not registered host authority or a production catalog.
    capabilities = CompilationCapabilities(tuple(descriptors), trust_class="fixture")
    compiled = compile_method(loaded.value, capabilities, "test.generic-decision/1")
    assert compiled.ok, compiled.error
    # This is in-memory compile evidence only. No SnapshotStore/publication or
    # production registry is created by this helper.
    return compiled.value.program


def test_compiled_candidate_question_resource_and_criterion_links_are_exact(env):
    from ordessa_engineering.domain.reviews.models import CheckKey

    program = _compile_candidate()
    standard = next(item for item in program.standard_definitions
                    if item.standard_id == "acceptance")
    criterion = next(item for item in standard.criteria if item.criterion_id == "output_scope")
    plan, *_ = _source(env)[2:]
    key = CheckKey(plan.check_keys[0].target, "output_scope")
    questions = GenericDecisionCheckSource._questions(
        SimpleNamespace(program=program), SimpleNamespace(check_keys=(key,)), standard, (key,))
    expected = next(item.resource_ref for item in program.decision_definitions
                     if item.question_set_id == "output-scope")
    assert questions == (expected,)
    required_slots = GenericDecisionCheckSource._input_slots(SimpleNamespace(program=program), questions)
    assert required_slots == (
        "submission_ref", "fixed_delivery_refs", "executor_report", "independent_review_observations")
    source_standard = next(item for item in program.standard_definitions
                           if item.standard_id == "source-review")
    source_criterion = next(item for item in source_standard.criteria
                            if item.criterion_id == "claim_support")
    source_key = CheckKey(key.target, "claim_support")
    source_questions = GenericDecisionCheckSource._questions(
        SimpleNamespace(program=program), SimpleNamespace(check_keys=(source_key,)),
        source_standard, (source_key,))
    source_slots = GenericDecisionCheckSource._input_slots(
        SimpleNamespace(program=program), source_questions)
    assert source_slots == ("claim", "captured_sources", "counter_sources", "resolved_criterion")
    # Question input names are explicit method aliases; they intentionally
    # differ from Criterion.required_inputs and must not be inferred from them.
    assert set(source_slots) != set(source_criterion.required_inputs or ())


def test_compiled_candidate_rejects_wrong_question_resource_and_criterion_link(env):
    from ordessa_engineering.domain.reviews.models import CheckKey

    program = _compile_candidate()
    standard = next(item for item in program.standard_definitions
                    if item.standard_id == "acceptance")
    plan, *_ = _source(env)[2:]
    key = CheckKey(plan.check_keys[0].target, "output_scope")
    criterion = next(item for item in standard.criteria if item.criterion_id == "output_scope")
    from ordessa_engineering.methods.definitions.models.compiled import freeze_value
    wrong_resource = next(item.resource_ref for item in program.decision_definitions
                          if item.question_set_id == "test-evidence")
    bad_check = replace(criterion.checks[0], bindings=freeze_value({
        "question_set": asdict(wrong_resource),
        "question_ids": ["output_scope"],
    }))
    bad_criterion = replace(criterion, checks=(bad_check,))
    bad_standard = replace(standard, criteria=tuple(
        bad_criterion if item.criterion_id == criterion.criterion_id else item
        for item in standard.criteria))
    with pytest.raises(ApplicationError, match="DECISION_QUESTION_BINDING_UNAVAILABLE"):
        GenericDecisionCheckSource._questions(SimpleNamespace(program=program),
            SimpleNamespace(check_keys=(key,)), bad_standard, (key,))

    decision = next(item for item in program.decision_definitions
                    if item.question_set_id == "output-scope")
    question = decision.questions[0]
    bad_question = replace(question, criterion_refs=tuple(
        replace(ref, criterion_id="wrong_criterion") for ref in question.criterion_refs))
    bad_decision = replace(decision, questions=(bad_question,))
    bad_program = replace(program, decision_definitions=tuple(
        bad_decision if item.question_set_id == decision.question_set_id else item
        for item in program.decision_definitions))
    with pytest.raises(ApplicationError, match="DECISION_QUESTION_BINDING_UNAVAILABLE"):
        GenericDecisionCheckSource._questions(SimpleNamespace(program=bad_program),
            SimpleNamespace(check_keys=(key,)), standard, (key,))
