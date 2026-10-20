"""Synthetic rank diagnostic through the original assignment graph and SDK.

Preparation runs that graph offline to capture its actual questions. No copied
ranking compiler, real owner capability or economic facts are introduced here.
"""
import argparse
import asyncio
from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time

import httpx2
from decision_runtime.definitions import (TaskBrief, ProposalDraft, ProposalCandidateBatch,
    DecisionRequest, DecisionAnswer, DecisionServices, ReadContext, RunLimits, FlowRef,
    digest, plain, freeze)
from assignment_source.build import build_assignment_flow, load_assignment_policy
from assignment_source.proposals import check_proposal_basis
from assignment_source.selection import validate_policy
from assignment_source.offline import OfflineCandidates
from decision_runtime.evidence import FileEvidenceSink, MemoryEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from decision_runtime.runtime import run_decision, reviewed_code_digest, flow_digest

_spec = importlib.util.spec_from_file_location('rank_reference_helpers', Path(__file__).with_name('reference_flow_probe.py'))
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)
live = reference.live
EvaluationError = live.EvaluationError


def validate(plan):
    try:
        if set(plan) != {'version', 'synthetic_only', 'scope_id', 'settings', 'limits', 'task', 'policy', 'proposals', 'expected'}:
            raise ValueError()
        if plan['version'] != 'jev-rank-flow/1' or plan['synthetic_only'] is not True: raise ValueError()
        if type(plan['scope_id']) is not str or not plan['scope_id'] or len(plan['scope_id']) > 128: raise ValueError()
        settings = JevProviderSettings(**plan['settings'])
        if (settings.base_url + '/v1/systemone' != live.ENDPOINT or settings.model != 'jev-1.13-free'
                or settings.accepted_response_models != ('jev-1.13-free',) or settings.timeout_seconds > 30): raise ValueError()
        bounds = plan['limits']
        if set(bounds) != {'max_http_requests', 'max_model_attempts', 'wall_timeout_seconds'}: raise ValueError()
        for key in ('max_http_requests', 'max_model_attempts'):
            if type(bounds[key]) is not int or not 7 <= bounds[key] <= 16: raise ValueError()
        wall = bounds['wall_timeout_seconds']
        if type(wall) not in (int, float) or not math.isfinite(wall) or not 0 < wall <= 90: raise ValueError()
        task = TaskBrief.from_dict(plan['task']); policy = freeze(plan['policy'])
        selection = validate_policy(policy['selection'])
        baseline = plain(load_assignment_policy()['selection'])
        baseline['rank_instructions'] = selection['rank_instructions']
        if plain(selection) != baseline: raise ValueError()
        candidate, _ = reference._fixture(task, policy)
        drafts = tuple(ProposalDraft.from_dict(p) for p in plan['proposals'])
        if not 2 <= len(drafts) <= 4 or len({p.proposal_digest for p in drafts}) != len(drafts): raise ValueError()
        for draft in drafts:
            check_proposal_basis(draft, candidate, task, selection['required_checks']['reuse'], selection['required_validation']['reuse'])
        expected = plan['expected']
        if set(expected) != {'disposition', 'selected_proposal_digest', 'rank_value'}: raise ValueError()
        if expected['disposition'] == 'ready':
            index = next(i for i, d in enumerate(drafts) if d.proposal_digest == expected['selected_proposal_digest'])
            if expected['rank_value'] != 'proposal_' + str(index): raise ValueError()
        elif expected['disposition'] == 'clarify':
            if expected['selected_proposal_digest'] is not None or expected['rank_value'] not in ('none_suitable', 'insufficient_evidence', 'tie'): raise ValueError()
        else: raise ValueError()
        original = build_assignment_flow(policy)
        code = digest('flow', {'original_graph_code': original.reviewed_code_digest,
            'probe_helpers': reviewed_code_digest(__file__, Path(__file__).with_name('reference_flow_probe.py'),
                Path(__file__).with_name('live_acceptance.py')), 'plan': digest('policy', plan)})
        flow = replace(original, ref=FlowRef('agent.assignment.synthetic-rank', '1', flow_digest(code, original.policy_refs)),
            reviewed_code_digest=code, review_ref=plan['scope_id'])
        flow.validate()
        limits = RunLimits(max_model_attempts=bounds['max_model_attempts'], max_node_entries=40,
            max_repair_rounds=0, max_inflight_model_calls=1, wall_timeout_seconds=wall, cleanup_timeout_seconds=2)
        request = DecisionRequest('rank', task, flow.ref, limits)
        return settings, policy, candidate, drafts, flow, request
    except Exception:
        raise EvaluationError('plan_invalid') from None


class Composer:
    def __init__(self, drafts, row, save): self.drafts, self.row, self.save = drafts, row, save
    async def compose(self, *args):
        if self.row['compose_calls']: raise EvaluationError('unexpected_composition')
        self.row['compose_calls'].append({'proposal_digests': [d.proposal_digest for d in self.drafts], 'scope': 'controlled_non_native'})
        self.save()
        return ProposalCandidateBatch(self.drafts, True)


class CaptureProvider:
    binding_ref = 'controlled-question-capture'
    settings_digest = digest('descriptor', {'provider': 'controlled-question-capture'})
    def __init__(self): self.questions = []
    async def decide(self, question, context):
        context.claim(question, self.settings_digest)
        self.questions.append(question)
        value = 'proposal_0' if question.question_id == 'assignment.rank' else 'pass'
        return DecisionAnswer(question.question_id, 'choice', value, {'selection_status': 'unique', 'scope': 'offline_capture_only'})


def _services(policy, candidate, drafts, provider, sink, context, flow, row, save, mode):
    return DecisionServices(None, OfflineCandidates((candidate,)), Composer(drafts, row, save),
        reference.ControlledValidator(False, row, save), provider, sink, policy, context, flow.policy_refs, mode=mode)


async def prepare(plan):
    settings, policy, candidate, drafts, flow, request = validate(plan)
    provider = CaptureProvider(); context = ReadContext(object(), 'offline-rank-capture')
    sink = MemoryEvidenceSink(read_context=context)
    state = flow.new_state(request); flow = replace(flow, new_state=lambda _: state)
    row = {'compose_calls': [], 'validate_calls': []}
    services = _services(policy, candidate, drafts, provider, sink, context, flow, row, lambda: None, 'offline')
    try:
        result = await run_decision(request, flow=flow, services=services)
    finally:
        await sink.close()
    if (result.status != 'completed' or result.outcome.disposition != 'ready'
            or len(provider.questions) != 7 or provider.questions[-1].question_id != 'assignment.rank'
            or any(not q.question_id.startswith('task-gate.') for q in provider.questions[:-1])):
        raise EvaluationError('rank_capture_failed')
    for question in provider.questions: JevDecisionProvider._map_question(question)
    return {'status': 'PREPARED_NOT_RUN', 'input_hash': digest('policy', plan), 'scope_id': plan['scope_id'],
        'plan': plain(plan), 'flow': plain(flow.ref), 'reviewed_code_digest': flow.reviewed_code_digest,
        'policy_refs': plain(flow.policy_refs),
        'request': plain(request), 'candidate': plain(candidate), 'proposals': plain(drafts),
        'questions': plain(provider.questions), 'question_digests': [q.question_digest for q in provider.questions],
        'preparation_graph_trace': list(state.trace), 'preparation_model_attempts': 7,
        'preparation_quality': 'not_evaluated; controlled offline capture only',
        'fixture_scope': 'controlled synthetic candidate/composer/validator; non-native',
        'maximum_http_requests': 7, 'credential_reads': 0, 'real_model_requests': 0}


async def run_plan(plan, output, credential_file, authorize_live=False, *, ledger_path, transport=None):
    settings, policy, candidate, drafts, flow, request = validate(plan)
    frozen = await prepare(plan)
    if not authorize_live: raise EvaluationError('live_authorization_required')
    if ledger_path is None: raise EvaluationError('scope_ledger_required')
    ledger = live.ScopeLedger(ledger_path, plan)
    if 'rank' in ledger.data['cases']:
        ledger.close(); raise EvaluationError('case_already_claimed')
    output = Path(output)
    row = {'id': 'rank', 'answers': [], 'compose_calls': [], 'validate_calls': [],
        'graph_trace': [], 'quality_pass': False, 'technical_status': 'NOT_RUN'}
    receipt = {**frozen, 'status': 'IN_PROGRESS', 'rows': [row], 'native_effects': 0, 'retry': 0,
        'cost': 'UNKNOWN', 'evaluation_mode': 'live_https' if transport is None else 'injected_test_transport'}
    def save(): live.atomic_write(output / 'receipt.json', receipt)
    start = time.monotonic(); deadline = start + request.limits.wall_timeout_seconds
    provider = sink = None; state = flow.new_state(request)
    try:
        live.atomic_write(output / 'frozen-inputs.json', frozen); save()
        (output / 'durable').mkdir(parents=True, exist_ok=True, mode=0o700)
        context = ReadContext(object(), 'controlled-rank-graph')
        sink = FileEvidenceSink(output / 'durable', read_context=context)
        receipt['credential_reads'] += 1; save()
        key = Path(credential_file).read_text().strip()
        if not key or '\n' in key: raise EvaluationError('credential_invalid')
        audited = live.AuditedTransport(transport or httpx2.AsyncHTTPTransport(retries=0), ledger, deadline)
        provider = JevDecisionProvider(settings, secret_resolver=lambda _: key, transport=audited)
        ledger.begin('rank'); audited.case_id = 'rank'
        from decision_runtime.definitions import DecisionQuestion
        questions = tuple(DecisionQuestion.from_dict(q) for q in frozen['questions'])
        recorded = reference.FrozenQuestions(provider, row, save, questions)
        flow = replace(flow, new_state=lambda _: state)
        services = _services(policy, candidate, drafts, recorded, sink, context, flow, row, save, 'real')
        async with asyncio.timeout_at(deadline):
            result = await run_decision(request, flow=flow, services=services)
        row.update(run_id=result.run_id, technical_status=result.status, result=plain(result), result_digest=digest('result', result))
        await live.verify_terminal(sink, result, context); row['terminal_verified'] = True
        expected = plan['expected']
        selected = result.outcome.proposals[0].proposal_digest if result.status == 'completed' and result.outcome.proposals else None
        rank = row['answers'][-1] if len(row['answers']) == 7 else None
        value = ('tie' if rank['provider_receipt'].get('selection_status') == 'tie' else rank['value']) if rank else None
        row.update(selected_proposal_digest=selected, rank_value=value)
        row['quality_pass'] = (result.status == 'completed' and result.outcome.disposition == expected['disposition']
            and selected == expected['selected_proposal_digest'] and value == expected['rank_value']
            and len(row['answers']) == 7 and all(a['value'] == 'pass' for a in row['answers'][:6])
            and len(row['compose_calls']) == 1 and len(row['validate_calls']) == (1 if expected['disposition'] == 'ready' else 0))
        receipt['status'] = 'SCOPED_PASS' if row['quality_pass'] else 'PARTIAL'
    except TimeoutError as error:
        receipt['status'] = 'PARTIAL'; row.update(technical_status='TIMEOUT_UNKNOWN', error='global_deadline_unknown')
        if getattr(error.__cause__, 'run_id', None): row['run_id'] = error.__cause__.run_id
    except asyncio.CancelledError as error:
        receipt['status'] = 'PARTIAL'; row.update(technical_status='CANCELLED', error='cancelled_unknown')
        if getattr(error, 'run_id', None): row['run_id'] = error.run_id
        raise
    except Exception:
        receipt['status'] = 'PARTIAL'; row['collection_error'] = 'collection_failed'
    finally:
        row['graph_trace'] = list(state.trace)
        receipt.update(elapsed_seconds=round(time.monotonic()-start, 4), http_audit=ledger.data['requests'],
            transport_attempts=len(ledger.data['requests']), actual_http_requests=len(ledger.data['requests']) if transport is None else 0,
            real_model_requests=len(ledger.data['requests']) if transport is None else 0,
            model_quality_passes=int(row['quality_pass']) if transport is None else 0,
            controlled_label_matches=int(row['quality_pass']) if transport is not None else 0)
        receipt['usage'] = [a['usage_evidence'] for a in row['answers']]
        receipt['usage_unknown_requests'] = max(0, len(ledger.data['requests'])-sum(u.get('status') == 'reported' for u in receipt['usage']))
        try: save()
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
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ledger', type=Path); parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--authorize-live', action='store_true'); args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        if args.mode == 'prepare': live.atomic_write(args.output / 'prepared.json', asyncio.run(prepare(plan)))
        else:
            if args.ledger is None or args.credential_file is None: raise EvaluationError('live_arguments_required')
            asyncio.run(run_plan(plan, args.output, args.credential_file, args.authorize_live, ledger_path=args.ledger))
    except BaseException:
        print('evaluation_failed'); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
