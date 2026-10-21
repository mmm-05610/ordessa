"""Explicit two-call free JEV qualification; not formal Engineering approval.

Run only under the user's live authorization. Uses actual Graph/gateway/SDK and
durable evidence. No retries, redirects, paid fallback or user task material.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import httpx2
from pydantic_graph import GraphBuilder
from ordessa_decision.definitions import (
    DecisionQuestion, PolicyRef, FlowRef, TaskBrief, RunLimits, DecisionRequest,
    BusinessOutcome, DecisionServices, ReadContext, digest, plain,
)
from ordessa_decision.runtime import TrustedFlow, RunContext, run_decision, reviewed_code_digest, flow_digest
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput

ENDPOINT = "https://opencode.ai/zen/v1/systemone"

class AuditTransport(httpx2.AsyncBaseTransport):
    def __init__(self, path):
        self.inner = httpx2.AsyncHTTPTransport(retries=0, trust_env=False)
        self.requests = []
        self.path = path
        self.path.write_text(json.dumps(self.requests)+'\n')
    async def handle_async_request(self, request):
        if str(request.url) != ENDPOINT or request.method != "POST" or len(self.requests) >= 2:
            raise RuntimeError("live_scope_refused")
        row = {"attempt": len(self.requests) + 1, "endpoint": ENDPOINT}
        self.requests.append(row)
        self.path.write_text(json.dumps(self.requests)+'\n')
        response = await self.inner.handle_async_request(request)
        row["http_status"] = response.status_code
        self.path.write_text(json.dumps(self.requests)+'\n')
        return response
    async def aclose(self):
        await self.inner.aclose()

class RecordedProvider:
    def __init__(self, provider):
        self.provider = provider
        self.binding_ref, self.settings_digest = provider.binding_ref, provider.settings_digest
        self.answers = []
    async def decide(self, question, context):
        answer = await self.provider.decide(question, context)
        self.answers.append(answer)
        return answer

async def qualify(output):
    output.mkdir(parents=True, exist_ok=False)
    secret = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env').read()
    transport = AuditTransport(output/'http-audit.json')
    provider = JevDecisionProvider(JevProviderSettings(binding_ref='ordessa-v1-zen-jev',
        secret_ref='approved-process-input', base_url='https://opencode.ai/zen',
        model='jev-1.13-free', timeout_seconds=25),
        secret_resolver=lambda ref: secret.decode('ascii'), transport=transport)
    recorded = RecordedProvider(provider)
    read_context = ReadContext(object(), 'ordessa-v1-live-qualification')
    (output/'durable').mkdir(mode=0o700)
    sink = FileEvidenceSink(output/'durable', read_context=read_context)
    cases = [('missing-check', {'proposal': 'Return square(n).', 'requirements': 'Must specify rejection of negative inputs.', 'acceptance': 'Check square(2)=4.'}, 'reject'),
             ('revised-check', {'proposal': 'Return square(n); reject negative inputs with ValueError.', 'requirements': 'Must specify rejection of negative inputs.', 'acceptance': 'Check square(2)=4 and square(-1) raises ValueError.'}, 'pass')]
    policy = PolicyRef('ordessa-v1.synthetic-review', '1', digest('policy', cases))
    rows = []
    try:
        for identity, state, expected in cases:
            before = len(recorded.answers)
            builder = GraphBuilder(name='ordessa-v1-live-review', state_type=dict, deps_type=RunContext,
                input_type=DecisionRequest, output_type=BusinessOutcome, auto_instrument=False)
            @builder.step
            async def evaluate(ctx) -> BusinessOutcome:
                await ctx.deps.enter_node('EvaluateExactSyntheticRevision')
                question = DecisionQuestion('requirements-covered', '1', 'choice', state,
                    'Does the proposal AND its acceptance checks explicitly cover every stated requirement? Reject missing checks. Evaluate only supplied text.',
                    options={'pass': 'All requirements and checks explicitly covered.', 'reject': 'A required behavior or acceptance check is missing.'}, policy_ref=policy)
                await ctx.deps.gateway.decide(question)
                return BusinessOutcome('clarify', issues=({'code': 'qualification_only_no_grant'},))
            builder.add(builder.edge_from(builder.start_node).to(evaluate), builder.edge_from(evaluate).to(builder.end_node))
            code = reviewed_code_digest(__file__)
            ref = FlowRef('ordessa-v1.synthetic-review', '1', flow_digest(code, (policy,)))
            flow = TrustedFlow(ref, builder.build(), lambda request: {}, (policy,), code, 'user-authorized-controlled-live')
            request = DecisionRequest(identity, TaskBrief(identity, '1', 'Synthetic review qualification.'), ref,
                RunLimits(max_model_attempts=1, max_node_entries=2, max_repair_rounds=0, wall_timeout_seconds=35))
            result = await run_decision(request, flow=flow, services=DecisionServices(
                None, None, None, None, recorded, sink, {}, read_context, (policy,), mode='real'))
            durable = await sink.read(result.run_id, read_context)
            answers = recorded.answers[before:]
            rows.append({'case': identity, 'expected': expected, 'status': result.status,
                'run_id': result.run_id, 'result_digest': digest('result', result),
                'durable_terminal_matches': durable.get('terminal', {}).get('terminal_digest') == digest('result', result),
                'answers': [plain(a) for a in answers],
                'quality_pass': len(answers) == 1 and answers[0].value == expected})
            if result.status != 'completed':
                break  # No resend after failed/unknown original attempt.
    finally:
        await provider.close()
        await sink.close()
    receipt = {'kind': 'actual-JEV-SDK-Graph-qualification', 'http_requests': transport.requests,
        'rows': rows, 'retry': 0, 'paid_fallback': False, 'formal_engineering_review': False,
        'quality_scope': 'Two synthetic labels only; no product approval or general quality claim.'}
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2)
    if secret.decode('ascii') in rendered:
        raise RuntimeError('credential_output_blocked')
    secret[:] = b'\0' * len(secret)
    (output/'receipt.json').write_text(rendered+'\n')
    print(rendered)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.authorize_live:
        raise SystemExit('explicit_live_authorization_required')
    try:
        asyncio.run(qualify(args.output))
    except Exception as error:
        print(json.dumps({'status': 'qualification_failed', 'error_type': type(error).__name__}))
        raise SystemExit(1)
