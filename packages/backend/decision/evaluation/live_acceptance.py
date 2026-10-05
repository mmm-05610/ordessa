"""Frozen synthetic acceptance through the existing graph, gateway and Jev SDK.

No automatic retry/resume. A scope ledger is mandatory and must be reused across
processes, including when output directories change. Answers are synthetic only.
"""
import argparse
import asyncio
import fcntl
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace

import httpx2
from pydantic_graph import GraphBuilder
from ordessa_decision.contracts import (DecisionQuestion, DecisionAnswer, PolicyRef,
    TaskBrief, RunLimits, DecisionRequest, BusinessOutcome, DecisionServices,
    ReadContext, FlowRef, digest, plain)
from ordessa_decision.providers.jev import JevDecisionProvider, JevProviderSettings
from ordessa_decision.runtime import (TrustedFlow, RunContext, run_decision,
    reviewed_code_digest, flow_digest)
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision.flows.agent_assignment.task_gate import compile_task_gate, reduce_task_gate, _policy

ENDPOINT = 'https://opencode.ai/zen/v1/systemone'


class EvaluationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def validate(plan):
    """Validate every frozen question and output domain before any key read."""
    try:
        if plan['version'] != 'jev-live-acceptance/1' or plan['synthetic_only'] is not True:
            raise ValueError()
        scope = plan['scope_id']
        if not isinstance(scope, str) or not scope or len(scope) > 128: raise ValueError()
        settings = JevProviderSettings(**plan['settings'])
        if (settings.base_url + '/v1/systemone' != ENDPOINT or settings.model != 'jev-1.13-free'
                or settings.accepted_response_models != ('jev-1.13-free',)):
            raise ValueError()
        limits = plan['limits']
        if type(limits['max_http_requests']) is not int or not 1 <= limits['max_http_requests'] <= 1000:
            raise ValueError()
        for key in ('wall_timeout_seconds', 'case_timeout_seconds'):
            if type(limits[key]) not in (int, float) or not math.isfinite(limits[key]) or not 0 < limits[key] <= 3600:
                raise ValueError()
        refs = tuple(PolicyRef.from_dict(r) for r in plan['policy_refs'])
        policy = _policy(plan['task_gate_policy'])
        pref = PolicyRef(policy['policy_id'], policy['version'], digest('policy', policy))
        if pref not in refs: raise ValueError()
        cases = []; ids = set()
        for case in plan['cases']:
            cid = case['id']
            if not isinstance(cid, str) or not cid or cid in ids or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in cid): raise ValueError()
            ids.add(cid)
            task = TaskBrief.from_dict(case['task'])
            questions = tuple(DecisionQuestion.from_dict(q) for q in case['questions'])
            qmap = {q.question_id: q for q in questions}
            if len(qmap) != len(questions): raise ValueError()
            for q in questions:
                if q.policy_ref not in refs: raise ValueError()
                JevDecisionProvider._map_question(q)
            expected = case['expected']; kind = expected['kind']; gate = None
            if kind == 'gate_result':
                if set(expected) - {'kind', 'value', 'dimension_expected'} or expected['value'] not in ('gate_pass', 'clarify', 'revise', 'blocked'): raise ValueError()
                ctx = SimpleNamespace(services=SimpleNamespace(policy={}, policy_refs=refs))
                gate = compile_task_gate(task, ctx, policy, facts=case['facts'], policy_ref=pref)
                if [q.question_digest for q in gate.questions] != [q.question_digest for q in questions]: raise ValueError()
                dims = expected.get('dimension_expected', {})
                if set(dims) - set(qmap) or any(v not in ('pass', 'fail', 'unknown') for v in dims.values()): raise ValueError()
            elif kind == 'choice_expected':
                if set(expected) != {'kind', 'values'} or set(expected['values']) != set(qmap) or not questions: raise ValueError()
                if any(q.kind != 'choice' or expected['values'][q.question_id] not in q.options for q in questions): raise ValueError()
            elif kind in ('noul_range', 'score_range'):
                if set(expected) != {'kind', 'ranges'} or set(expected['ranges']) != set(qmap) or not questions: raise ValueError()
                for q in questions:
                    lo, hi = expected['ranges'][q.question_id]
                    maximum = 1 if kind == 'noul_range' else len(q.scale) - 1
                    if q.kind != ('noul' if kind == 'noul_range' else 'score') or any(type(v) not in (int, float) or not math.isfinite(v) for v in (lo, hi)) or not 0 <= lo <= hi <= maximum: raise ValueError()
            else: raise ValueError()
            cases.append((case, task, questions, gate))
        if not cases or sum(len(q) for _, _, q, _ in cases) > limits['max_http_requests']: raise ValueError()
        return settings, refs, cases
    except Exception:
        raise EvaluationError('plan_invalid') from None


def prepare(plan):
    _, _, cases = validate(plan)
    return {'status': 'PREPARED_NOT_RUN', 'input_hash': digest('policy', plan),
        'scope_id': plan['scope_id'], 'maximum_http_requests': sum(len(q) for _, _, q, _ in cases),
        'cases': [{'id': c['id'], 'status': 'NOT_RUN', 'question_digests': [q.question_digest for q in qs]} for c, _, qs, _ in cases],
        'credential_reads': 0, 'actual_http_requests': 0}


class ScopeLedger:
    """Locked durable reservations. An uncertain claim is never released."""
    def __init__(self, path, plan):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try: fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.close(); raise EvaluationError('scope_busy') from None
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {
                'scope_id': plan['scope_id'], 'input_hash': digest('policy', plan),
                'limit': plan['limits']['max_http_requests'], 'cases': [], 'requests': []}
        except Exception:
            self.close(); raise EvaluationError('scope_invalid') from None
        if (not isinstance(self.data, dict) or self.data.get('input_hash') != digest('policy', plan) or self.data.get('scope_id') != plan['scope_id']
                or self.data.get('limit') != plan['limits']['max_http_requests']
                or not isinstance(self.data.get('cases'), list) or not isinstance(self.data.get('requests'), list)):
            self.close(); raise EvaluationError('scope_conflict')
    def begin(self, cid):
        if cid in self.data['cases']: raise EvaluationError('case_already_claimed')
        self.data['cases'].append(cid); atomic_write(self.path, self.data)
    def claim(self, cid):
        if len(self.data['requests']) >= self.data['limit']: raise EvaluationError('http_limit')
        row = {'case_id': cid, 'attempt': len(self.data['requests']) + 1, 'status': 'CLAIMED_UNKNOWN'}
        self.data['requests'].append(row); atomic_write(self.path, self.data)
        return row
    def save(self): atomic_write(self.path, self.data)
    def close(self):
        if self.lock is not None: os.close(self.lock); self.lock = None


class AuditedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, inner, ledger, deadline):
        self.inner = inner; self.ledger = ledger; self.deadline = deadline; self.case_id = None
    async def handle_async_request(self, request):
        if str(request.url) != ENDPOINT or request.method != 'POST' or time.monotonic() >= self.deadline:
            raise EvaluationError('http_scope_refused')
        row = self.ledger.claim(self.case_id); start = time.monotonic()
        try:
            response = await self.inner.handle_async_request(request)
            row.update(status='HEADERS_RETURNED', http_status=response.status_code)
            return response
        except asyncio.CancelledError:
            row['status'] = 'CANCELLED_UNKNOWN'; raise
        except Exception:
            row['status'] = 'TRANSPORT_FAILED_UNKNOWN'; raise EvaluationError('transport_failed') from None
        finally:
            row['seconds_to_headers'] = round(time.monotonic() - start, 4); self.ledger.save()
    async def aclose(self): await self.inner.aclose()


class RecordedProvider:
    def __init__(self, provider, row, save):
        self.provider = provider; self.row = row; self.save = save
        self.binding_ref = provider.binding_ref; self.settings_digest = provider.settings_digest
    async def decide(self, question, context):
        try: answer = await self.provider.decide(question, context)
        except asyncio.CancelledError:
            self.row['provider_error'] = 'cancelled_unknown'; self.save(); raise
        except Exception as error:
            code = getattr(error, 'code', '')
            self.row['provider_error'] = code if code in {'policy_invalid', 'provider_timeout', 'provider_failed', 'protocol_invalid', 'authentication_failed', 'call_refused'} else 'provider_failed'
            self.save(); raise
        self.row['answers'].append(plain(answer)); self.save()
        return answer


def score(case, questions, answers, gate=None):
    if len(answers) != len(questions) or [a.question_id for a in answers] != [q.question_id for q in questions] or any(a.kind != q.kind for a, q in zip(answers, questions)):
        raise EvaluationError('answer_set_invalid')
    actual = {a.question_id: a.value for a in answers}; expected = case['expected']
    if expected['kind'] == 'gate_result':
        outcome = reduce_task_gate(gate, answers)
        passed = outcome.status == expected['value'] and all(actual[k] == v for k, v in expected.get('dimension_expected', {}).items())
        return {'actual': outcome.status, 'dimensions': actual, 'issues': plain(outcome.issues), 'quality_pass': passed}
    if expected['kind'] == 'choice_expected': passed = actual == expected['values']
    else: passed = all(lo <= actual[k] <= hi for k, (lo, hi) in expected['ranges'].items())
    return {'actual': actual, 'quality_pass': passed}


async def verify_terminal(sink, result, context):
    evidence = await sink.read(result.run_id, context)
    if evidence.get('status') != 'completed' or evidence['terminal']['terminal_digest'] != digest('result', result):
        raise EvaluationError('terminal_unverified')


async def run_plan(plan, output, credential_file, authorize_live=False, *, ledger_path,
                   transport=None, terminal_verifier=verify_terminal):
    settings, refs, cases = validate(plan)
    if not authorize_live: raise EvaluationError('live_authorization_required')
    output = Path(output); ledger = ScopeLedger(ledger_path, plan)
    if any(c['id'] in ledger.data['cases'] for c, _, _, _ in cases):
        ledger.close(); raise EvaluationError('case_already_claimed')
    live_https = transport is None
    receipt = prepare(plan); receipt.update(status='IN_PROGRESS', rows=[], retry=0, native_effects=0, cost='UNKNOWN',
        evaluation_mode='live_https' if live_https else 'injected_test_transport')
    receipt['rows'] = [{'id': c['id'], 'technical_status': 'NOT_RUN', 'quality_pass': False, 'answers': []} for c, _, _, _ in cases]
    def save(): atomic_write(output / 'receipt.json', receipt)
    provider = sink = None; start = time.monotonic(); deadline = start + plan['limits']['wall_timeout_seconds']
    try:
        save()
        key = Path(credential_file).read_text().strip()
        if not key or '\n' in key: raise EvaluationError('credential_invalid')
        audited = AuditedTransport(transport or httpx2.AsyncHTTPTransport(retries=0), ledger, deadline)
        provider = JevDecisionProvider(settings, secret_resolver=lambda _: key, transport=audited)
        (output / 'durable').mkdir(parents=True, exist_ok=True, mode=0o700)
        context = ReadContext(object(), 'synthetic-live-acceptance'); sink = FileEvidenceSink(output / 'durable', read_context=context)
        code = digest('flow', {'reviewed_source': reviewed_code_digest(__file__), 'plan_digest': digest('policy', plan)})
        ref = FlowRef('jev.live-acceptance', '1', flow_digest(code, refs))
        for (case, task, questions, gate), row in zip(cases, receipt['rows']):
            if time.monotonic() >= deadline: row['error'] = 'global_deadline'; save(); continue
            ledger.begin(case['id']); audited.case_id = case['id']; row['technical_status'] = 'CLAIMED'; save()
            recorded = RecordedProvider(provider, row, save)
            builder = GraphBuilder(name='jev-live-acceptance', state_type=dict, deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome, auto_instrument=False)
            @builder.step
            async def evaluate(ctx) -> BusinessOutcome:
                await ctx.deps.enter_node('EvaluateSyntheticCase')
                for question in questions: await ctx.deps.gateway.decide(question)
                return BusinessOutcome('clarify', issues=({'code': 'evaluation_only_no_proposal'},))
            builder.add(builder.edge_from(builder.start_node).to(evaluate), builder.edge_from(evaluate).to(builder.end_node))
            flow = TrustedFlow(ref, builder.build(), lambda request: {}, refs, code, plan['scope_id'])
            limits = RunLimits(max_model_attempts=max(1, len(questions)), max_node_entries=2, max_repair_rounds=0, max_inflight_model_calls=1,
                wall_timeout_seconds=min(plan['limits']['case_timeout_seconds'], deadline - time.monotonic()), cleanup_timeout_seconds=2)
            services = DecisionServices(None, None, None, None, recorded, sink, {}, context, refs, mode='real')
            request = DecisionRequest('eval-' + case['id'], task, ref, limits)
            try:
                result = await run_decision(request, flow=flow, services=services)
                row.update(run_id=result.run_id, technical_status=result.status, result_digest=digest('result', result)); save()
                await terminal_verifier(sink, result, context)
                row['terminal_verified'] = True
                if result.status == 'completed':
                    row.update(score(case, questions, tuple(DecisionAnswer.from_dict(a) for a in row['answers']), gate))
                    row['quality_source'] = ('model' if live_https else 'controlled_transport') if questions else 'hard_rule_zero_model'
            except asyncio.CancelledError as cancellation:
                row.update(technical_status='CANCELLED', error='cancelled_unknown')
                if getattr(cancellation, 'run_id', None): row['run_id'] = cancellation.run_id
                save(); raise
            except Exception:
                row.update(technical_status='COLLECTION_FAILED', error='collection_failed', quality_pass=False)
            finally: save()
        receipt['status'] = 'SCOPED_PASS' if all(r['quality_pass'] for r in receipt['rows']) else 'PARTIAL'
    except asyncio.CancelledError:
        receipt.update(status='PARTIAL', error='cancelled_unknown'); raise
    except Exception:
        receipt.update(status='PARTIAL', error='evaluation_failed'); raise EvaluationError('evaluation_failed') from None
    finally:
        receipt['elapsed_seconds'] = round(time.monotonic() - start, 4)
        receipt['http_audit'] = ledger.data['requests']
        receipt['transport_attempts'] = len(ledger.data['requests'])
        receipt['actual_http_requests'] = len(ledger.data['requests']) if live_https else 0
        receipt['real_model_requests'] = receipt['actual_http_requests']
        receipt['usage'] = [a['usage_evidence'] for r in receipt['rows'] for a in r['answers']]
        receipt['usage_unknown_requests'] = max(0, len(ledger.data['requests']) - sum(u.get('status') == 'reported' for u in receipt['usage']))
        receipt['model_quality_passes'] = sum(r['quality_pass'] and r.get('quality_source') == 'model' for r in receipt['rows'])
        receipt['controlled_label_matches'] = sum(r['quality_pass'] and r.get('quality_source') == 'controlled_transport' for r in receipt['rows'])
        receipt['hard_rule_cases'] = sum(r.get('quality_source') == 'hard_rule_zero_model' for r in receipt['rows'])
        receipt['technical_counts'] = {status: sum(r['technical_status'] == status for r in receipt['rows']) for status in sorted({r['technical_status'] for r in receipt['rows']})}
        try:
            save()
        finally:
            try:
                if provider: await provider.close()
            finally:
                try:
                    if sink: await sink.close()
                finally: ledger.close()
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'run')); parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--ledger', type=Path)
    parser.add_argument('--credential-file', type=Path); parser.add_argument('--authorize-live', action='store_true')
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        if args.mode == 'prepare': atomic_write(args.output / 'prepared.json', prepare(plan))
        else:
            if args.ledger is None or args.credential_file is None: raise EvaluationError('live_arguments_required')
            asyncio.run(run_plan(plan, args.output, args.credential_file, args.authorize_live, ledger_path=args.ledger))
    except BaseException:
        print('evaluation_failed'); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
