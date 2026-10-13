"""Descriptors/adapters cover only two narrow mechanical check families."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest, VerifiedCheckResponse
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.orchestration.check_capabilities import (
    MechanicalCheckCapabilityAdapter,
    mechanical_review_check_capabilities,
)
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from test_review_usecases import _context, _plan, _scope
from ordessa_engineering.application.orchestration.check_capabilities import (
    _CLAIMS_COVERAGE,
    _SOURCE_INTEGRITY,
)
from ordessa_engineering.methods.definitions.models.identity import method_digest


def test_mechanical_catalog_contains_only_the_two_existing_source_checks():
    catalog = mechanical_review_check_capabilities()
    by_id = {item.capability_id: item for item in catalog.capabilities}
    assert set(by_id) == {
        "ordessa.sources.integrity",
        "ordessa.claims.coverage",
    }
    assert catalog.trust_class == "host"
    for descriptor in by_id.values():
        assert descriptor.kind == "check"
        assert descriptor.interface_version == "1.0.0"
        assert descriptor.contract_digest == method_digest("capability-contract", descriptor.contract)
        assert descriptor.contract["owner"].endswith("MechanicalReviewCheckSource")
        assert descriptor.contract["context"] == "method-declared Artifact provenance checks"
        assert "exact original method snapshot" in descriptor.contract["standard_binding"]
        assert descriptor.contract["semantic_authority"] is False
        assert "original Review COMMIT" in descriptor.contract["guard"]


def test_claim_link_coverage_stays_unknown_when_complete_and_never_satisfied():
    descriptor = next(item for item in mechanical_review_check_capabilities().capabilities
        if item.capability_id == "ordessa.claims.coverage")
    assert descriptor.contract["result"] == {
        "claims_and_evidence_link_chain_complete": "unknown",
        "claim_set_empty_or_link_missing": "insufficient",
    }
    assert descriptor.contract["complete_chain_is_never_satisfied"] is True
    assert "semantic claim support" in descriptor.contract["does_not_establish"]
    assert "review pass" in descriptor.contract["does_not_establish"]


def test_source_integrity_is_only_captured_byte_and_selector_integrity():
    descriptor = next(item for item in mechanical_review_check_capabilities().capabilities
        if item.capability_id == "ordessa.sources.integrity")
    assert descriptor.contract["result"] == {
        "captured_source_bytes_and_selectors_valid": "satisfied",
        "no_captured_source_bytes": "insufficient",
    }
    assert set(descriptor.contract["does_not_establish"]) == {
        "source authenticity", "claim support", "source completeness",
    }


@pytest.fixture
def routed_source(monkeypatch):
    scope = _scope()
    target = SimpleNamespace(
        realm_id=scope.realm_id, project_id=scope.project_id,
        artifact_id="artifact-1", revision_id="revision-1",
        digest=Digest("sha256", "a" * 64),
    )
    from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
    target = ArtifactRevisionRef(**vars(target))
    base_plan = _plan(scope, target)
    requirement = replace(base_plan.requirement, purpose="provenance_support",
        criterion_set_ref=CriterionSetRef("source-review", 1, Digest("sha256", "b" * 64)))
    plan = replace(base_plan, requirement=requirement)
    key = plan.check_keys[0]
    standard = SimpleNamespace(standard_id="source-review", purpose="provenance_support",
        criteria=(SimpleNamespace(criterion_id=key.criterion_id,
            checks=(SimpleNamespace(capability_id=_SOURCE_INTEGRITY, interface_version="1.0.0"),)),))
    request = FrozenCheckRequest(plan.plan_digest, 0, 1)
    proof = BlobRef(Digest("sha256", "c" * 64), 3, "application/json", "proof-1")
    response = VerifiedCheckResponse((CriterionAnswer(key, "satisfied", (target,), "byte integrity only"),),
        Digest("sha256", "d" * 64))
    factory = SimpleNamespace(authority_id="original-library-authority")
    source = object.__new__(MechanicalReviewCheckSource)
    source.factory = factory
    source.methods = SimpleNamespace(factory=factory)
    source.blobs = SimpleNamespace(authority_id=factory.authority_id)
    calls = []

    def capture(context, full_plan, frozen, *, standard, check_keys):
        calls.append(("capture", full_plan, frozen, standard, check_keys))
        return proof

    def verify(context, full_plan, frozen, raw_ref, *, standard, check_keys):
        calls.append(("verify", full_plan, frozen, standard, check_keys, raw_ref))
        return response

    @contextmanager
    def guard(context, admissions):
        calls.append(("guard", admissions))
        yield

    monkeypatch.setattr(source, "capture_proof", capture, raising=False)
    monkeypatch.setattr(source, "verify_checks", verify, raising=False)
    monkeypatch.setattr(source, "guard_checks", guard, raising=False)
    adapter = MechanicalCheckCapabilityAdapter(source)
    return adapter, _context(scope, "check-adapter"), plan, request, standard, (key,), proof, response, calls


def test_adapter_routes_capture_verify_and_commit_guard_to_original_source(routed_source):
    adapter, context, plan, request, standard, keys, proof, response, calls = routed_source
    captured, verified = adapter.execute(_SOURCE_INTEGRITY, context, plan, request,
        standard=standard, check_keys=keys)
    assert captured == proof and verified == response
    assert [row[0] for row in calls] == ["capture", "verify"]
    assert calls[0][1:] == (plan, request, standard, keys)
    with adapter.guard_checks(_SOURCE_INTEGRITY, context, plan, request,
            standard=standard, check_keys=keys, raw_response_ref=proof, response=response):
        assert calls[-1][0] == "guard"
        admission = calls[-1][1][0]
        assert admission.plan == plan and admission.request == request
        assert admission.raw_response_ref == proof and admission.check_keys == keys
        assert admission.response == response


@pytest.mark.parametrize("capability", ["ordessa.decision.evaluate", "ordessa.outputs.scope"])
def test_adapter_refuses_other_standard_capabilities_before_source_calls(routed_source, capability):
    adapter, context, plan, request, standard, keys, _, _, calls = routed_source
    with pytest.raises(ApplicationError, match="REVIEW_CHECK_EXECUTION_UNAVAILABLE"):
        adapter.execute(capability, context, plan, request, standard=standard, check_keys=keys)
    assert calls == []


def test_adapter_forwards_method_selected_standard_without_phase_allowlist(routed_source):
    adapter, context, plan, request, standard, keys, _, _, calls = routed_source
    quality = SimpleNamespace(**{**vars(standard), "purpose": "quality"})
    other_method_standard = SimpleNamespace(**{**vars(quality), "standard_id": "method-specific-criteria"})
    # The monkeypatched source double tests router selection only. In production
    # the original source checks the exact standard against the current method
    # snapshot before it emits or guards evidence.
    proof, _ = adapter.execute(_SOURCE_INTEGRITY, context, plan, request,
        standard=other_method_standard, check_keys=keys)
    assert proof is not None
    assert calls[0][3] is other_method_standard and calls[1][3] is other_method_standard
    calls.clear()
    mismatch = SimpleNamespace(**{**vars(standard), 'criteria':(SimpleNamespace(criterion_id=keys[0].criterion_id,
        checks=(SimpleNamespace(capability_id=_CLAIMS_COVERAGE, interface_version="1.0.0"),)),)})
    with pytest.raises(ApplicationError, match="REVIEW_CHECK_EXECUTION_UNAVAILABLE"):
        adapter.execute(_SOURCE_INTEGRITY, context, plan, request, standard=mismatch, check_keys=keys)
    assert calls == []


def test_adapter_refuses_keys_outside_the_unchanged_full_plan_in_execute_and_guard(routed_source):
    adapter, context, plan, request, standard, keys, proof, response, calls = routed_source
    other_key = replace(keys[0], criterion_id="not-in-full-plan")
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_INVALID"):
        adapter.execute(_SOURCE_INTEGRITY, context, plan, request,
            standard=standard, check_keys=(other_key,))
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_INVALID"):
        with adapter.guard_checks(_SOURCE_INTEGRITY, context, plan, request,
                standard=standard, check_keys=(other_key,), raw_response_ref=proof,
                response=response):
            pytest.fail("invalid subset must fail before original trust guard")
    assert calls == []
