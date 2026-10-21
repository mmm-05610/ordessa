"""Different typed domain rules use the same neutral request/runtime/evidence API."""
import dataclasses
import importlib.util
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[5]
EXAMPLE = ROOT / 'packages/execution/decision/examples/two_domain_runtime.py'


@pytest.fixture(scope='module')
def domain_api():
    # The example is also the independently runnable no-host entry point.
    return runpy.run_path(str(EXAMPLE), run_name='ordessa_decision_example')


@pytest.mark.asyncio
async def test_typed_material_screening_ranks_eligible_candidates(domain_api):
    MaterialsInput = domain_api['MaterialsInput']
    MaterialCandidate = domain_api['MaterialCandidate']
    run_case = domain_api['run_materials']
    request_data = MaterialsInput(
        risk_limit=0.20,
        candidates=(
            MaterialCandidate('low-utility', True, 0.10, 40),
            MaterialCandidate('best-eligible', True, 0.12, 95),
            MaterialCandidate('unsafe', True, 0.35, 100),
        ),
    )
    result, evidence, calls = await run_case(request_data)
    assert result.status == 'completed'
    assert result.outcome.disposition == 'revise'
    assert result.outcome.issues == ({'code': 'material-ranked', 'candidate_id': 'best-eligible'},)
    assert evidence['status'] == 'completed'
    assert calls == 0


@pytest.mark.asyncio
async def test_typed_material_screening_blocks_when_no_candidate_meets_risk_limit(domain_api):
    MaterialsInput = domain_api['MaterialsInput']
    MaterialCandidate = domain_api['MaterialCandidate']
    result, evidence, calls = await domain_api['run_materials'](MaterialsInput(
        risk_limit=0.20,
        candidates=(
            MaterialCandidate('unsafe-a', True, 0.25, 80),
            MaterialCandidate('unsafe-b', True, 0.40, 90),
        ),
    ))
    assert result.status == 'completed'
    assert result.outcome.disposition == 'blocked'
    assert result.outcome.issues == ({'code': 'no-material-within-risk-limit'},)
    assert evidence['status'] == 'completed'
    assert calls == 0


@pytest.mark.asyncio
async def test_typed_did_review_accepts_complete_versioned_source_mapping(domain_api):
    DidReviewInput = domain_api['DidReviewInput']
    ClaimSource = domain_api['ClaimSource']
    result, evidence, calls = await domain_api['run_did_review'](DidReviewInput(
        subject_id='did:example:subject-7',
        approved_baseline='sha256:baseline-7',
        required_claims=('controller', 'service-endpoint'),
        sources=(
            ClaimSource('controller', 'registry:controller-7', 'registry/42', True, 'sha256:baseline-7'),
            ClaimSource('service-endpoint', 'registry:endpoint-7', 'registry/42', True, 'sha256:baseline-7'),
        ),
    ))
    assert result.status == 'completed'
    assert result.outcome.disposition == 'revise'
    assert result.outcome.issues == ({
        'code': 'did-source-map-reviewable',
        'subject_id': 'did:example:subject-7',
        'claim_count': 2,
        'baseline': 'sha256:baseline-7',
    },)
    assert evidence['status'] == 'completed'
    assert calls == 0


@pytest.mark.asyncio
async def test_typed_did_review_clarifies_when_required_claim_lacks_versioned_source(domain_api):
    DidReviewInput = domain_api['DidReviewInput']
    ClaimSource = domain_api['ClaimSource']
    result, evidence, calls = await domain_api['run_did_review'](DidReviewInput(
        subject_id='did:example:subject-8',
        approved_baseline='sha256:baseline-8',
        required_claims=('controller', 'service-endpoint'),
        sources=(
            ClaimSource('controller', 'registry:controller-8', 'registry/43', True, 'sha256:baseline-8'),
            ClaimSource('service-endpoint', 'registry:endpoint-8', None, True, 'sha256:baseline-8'),
        ),
    ))
    assert result.status == 'completed'
    assert result.outcome.disposition == 'clarify'
    assert result.outcome.issues == ({
        'code': 'did-source-version-missing',
        'claim_ids': ('service-endpoint',),
    },)
    assert evidence['status'] == 'completed'
    assert calls == 0


@pytest.mark.asyncio
async def test_typed_did_review_blocks_mapping_bound_to_stale_baseline(domain_api):
    DidReviewInput = domain_api['DidReviewInput']
    ClaimSource = domain_api['ClaimSource']
    result, evidence, calls = await domain_api['run_did_review'](DidReviewInput(
        subject_id='did:example:subject-9',
        approved_baseline='sha256:baseline-9',
        required_claims=('controller',),
        sources=(ClaimSource('controller', 'registry:controller-9', 'registry/44', True,
                             'sha256:old-baseline'),),
    ))
    assert result.status == 'completed'
    assert result.outcome.disposition == 'blocked'
    assert result.outcome.issues == ({
        'code': 'did-source-baseline-mismatch', 'claim_ids': ('controller',),
    },)
    assert evidence['status'] == 'completed'
    assert calls == 0


def test_domains_have_distinct_typed_adapters_and_do_not_require_pacthold(domain_api):
    assert dataclasses.is_dataclass(domain_api['MaterialsInput'])
    assert dataclasses.is_dataclass(domain_api['DidReviewInput'])
    assert domain_api['materials_flow']().ref.flow_id == 'materials.screening'
    assert domain_api['did_review_flow']().ref.flow_id == 'did.source-mapping-review'
    assert importlib.util.find_spec('pacthold') is None
