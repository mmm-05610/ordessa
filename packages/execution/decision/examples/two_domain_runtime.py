"""Distinct typed domain adapters over the same host-neutral decision runtime.

The deterministic examples show bounded execution/evidence mechanics only.
They do not establish material quality, DID compliance, or user approval.
"""
import asyncio
from dataclasses import asdict, dataclass
import importlib.util
import json
import sys
import uuid

from pydantic_graph import GraphBuilder

from decision_runtime import (
    BusinessOutcome,
    DecisionRequest,
    DecisionServices,
    FlowRef,
    MemoryEvidenceSink,
    PolicyRef,
    ReadContext,
    RunContext,
    RunLimits,
    TaskBrief,
    TrustedFlow,
    flow_digest,
    reviewed_code_digest,
    run_decision,
)
from decision_runtime.definitions import plain


@dataclass(frozen=True)
class MaterialCandidate:
    candidate_id: str
    source_verified: bool
    residual_risk: float
    utility_score: int


@dataclass(frozen=True)
class MaterialsInput:
    risk_limit: float
    candidates: tuple[MaterialCandidate, ...]


@dataclass(frozen=True)
class ClaimSource:
    claim_id: str
    source_ref: str
    source_version: str | None
    source_verified: bool
    baseline_digest: str


@dataclass(frozen=True)
class DidReviewInput:
    subject_id: str
    approved_baseline: str
    required_claims: tuple[str, ...]
    sources: tuple[ClaimSource, ...]


class NoModelCalls:
    binding_ref = 'controlled-not-used/1'
    settings_digest = 'sha256:controlled-not-used'

    def __init__(self):
        self.calls = 0

    async def decide(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError('these deterministic domain examples must not call a model')


def _one_input(request):
    if len(request.task.inputs) != 1:
        raise ValueError('domain_input_count')
    value = request.task.inputs[0]
    if not isinstance(value, dict):
        # Contract decoding freezes mappings; they implement Mapping but may
        # not be an ordinary dict.
        from collections.abc import Mapping
        if not isinstance(value, Mapping):
            raise ValueError('domain_input_shape')
    return value


def _materials_input(request):
    value = _one_input(request)
    candidates = tuple(MaterialCandidate(**candidate) for candidate in value['candidates'])
    return MaterialsInput(value['risk_limit'], candidates)


def _did_review_input(request):
    value = _one_input(request)
    sources = tuple(ClaimSource(**source) for source in value['sources'])
    return DidReviewInput(value['subject_id'], value['approved_baseline'],
                          tuple(value['required_claims']), sources)


def materials_flow():
    policy_refs = (PolicyRef('materials.risk-screening', '1', 'sha256:materials-policy-v1'),)
    builder = GraphBuilder(name='materials.screening', state_type=MaterialsInput,
        deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome,
        auto_instrument=False)

    @builder.step(node_id='screen-and-rank-candidates')
    async def screen_and_rank(ctx):
        await ctx.deps.enter_node('screen-and-rank-candidates')
        request = ctx.inputs
        material_case = _materials_input(request)
        if any(not candidate.source_verified for candidate in material_case.candidates):
            return BusinessOutcome('clarify', issues=({'code': 'material-source-unverified'},))
        eligible = [candidate for candidate in material_case.candidates
                    if candidate.residual_risk <= material_case.risk_limit]
        if not eligible:
            return BusinessOutcome('blocked', issues=({'code': 'no-material-within-risk-limit'},))
        selected = max(eligible, key=lambda candidate: (candidate.utility_score, -candidate.residual_risk))
        return BusinessOutcome('revise', issues=({'code': 'material-ranked',
            'candidate_id': selected.candidate_id},))

    builder.add(builder.edge_from(builder.start_node).to(screen_and_rank))
    builder.add(builder.edge_from(screen_and_rank).to(builder.end_node))
    code = reviewed_code_digest(__file__)
    ref = FlowRef('materials.screening', '1', flow_digest(code, policy_refs))
    return TrustedFlow(ref, builder.build(), _materials_input, policy_refs,
                       code, 'controlled:materials-screening/1')


def did_review_flow():
    policy_refs = (PolicyRef('did.source-mapping-review', '1', 'sha256:did-policy-v1'),)
    builder = GraphBuilder(name='did.source-mapping-review', state_type=DidReviewInput,
        deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome,
        auto_instrument=False)

    @builder.step(node_id='verify-claim-source-map')
    async def verify_claim_source_map(ctx):
        await ctx.deps.enter_node('verify-claim-source-map')
        did_case = _did_review_input(ctx.inputs)
        source_by_claim = {source.claim_id: source for source in did_case.sources}
        missing = tuple(claim for claim in did_case.required_claims if claim not in source_by_claim)
        if missing:
            return BusinessOutcome('clarify', issues=({'code': 'did-claim-source-missing',
                'claim_ids': missing},))
        unversioned = tuple(claim for claim in did_case.required_claims
            if not source_by_claim[claim].source_version or not source_by_claim[claim].source_verified
            or not source_by_claim[claim].source_ref)
        if unversioned:
            return BusinessOutcome('clarify', issues=({'code': 'did-source-version-missing',
                'claim_ids': unversioned},))
        mismatched = tuple(claim for claim in did_case.required_claims
            if source_by_claim[claim].baseline_digest != did_case.approved_baseline)
        if mismatched:
            return BusinessOutcome('blocked', issues=({'code': 'did-source-baseline-mismatch',
                'claim_ids': mismatched},))
        return BusinessOutcome('revise', issues=({'code': 'did-source-map-reviewable',
            'subject_id': did_case.subject_id, 'claim_count': len(did_case.required_claims),
            'baseline': did_case.approved_baseline},))

    builder.add(builder.edge_from(builder.start_node).to(verify_claim_source_map))
    builder.add(builder.edge_from(verify_claim_source_map).to(builder.end_node))
    code = reviewed_code_digest(__file__)
    ref = FlowRef('did.source-mapping-review', '1', flow_digest(code, policy_refs))
    return TrustedFlow(ref, builder.build(), _did_review_input, policy_refs,
                       code, 'controlled:did-source-review/1')


async def _run(flow, domain_input, domain_name):
    request = DecisionRequest('request-' + uuid.uuid4().hex,
        TaskBrief('task-' + domain_name, '1', 'Evaluate typed, versioned domain inputs.',
            inputs=(asdict(domain_input),), boundaries=('controlled',),
            acceptance_criteria=('Use only supplied deterministic facts.',)),
        flow.ref, RunLimits())
    context = ReadContext(object(), 'example.' + domain_name)
    sink = MemoryEvidenceSink(read_context=context)
    provider = NoModelCalls()
    services = DecisionServices(None, None, None, None, provider, sink,
        {'domain': domain_name}, context, flow.policy_refs)
    result = await run_decision(request, flow=flow, services=services)
    evidence = await sink.read(result.run_id, context)
    if result.status != 'completed' or evidence['status'] != 'completed':
        raise AssertionError('controlled runtime mechanics did not complete')
    return result, evidence, provider.calls


async def run_materials(domain_input):
    return await _run(materials_flow(), domain_input, 'materials')


async def run_did_review(domain_input):
    return await _run(did_review_flow(), domain_input, 'did-review')


async def main():
    if 'pacthold' in sys.modules or importlib.util.find_spec('pacthold') is not None:
        raise AssertionError('isolated neutral example must neither import nor install Pacthold')
    cases = (
        ('materials-screening', await run_materials(MaterialsInput(0.20, (
            MaterialCandidate('low-utility', True, 0.10, 40),
            MaterialCandidate('best-eligible', True, 0.12, 95),
            MaterialCandidate('unsafe', True, 0.35, 100),
        )))),
        ('materials-screening-rejected', await run_materials(MaterialsInput(0.20, (
            MaterialCandidate('unsafe-a', True, 0.25, 80),
            MaterialCandidate('unsafe-b', True, 0.40, 90),
        )))),
        ('did-evidence-review', await run_did_review(DidReviewInput(
            'did:example:subject-7', 'sha256:baseline-7', ('controller', 'service-endpoint'), (
                ClaimSource('controller', 'registry:controller-7', 'registry/42', True, 'sha256:baseline-7'),
                ClaimSource('service-endpoint', 'registry:endpoint-7', 'registry/42', True, 'sha256:baseline-7'),
            )))),
        ('did-evidence-review-incomplete', await run_did_review(DidReviewInput(
            'did:example:subject-8', 'sha256:baseline-8', ('controller', 'service-endpoint'), (
                ClaimSource('controller', 'registry:controller-8', 'registry/43', True, 'sha256:baseline-8'),
                ClaimSource('service-endpoint', 'registry:endpoint-8', None, True, 'sha256:baseline-8'),
            )))),
        ('did-evidence-review-stale', await run_did_review(DidReviewInput(
            'did:example:subject-9', 'sha256:baseline-9', ('controller',), (
                ClaimSource('controller', 'registry:controller-9', 'registry/44', True, 'sha256:old-baseline'),
            )))),
    )
    rows = []
    for domain, (result, evidence, model_calls) in cases:
        rows.append({'domain': domain, 'disposition': result.outcome.disposition,
            'issues': plain(result.outcome.issues), 'evidence_status': evidence['status'],
            'model_calls': model_calls})
    return rows


if __name__ == '__main__':
    print(json.dumps(asyncio.run(main()), sort_keys=True))
