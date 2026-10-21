"""Bounded synthetic Jev probe of the original assignment graph, never native use.

The graph owns all routing and permits. Controlled candidate/composer/validator
ports exercise a ready path and one actionable repair, with no owner side effect.
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
from types import SimpleNamespace

import httpx2
from ordessa_decision.definitions import (TaskBrief, RunLimits, DecisionRequest,
    DecisionServices, ReadContext, ProposalCandidateBatch, ValidationReceipt,
    ObligationResult, ExternalRef, FlowRef, digest, plain, freeze)
from assignment_source.offline import offline_case, OfflineCandidates
from assignment_source.build import build_assignment_flow, load_assignment_policy
from assignment_source.task_gate import compile_task_gate
from assignment_source.selection import validate_policy
from assignment_source.proposals import check_proposal_basis
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision.runtime import run_decision, reviewed_code_digest, flow_digest

_spec = importlib.util.spec_from_file_location('reference_probe_live_helpers', Path(__file__).with_name('live_acceptance.py'))
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)
EvaluationError = live.EvaluationError
STAMP = '2026-10-05T00:00:00Z'
CASE_IDS = ('reference-ready', 'reference-repair')
DEFAULT_EXPECTED = {CASE_IDS[0]: {'disposition':'ready','compose':1,'validate':1,'repair_rounds':0},
    CASE_IDS[1]: {'disposition':'ready','compose':2,'validate':2,'repair_rounds':1}}


def _fixture(task, policy):
    """Reuse existing fixture shapes; replace clock/input identities before freeze."""
    _, _, services = offline_case(action='reuse')
    candidate = services.candidate_source.candidates[0]
    candidate = replace(candidate, observation=replace(candidate.observation, observed_at=STAMP))
    draft = services.proposal_source.proposals[0]
    conditions = tuple(replace(p, subject_ref=ExternalRef('task', {'id': task.task_id,
        'revision': task.task_revision}), expected_version=task.task_revision)
        if p.condition_id == 'task_revision' else p for p in draft.preconditions)
    draft = replace(draft, preconditions=conditions)
    repaired = replace(draft, proposal_id='controlled-repaired',
        payload={**plain(draft.payload), 'configuration': {'ratio': 0.8}})
    return candidate, (draft, repaired)


def validate(plan):
    """All static inputs are checked before credential access or HTTP reservation."""
    try:
        if set(plan) - {'expected'} != {'version', 'synthetic_only', 'scope_id', 'settings', 'limits', 'task', 'policy'}:
            raise ValueError()
        if plan['version'] != 'jev-reference-flow/1' or plan['synthetic_only'] is not True:
            raise ValueError()
        scope = plan['scope_id']
        if type(scope) is not str or not scope or len(scope) > 128: raise ValueError()
        expected = plan.get('expected', DEFAULT_EXPECTED)
        if set(expected) != set(CASE_IDS): raise ValueError()
        for row in expected.values():
            if (set(row) != {'disposition','compose','validate','repair_rounds'}
                    or row['disposition'] not in ('ready','clarify','revise','blocked')
                    or any(type(row[k]) is not int or not 0 <= row[k] <= maximum
                           for k,maximum in [('compose',2),('validate',2),('repair_rounds',1)])
                    or (row['disposition'] != 'ready' and any(row[k] for k in ('compose','validate','repair_rounds')))):
                raise ValueError()
        settings = JevProviderSettings(**plan['settings'])
        if (settings.base_url + '/v1/systemone' != live.ENDPOINT or settings.model != 'jev-1.13-free'
                or settings.accepted_response_models != ('jev-1.13-free',)
                or settings.timeout_seconds > 30): raise ValueError()
        bounds = plan['limits']
        if set(bounds) != {'max_http_requests', 'max_model_attempts', 'wall_timeout_seconds', 'case_timeout_seconds'}:
            raise ValueError()
        for key in ('max_http_requests', 'max_model_attempts'):
            if type(bounds[key]) is not int or not 12 <= bounds[key] <= 16: raise ValueError()
        for key in ('wall_timeout_seconds', 'case_timeout_seconds'):
            value = bounds[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 90: raise ValueError()
        task = TaskBrief.from_dict(plan['task'])
        policy = freeze(plan['policy'])
        # Keep the controlled fixture's native check catalogue, never invent owner semantics.
        base = load_assignment_policy()
        if policy['selection'] != base['selection']: raise ValueError()
        validate_policy(policy['selection'])
        flow = build_assignment_flow(policy)
        code = digest('flow', {'original_graph_code': flow.reviewed_code_digest,
            'probe_code': reviewed_code_digest(__file__, Path(__file__).with_name('live_acceptance.py')),
            'frozen_plan': digest('policy', plan)})
        flow = replace(flow, ref=FlowRef('agent.assignment.synthetic-reference', '1',
            flow_digest(code, flow.policy_refs)), reviewed_code_digest=code, review_ref=scope)
        flow.validate()
        limits = RunLimits(max_model_attempts=bounds['max_model_attempts'], max_node_entries=40,
            max_repair_rounds=1, max_inflight_model_calls=1,
            wall_timeout_seconds=bounds['case_timeout_seconds'], cleanup_timeout_seconds=2)
        context = SimpleNamespace(services=SimpleNamespace(policy=policy, policy_refs=flow.policy_refs))
        gate = compile_task_gate(task, context, policy['task_gate'])
        if gate.hard_result is not None or len(gate.questions) != 6: raise ValueError()
        for question in gate.questions: JevDecisionProvider._map_question(question)
        candidate, drafts = _fixture(task, policy)
        for draft in drafts:
            check_proposal_basis(draft, candidate, task, policy['selection']['required_checks']['reuse'],
                policy['selection']['required_validation']['reuse'])
        requests = tuple(DecisionRequest(cid, task, flow.ref, limits) for cid in CASE_IDS)
        return settings, policy, flow, gate, candidate, drafts, requests
    except Exception:
        raise EvaluationError('plan_invalid') from None


def prepare(plan):
    settings, policy, flow, gate, candidate, drafts, requests = validate(plan)
    return {'status': 'PREPARED_NOT_RUN', 'input_hash': digest('policy', plan),
        'scope_id': plan['scope_id'], 'credential_reads': 0, 'real_model_requests': 0,
        'maximum_http_requests': 12, 'graph': 'original build_assignment_flow',
        'fixture_scope': 'controlled synthetic candidate/composer/validator; non-native',
        'permit_scope': 'runtime only; single-use permit after durable call.intent ACK',
        'probe_source_digest': reviewed_code_digest(__file__, Path(__file__).with_name('live_acceptance.py')),
        'flow': plain(flow.ref), 'policy_refs': plain(flow.policy_refs),
        'settings': plain(settings.__dict__), 'plan': plain(plan),
        'questions': plain(gate.questions), 'candidate': plain(candidate), 'drafts': plain(drafts),
        'requests': plain(requests),
        'expected': plain(plan.get('expected', DEFAULT_EXPECTED)),
        'controlled_rejection': {'code': 'configuration_ratio_revision_required', 'new_ratio': 0.8}}


class FrozenQuestions(live.RecordedProvider):
    """Refuse any unplanned question before entering the SDK; runtime owns permit."""
    def __init__(self, provider, row, save, questions):
        super().__init__(provider, row, save)
        self.question_digests = tuple(q.question_digest for q in questions)
    async def decide(self, question, context):
        index = len(self.row['answers'])
        if index >= len(self.question_digests) or question.question_digest != self.question_digests[index]:
            raise EvaluationError('unplanned_question')
        return await super().decide(question, context)


class ControlledComposer:
    def __init__(self, drafts, row, save): self.drafts, self.row, self.save = drafts, row, save
    async def compose(self, task, refs, offers, constraints, feedback, context):
        calls = self.row['compose_calls']; actual = plain(constraints['feedback'])
        index = len(calls)
        if index > 1 or (index == 1 and (not actual or actual['issue_codes'] != ['configuration_ratio_revision_required'])):
            raise EvaluationError('controlled_feedback_invalid')
        calls.append({'feedback': actual, 'proposal_digest': self.drafts[index].proposal_digest})
        self.save()
        return ProposalCandidateBatch((self.drafts[index],), True)


class ControlledValidator:
    def __init__(self, reject_first, row, save): self.reject_first, self.row, self.save = reject_first, row, save
    async def validate(self, draft, basis, context):
        invalid = self.reject_first and not self.row['validate_calls']
        self.row['validate_calls'].append({'proposal_digest': draft.proposal_digest,
            'status': 'invalid' if invalid else 'valid', 'scope': 'controlled_non_native'})
        self.save()
        return ValidationReceipt('controlled.reference', '1', draft.proposal_digest,
            'invalid' if invalid else 'valid', tuple(ObligationResult(o.obligation_id, 'failed' if invalid else 'passed',
                o.validator_kind, o.version_constraint, {'descriptor': '1'}, ('controlled-only',))
                for o in draft.required_validation_obligations), STAMP, 'controlled_non_native',
            issues=({'code': 'configuration_ratio_revision_required'},) if invalid else ())


async def run_plan(plan, output, credential_file, authorize_live=False, *, ledger_path, transport=None):
    settings, policy, original, gate, candidate, drafts, requests = validate(plan)
    frozen = prepare(plan)
    if not authorize_live: raise EvaluationError('live_authorization_required')
    if ledger_path is None: raise EvaluationError('scope_ledger_required')
    output = Path(output); ledger = live.ScopeLedger(ledger_path, plan)
    if any(cid in ledger.data['cases'] for cid in CASE_IDS):
        ledger.close(); raise EvaluationError('case_already_claimed')
    receipt = {**frozen, 'status': 'IN_PROGRESS', 'rows': [
        {'id': cid, 'answers': [], 'compose_calls': [], 'validate_calls': [],
         'quality_pass': False, 'graph_trace': [], 'technical_status': 'NOT_RUN'} for cid in CASE_IDS],
        'native_effects': 0, 'retry': 0,
        'cost': 'UNKNOWN', 'evaluation_mode': 'live_https' if transport is None else 'injected_test_transport'}
    def save(): live.atomic_write(output / 'receipt.json', receipt)
    start = time.monotonic(); deadline = start + plan['limits']['wall_timeout_seconds']
    provider = sink = None
    try:
        live.atomic_write(output / 'frozen-inputs.json', frozen); save()
        # Validate durable evidence construction before reading credentials.
        (output / 'durable').mkdir(parents=True, exist_ok=True, mode=0o700)
        context = ReadContext(object(), 'controlled-reference-graph')
        sink = FileEvidenceSink(output / 'durable', read_context=context)
        receipt['credential_reads'] += 1; save()
        key = Path(credential_file).read_text().strip()
        if not key or '\n' in key: raise EvaluationError('credential_invalid')
        audited = live.AuditedTransport(transport or httpx2.AsyncHTTPTransport(retries=0), ledger, deadline)
        provider = JevDecisionProvider(settings, secret_resolver=lambda _: key, transport=audited)
        for request, row in zip(requests, receipt['rows']):
            if time.monotonic() >= deadline: row['error'] = 'global_deadline'; save(); continue
            ledger.begin(request.request_id); audited.case_id = request.request_id
            state = original.new_state(request)
            flow = replace(original, new_state=lambda _: state)  # Observe original state; no graph/routing edit.
            recorded = FrozenQuestions(provider, row, save, gate.questions)
            services = DecisionServices(None, OfflineCandidates((candidate,)),
                ControlledComposer(drafts, row, save),
                ControlledValidator(request.request_id == CASE_IDS[1], row, save),
                recorded, sink, policy, context, flow.policy_refs, mode='real')
            try:
                async with asyncio.timeout_at(deadline):
                    result = await run_decision(request, flow=flow, services=services)
                row.update(run_id=result.run_id, technical_status=result.status,
                    result=plain(result), result_digest=digest('result', result))
                await live.verify_terminal(sink, result, context)
                row['terminal_verified'] = True
                expected = frozen['expected'][request.request_id]
                row['quality_pass'] = (result.status == 'completed' and result.outcome.disposition == expected['disposition']
                    and len(row['compose_calls']) == expected['compose'] and len(row['validate_calls']) == expected['validate']
                    and result.consumed['repair_rounds'] == expected['repair_rounds']
                    and len(row['answers']) == 6 and (expected['disposition'] != 'ready'
                        or all(a['value'] == 'pass' for a in row['answers'])))
                row['quality_source'] = 'model_with_controlled_ports' if transport is None else 'controlled_transport'
            except TimeoutError as error:
                row.update(technical_status='TIMEOUT_UNKNOWN', error='global_deadline_unknown')
                run_id = getattr(error.__cause__, 'run_id', None)
                if run_id: row['run_id'] = run_id
            except asyncio.CancelledError as error:
                row.update(technical_status='CANCELLED', error='cancelled_unknown')
                if getattr(error, 'run_id', None): row['run_id'] = error.run_id
                raise
            except Exception:
                row.update(collection_error='collection_failed', quality_pass=False)
            finally:
                row['graph_trace'] = list(state.trace); save()
        receipt['status'] = 'SCOPED_PASS' if all(r['quality_pass'] for r in receipt['rows']) else 'PARTIAL'
    except asyncio.CancelledError:
        receipt['status'] = 'PARTIAL'; raise
    except Exception:
        receipt['status'] = 'PARTIAL'; raise EvaluationError('evaluation_failed') from None
    finally:
        receipt.update(elapsed_seconds=round(time.monotonic()-start, 4), http_audit=ledger.data['requests'],
            transport_attempts=len(ledger.data['requests']),
            real_model_requests=len(ledger.data['requests']) if transport is None else 0,
            actual_http_requests=len(ledger.data['requests']) if transport is None else 0,
            model_quality_passes=sum(r['quality_pass'] for r in receipt['rows']) if transport is None else 0,
            controlled_label_matches=sum(r['quality_pass'] for r in receipt['rows']) if transport is not None else 0)
        receipt['usage'] = [a['usage_evidence'] for r in receipt['rows'] for a in r['answers']]
        receipt['usage_unknown_requests'] = max(0, len(ledger.data['requests'])-
            sum(u.get('status') == 'reported' for u in receipt['usage']))
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
    parser.add_argument('--authorize-live', action='store_true')
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        if args.mode == 'prepare': live.atomic_write(args.output / 'prepared.json', prepare(plan))
        else:
            if args.ledger is None or args.credential_file is None: raise EvaluationError('live_arguments_required')
            asyncio.run(run_plan(plan, args.output, args.credential_file, args.authorize_live, ledger_path=args.ledger))
    except BaseException:
        print('evaluation_failed'); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
