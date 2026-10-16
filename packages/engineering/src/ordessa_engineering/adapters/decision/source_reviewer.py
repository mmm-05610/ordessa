"""Source review through public Decision services and their original evidence.

The host explicitly selects the scoped reviewer, roles and Decision services.
A model answer or a wire receipt cannot make that selection or authenticate
itself. This adapter owns no Decision run state and never calls a Unit.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256

from decision_runtime import (BusinessOutcome, DecisionAnswer, DecisionQuestion,
    DecisionRequest, DecisionResult, DecisionServices, FlowRef, PolicyRef, RunContext,
    RunLimits, RunManifest,
    TaskBrief, TrustedFlow, flow_digest, reviewed_code_digest, run_decision)
from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ...application.contracts.commands import CommandContext
from ...application.contracts.errors import ApplicationError
from ...application.contracts.reviewer_admission import CriterionAnswer, VerifiedReviewResponse
from ...application.usecases.reviews.admission import review_observations
from ...domain.common.models.identity import ActorRef, Scope
from ...domain.common.models.values import Digest
from ...domain.artifacts.provenance import SourceRef, VersionCapture
from ...domain.artifacts.provenance_codec import decode_source
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.reviews.evidence import VerifiedReviewerEvidence
from ...domain.reviews.models import CurrentReviewTrust, observations_digest

_V2_CHECK_IDS = (
    'source-version-preservation', 'scoped-read-boundary', 'evidence-support',
    'unique-record-authority', 'public-call-chain', 'changed-source-refusal',
    'acceptance-coverage', 'declared-limitations',
)


def _wait(coroutine):
    """Bridge the synchronous Engineering source port to the public async reader."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result(timeout=10)


def _flow(questions, policy, *, contract_version='1'):
    if isinstance(questions, DecisionQuestion):
        questions = (questions,)
    from pydantic_graph import GraphBuilder
    builder = GraphBuilder(name=f'engineering.source-review/{contract_version}', state_type=dict,
        deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome,
        auto_instrument=False)

    @builder.step(node_id='review-explicit-sources')
    async def review(ctx):
        await ctx.deps.enter_node('review-explicit-sources')
        issues = []
        for question in questions:
            answer = await ctx.deps.gateway.decide(question)
            issues.append({'code':'source-review-answer', 'check_id':question.question_id,
                           'answer':answer.to_dict()})
        return BusinessOutcome('revise', issues=tuple(issues))

    builder.add(builder.edge_from(builder.start_node).to(review))
    builder.add(builder.edge_from(review).to(builder.end_node))
    code = reviewed_code_digest(__file__)
    ref = FlowRef('engineering.source-review', contract_version, flow_digest(code, (policy,)))
    return TrustedFlow(ref, builder.build(), lambda request: {}, (policy,), code,
                       f'engineering-source-review-public-decision/{contract_version}')


def _verified_native_result(native, run_id, request, flow, provider_binding):
    """Authenticate the public reader projection against this exact run selection."""
    if (not isinstance(native, Mapping) or native.get('status') != 'completed'
            or native.get('call_evidence') != 'recorded'):
        raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE')
    terminal = native.get('terminal')
    events = native.get('events')
    if (not isinstance(terminal, Mapping) or not isinstance(events, (tuple, list))
            or not events or not isinstance(events[0], Mapping)):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    started = events[0].get('payload')
    raw_result = terminal.get('result')
    try:
        manifest = RunManifest(request.request_digest, flow.ref, flow.policy_refs,
            request.limits, provider_binding)
        result = DecisionResult.from_dict(raw_result)
    except Exception:
        raise ApplicationError('REVIEW_SOURCE_INVALID') from None
    terminal_digest = terminal.get('terminal_digest', terminal.get('result_digest'))
    if (not isinstance(started, Mapping)
            or started.get('type') != 'run.started'
            or started.get('run_id') != run_id
            or started.get('request_digest') != request.request_digest
            or started.get('flow_digest') != flow.ref.content_digest
            or started.get('manifest_digest') != manifest.manifest_digest
            or terminal.get('run_id') != run_id
            or terminal.get('status') != 'completed'
            or result.status != 'completed'
            or result.run_id != run_id
            or result.request_id != request.request_id
            or result.task_revision != request.task.task_revision
            or result.flow_ref != flow.ref
            or result.run_manifest_digest != manifest.manifest_digest
            or result.effective_policy_refs != tuple(flow.policy_refs)
            or ('result_digest' in terminal and terminal.get('result_digest') != terminal_digest)
            or terminal_digest != result.result_digest):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    return result


class DecisionReviewerSource:
    def __init__(self, factory, blobs, method_guard, source_materials, bindings, *,
                 scope: Scope, principal_id: str, reviewer: ActorRef,
                 roles: tuple[str, ...], services: DecisionServices, trust_version: int = 1):
        if (type(scope) is not Scope or type(reviewer) is not ActorRef
                or type(principal_id) is not str or not principal_id
                or type(roles) is not tuple or not roles or len(set(roles)) != len(roles)
                or type(trust_version) is not int or trust_version < 1
                or type(services) is not DecisionServices or services.mode != 'real'
                or services.evidence.durable is not True
                or any(getattr(port, 'factory', None) is not factory
                       for port in (method_guard, source_materials, bindings))
                or getattr(blobs, 'library', None) is not getattr(factory, 'library', None)):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        self.factory, self.blobs = factory, blobs
        self.method_guard, self.materials, self.bindings = method_guard, source_materials, bindings
        self.scope, self.principal_id = scope, principal_id
        self.reviewer, self.roles, self.services = reviewer, roles, services
        self.trust_version = trust_version
        self._reviewer_selection = (reviewer, roles, trust_version)
        self._provider = (services.decision_provider.binding_ref,
                          services.decision_provider.settings_digest)
        self._lock, self._active = threading.RLock(), True

    def _check(self, context):
        if (not self._active or type(context) is not CommandContext
                or context.scope != self.scope or context.principal_id != self.principal_id
                or self._reviewer_selection != (self.reviewer, self.roles, self.trust_version)
                or self._provider != (self.services.decision_provider.binding_ref,
                                       self.services.decision_provider.settings_digest)):
            raise ApplicationError('UNTRUSTED_REVIEWER')

    def _inputs(self, context, plan, request_version, fence):
        self._check(context)
        selected = self.bindings.review_inputs(context, plan)
        policy = selected['policy']
        if tuple(policy['reviewer_roles']) != self.roles:
            raise ApplicationError('UNTRUSTED_REVIEWER')
        source_inputs = []
        for target in plan.requirement.expected_targets.targets:
            ref = target.ref.source_ref
            raw = self.materials.read(context, ref)
            if type(raw) is not bytes or len(raw) > 65536:
                raise ApplicationError('REVIEW_INPUT_LIMIT')
            if policy.get('contract') == 'engineering-source-review/2':
                self._verify_material_bytes(ref, raw)
            try:
                text = raw.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                raise ApplicationError('REVIEW_SOURCE_INVALID') from None
            source_inputs.append({'role':target.role, 'source_ref':asdict(ref), 'text':text})
        binding_ref = next(ref for ref in selected['refs']
                           if ref.resource_id == self.bindings.binding_resource_id)
        v2 = policy.get('contract') == 'engineering-source-review/2'
        policy_ref = PolicyRef(binding_ref.resource_id, '2' if v2 else '1',
                               'sha256:' + binding_ref.resource_digest.hex)
        options = {key:value['description'] for key, value in policy['options'].items()}
        if v2:
            if selected.get('caller_input_schema') is None or type(selected.get('caller_materials_ref')) is not SourceRef:
                raise ApplicationError('REVIEW_INPUT_MISSING')
            caller_raw = self.materials.read(context, selected['caller_materials_ref'])
            if type(caller_raw) is not bytes or len(caller_raw) > 262144:
                raise ApplicationError('REVIEW_INPUT_LIMIT')
            self._verify_material_bytes(selected['caller_materials_ref'], caller_raw)
            try:
                caller = self._strict_json(caller_raw)
            except Exception:
                raise ApplicationError('REVIEW_INPUT_INVALID') from None
            if not self._validate_method_schema(selected, selected['caller_input_schema'], caller):
                raise ApplicationError('REVIEW_INPUT_INVALID')
            if (caller.get('scope') != asdict(context.scope)
                    or not self._matches_exact_source(self.bindings.baseline, caller.get('baseline'))
                    or not self._matches_exact_source(self.bindings.candidate, caller.get('candidate'))):
                raise ApplicationError('REVIEW_INPUT_SOURCE_MISMATCH')
            checks = caller.get('checks')
            if (type(checks) is not list or len(checks) != len(_V2_CHECK_IDS)
                    or any(type(item) is not dict for item in checks)
                    or tuple(item.get('check_id') for item in checks) != _V2_CHECK_IDS):
                raise ApplicationError('REVIEW_INPUT_INCOMPLETE')
            questions = []
            validated = []
            for item in checks:
                if (set(item) != {'check_id', 'claim', 'evidence'}
                        or type(item['claim']) is not str or not item['claim'].strip()
                        or type(item['evidence']) is not list or not item['evidence']):
                    raise ApplicationError('REVIEW_INPUT_INVALID')
                evidence = []
                for entry in item['evidence']:
                    if (type(entry) is not dict or set(entry) != {'source_ref', 'excerpt'}
                            or type(entry['excerpt']) is not str or not entry['excerpt'].strip()):
                        raise ApplicationError('REVIEW_INPUT_INVALID')
                    source_ref = self._decode_exact_source(entry['source_ref'])
                    raw = self.materials.read(context, source_ref)
                    if type(raw) is not bytes or len(raw) > 65536:
                        raise ApplicationError('REVIEW_INPUT_LIMIT')
                    self._verify_material_bytes(source_ref, raw)
                    try:
                        captured = raw.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        raise ApplicationError('REVIEW_INPUT_SOURCE_INVALID') from None
                    if entry['excerpt'] not in captured:
                        raise ApplicationError('REVIEW_INPUT_EXCERPT_MISMATCH')
                    evidence.append({'source_ref':asdict(source_ref), 'excerpt':entry['excerpt']})
                checked = {'check_id':item['check_id'], 'claim':item['claim'], 'evidence':evidence}
                validated.append(checked)
                state = {'scope':asdict(context.scope), 'method_ref':asdict(plan.requirement.method_ref),
                    'plan_digest':asdict(plan.plan_digest), 'engineering_request_version':request_version,
                    'engineering_request_fence':fence, 'sources':source_inputs,
                    'required_check':next(c for c in policy['required_checks'] if c['check_id'] == item['check_id']),
                    'caller_claim':item['claim'], 'caller_evidence':evidence,
                    'caller_materials_ref':asdict(selected['caller_materials_ref']),
                    'criteria':selected['criteria'], 'instructions':selected['prompt']}
                question_spec = next(c for c in policy['required_checks'] if c['check_id'] == item['check_id'])
                questions.append(DecisionQuestion(item['check_id'], '1', 'choice', state,
                    question_spec['question_text'], options=options,
                    allowed_answer_ids=tuple(options),
                    evidence_ids=tuple('sha256:' + ref.capture.content_digest.hex for ref in
                        (self.bindings.baseline, self.bindings.candidate)), policy_ref=policy_ref))
            selected = dict(selected)
            selected['caller_checks'] = tuple(validated)
        else:
            state = {'scope':asdict(context.scope), 'method_ref':asdict(plan.requirement.method_ref),
                'plan_digest':asdict(plan.plan_digest), 'engineering_request_version':request_version,
                'engineering_request_fence':fence, 'sources':source_inputs,
                'criteria':selected['criteria'], 'instructions':selected['prompt']}
            questions = [DecisionQuestion(policy['criterion_id'], '1', 'choice', state,
                selected['prompt'], options=options, allowed_answer_ids=tuple(options),
                evidence_ids=tuple('sha256:' + ref.capture.content_digest.hex for ref in
                    (self.bindings.baseline, self.bindings.candidate)), policy_ref=policy_ref)]
        flow = _flow(tuple(questions), policy_ref, contract_version='2' if v2 else '1')
        request = DecisionRequest(plan.review_id + ':' + str(fence),
            TaskBrief(plan.review_id, str(request_version), 'Review the exact supplied change.',
                inputs=tuple(question.bounded_state for question in questions), boundaries=('explicit-source-pins-only',)), flow.ref,
            limits=RunLimits(max_model_attempts=len(questions), max_node_entries=1,
                             wall_timeout_seconds=240 if v2 else 30, cleanup_timeout_seconds=2))
        return selected, tuple(questions), flow, request

    @staticmethod
    def _strict_json(raw):
        import json
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs)
        if type(value) is not dict:
            raise ApplicationError('REVIEW_INPUT_INVALID')
        return value

    @staticmethod
    def _decode_exact_source(value):
        try:
            source_ref = decode_source(value)
        except Exception:
            raise ApplicationError('REVIEW_INPUT_SOURCE_INVALID') from None
        if asdict(source_ref) != value:
            raise ApplicationError('REVIEW_INPUT_SOURCE_INVALID')
        return source_ref

    @staticmethod
    def _matches_exact_source(expected, value):
        if type(expected) is not SourceRef:
            return False
        try:
            actual = DecisionReviewerSource._decode_exact_source(value)
        except ApplicationError:
            return False
        return asdict(expected) == asdict(actual)

    @staticmethod
    def _verify_material_bytes(ref, raw):
        if type(ref.capture) is not VersionCapture or len(raw) != ref.byte_length or sha256(raw).hexdigest() != ref.capture.content_digest.hex:
            raise ApplicationError('REVIEW_INPUT_SOURCE_MISMATCH')

    @staticmethod
    def _validate_method_schema(selected, schema, value):
        from jsonschema import Draft202012Validator
        from referencing import Registry
        from referencing.exceptions import NoSuchResource
        def no_retrieval(uri):
            raise NoSuchResource(ref=uri)
        registry = Registry(retrieve=no_retrieval)
        for uri, resource in selected.get('schema_documents', {}).items():
            registry = registry.with_resource(uri, resource)
        try:
            return Draft202012Validator(schema, registry=registry.crawl()).is_valid(value)
        except Exception:
            return False

    @staticmethod
    def _digest_uri(value):
        return value if value.startswith('sha256:') else 'sha256:' + value

    def _v2_projection(self, selected, questions, answer_by_id, run_id):
        checks = []
        inputs = {item['check_id']:item for item in selected['caller_checks']}
        for question in questions:
            check_id = question.question_id
            answer = answer_by_id[check_id]
            item = inputs[check_id]
            checks.append({
                'check_id':check_id, 'claim':item['claim'], 'evidence':item['evidence'],
                'native_run_ref':run_id,
                'question_digest':self._digest_uri(question.question_digest),
                'answer_digest':self._digest_uri(answer.answer_digest), 'choice':answer.value,
            })
        choices = [item['choice'] for item in checks]
        conclusion = ('not_passed' if 'not_passed' in choices else
                      'unknown' if 'unknown' in choices else 'passed')
        value = {'scope':asdict(self.scope), 'baseline':asdict(self.bindings.baseline),
                 'candidate':asdict(self.bindings.candidate), 'checks':checks,
                 'aggregate':{'policy':'all_required', 'conclusion':conclusion}}
        schema = selected['result_schema']
        props = schema.get('properties', {})
        if (set(value) != set(schema.get('required', ()))
                or set(value['aggregate']) != set(props.get('aggregate', {}).get('required', ()))
                or len(checks) != 8 or tuple(item['check_id'] for item in checks) != _V2_CHECK_IDS
                or any(set(item) != set(props['checks']['items']['required']) for item in checks)):
            raise ApplicationError('REVIEW_RESULT_SCHEMA_INVALID')
        if not self._validate_method_schema(selected, schema, value):
            raise ApplicationError('REVIEW_RESULT_SCHEMA_INVALID')
        return value

    async def run_review(self, context, plan, request_state):
        """Run once after the original Engineering review request is persisted.

        Cancellation/unknown evidence remains the native runner's result; callers
        reconcile its original evidence, never blindly repeat a model call.
        """
        with self._lock, self.method_guard.guard(context, plan.requirement.method_ref):
            if (request_state.scope != context.scope or request_state.review_id != plan.review_id
                    or request_state.state != 'requested'):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            selected, questions, flow, request = self._inputs(context, plan, request_state.version,
                                                              request_state.fence)
            from dataclasses import replace
            services = replace(self.services, policy_refs=flow.policy_refs)
            result = await run_decision(request, flow=flow, services=services)
            self._check(context)
            if result.status != 'completed':
                error = ApplicationError('DECISION_REVIEW_NOT_COMPLETED', retry='reconcile')
                error.decision_run_id = result.run_id
                error.decision_status = result.status
                raise error
            receipt = {'run_id':result.run_id, 'request_version':request_state.version,
                'fence':request_state.fence, 'request_digest':request.request_digest,
                'question_digest':questions[0].question_digest}
            if selected['policy'].get('contract') == 'engineering-source-review/2':
                issues = result.to_dict().get('outcome', {}).get('issues', [])
                if (not isinstance(issues, (tuple, list)) or len(issues) != len(questions)
                        or any(not isinstance(issue, Mapping) or issue.get('code') != 'source-review-answer'
                               for issue in issues)):
                    raise ApplicationError('REVIEW_SOURCE_INVALID')
                answer_by_id = {}
                try:
                    for issue in issues:
                        answer_by_id[issue['check_id']] = DecisionAnswer.from_dict(issue['answer'])
                except Exception:
                    raise ApplicationError('REVIEW_SOURCE_INVALID') from None
                if set(answer_by_id) != set(_V2_CHECK_IDS):
                    raise ApplicationError('REVIEW_SOURCE_INVALID')
                projection = self._v2_projection(selected, questions, answer_by_id, result.run_id)
                receipt = {'run_id':result.run_id, 'request_version':request_state.version,
                    'fence':request_state.fence, 'request_digest':request.request_digest,
                    'question_digests':{q.question_id:q.question_digest for q in questions},
                    'caller_materials_ref':asdict(selected['caller_materials_ref']),
                    'result':projection}
            raw = canonical_bytes(receipt)
            return self.blobs.put_verified(raw, Digest('sha256', sha256(raw).hexdigest()),
                                           'application/json')

    def _verified(self, context, plan, raw_ref):
        try:
            raw = self.blobs.read_verified(raw_ref)
            receipt = decode_json(raw)
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from None
        if type(receipt) is not dict:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        v2 = self.bindings.review_inputs(context, plan)['policy'].get('contract') == 'engineering-source-review/2'
        expected_receipt_fields = ({'run_id','request_version','fence','request_digest',
            'question_digests','caller_materials_ref','result'} if v2 else
            {'run_id','request_version','fence','request_digest','question_digest'})
        if set(receipt) != expected_receipt_fields:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        if (type(receipt['run_id']) is not str or not receipt['run_id']
                or type(receipt['request_version']) is not int or receipt['request_version'] < 0
                or type(receipt['fence']) is not int or receipt['fence'] < 1
                or type(receipt['request_digest']) is not str
                or (not v2 and type(receipt.get('question_digest')) is not str)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        selected, questions, flow, request = self._inputs(context, plan,
                                                        receipt['request_version'], receipt['fence'])
        if (receipt['request_digest'] != request.request_digest
                or (not v2 and receipt['question_digest'] != questions[0].question_digest)
                or (v2 and receipt.get('question_digests') !=
                    {q.question_id:q.question_digest for q in questions})
                or (v2 and receipt.get('caller_materials_ref') != asdict(selected['caller_materials_ref']))):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        try:
            native = _wait(self.services.evidence.read(receipt['run_id'], self.services.read_context))
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE') from None
        result = _verified_native_result(native, receipt['run_id'], request, flow,
                                         self.services.decision_provider.binding_ref)
        terminal = result.to_dict()
        if (terminal.get('status') != 'completed' or terminal.get('flow_ref') != flow.ref.to_dict()):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        issues = terminal.get('outcome', {}).get('issues', [])
        expected_count = len(questions)
        if (not isinstance(issues, (tuple, list)) or len(issues) != expected_count
                or any(not isinstance(issue, Mapping) or issue.get('code') != 'source-review-answer'
                       for issue in issues)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        try:
            answer_pairs = []
            for issue in issues:
                check_id = issue.get('check_id')
                if not v2 and check_id is None:
                    check_id = questions[0].question_id
                answer = DecisionAnswer.from_dict(issue['answer'])
                answer_pairs.append((check_id, answer))
            events = native['events']
            if any(not isinstance(event, Mapping)
                   or not isinstance(event.get('payload'), Mapping) for event in events):
                raise ValueError()
            responses = [e['payload'] for e in events
                         if e['payload'].get('type') == 'call.response']
            intents = [e['payload'] for e in events
                       if e['payload'].get('type') == 'call.intent']
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from None
        expected_by_id = {q.question_id:q for q in questions}
        # The native run numbers model attempts globally across the run, so an
        # N-question flow yields attempts 1..N in call order. Requiring attempt 1
        # for every question would only hold for the single-question contract.
        expected_attempt = {q.question_id:index + 1 for index, q in enumerate(questions)}
        # The run's own records must number these calls 1..N exactly once each:
        # no duplicate, missing or extra attempt may be folded onto a question.
        intents_by_attempt = {}
        for item in intents:
            attempt = item.get('attempt')
            if type(attempt) is not int or attempt in intents_by_attempt:
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            intents_by_attempt[attempt] = item
        if sorted(intents_by_attempt) != list(range(1, len(questions) + 1)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        if (len(expected_by_id) != len(questions) or len(responses) != len(questions)
                or len(intents) != len(questions)
                or any(type(item.get('call_id')) is not str or not item.get('call_id') for item in intents)
                or any(type(item.get('call_id')) is not str or not item.get('call_id') for item in responses)
                or len({item.get('call_id') for item in intents}) != len(intents)
                or len({item.get('call_id') for item in responses}) != len(responses)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        checked_answers = {}
        for check_id, answer in answer_pairs:
            question = expected_by_id.get(check_id)
            matching = [i for i in intents if i.get('question_digest') == (question.question_digest if question else None)]
            if (question is None or check_id in checked_answers or len(matching) != 1):
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            intent = matching[0]
            response = next((r for r in responses if r.get('call_id') == intent.get('call_id')), None)
            if (response is None or response.get('answer_digest') != answer.answer_digest
                    or intent.get('call_id') != response.get('call_id')
                    or intent.get('run_id') != receipt['run_id']
                    or response.get('run_id') != receipt['run_id']
                    or intents_by_attempt.get(expected_attempt[check_id]) is not intent
                    or intent.get('attempt') != expected_attempt[check_id]
                    or response.get('attempt') != expected_attempt[check_id]
                    or answer.question_id != question.question_id or answer.kind != 'choice'
                    or type(answer.value) is not str
                    or ('question_digest' in answer.provider_receipt
                        and answer.provider_receipt['question_digest'] != question.question_digest)
                    or ('provider_settings_digest' in answer.provider_receipt
                        and answer.provider_receipt['provider_settings_digest'] != self._provider[1])
                    or answer.value not in selected['policy']['options']):
                raise ApplicationError('UNTRUSTED_REVIEWER')
            checked_answers[check_id] = answer
        if set(checked_answers) != set(_V2_CHECK_IDS if v2 else (questions[0].question_id,)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        if v2:
            projection = self._v2_projection(selected, questions, checked_answers, receipt['run_id'])
            if receipt.get('result') != projection:
                raise ApplicationError('REVIEW_SOURCE_INVALID')
        answers = []
        for check_id in ( _V2_CHECK_IDS if v2 else (questions[0].question_id,) ):
            answer = checked_answers[check_id]
            status = selected['policy']['options'][answer.value]['status']
            for key in plan.check_keys:
                if key.criterion_id == check_id:
                    answers.append(CriterionAnswer(key, status, (), 'Original Decision choice: ' + answer.value))
        answers = tuple(answers)
        observed = review_observations(plan, selected['standard'], answers)
        capability = record_digest('decision-source-reviewer', {
            'scope':asdict(self.scope), 'reviewer':asdict(self.reviewer), 'roles':self.roles,
            'provider_binding':self._provider[0], 'provider_settings':self._provider[1],
            'run_id':receipt['run_id'], 'question_digests':tuple(q.question_digest for q in questions),
            'answer_digests':tuple(checked_answers[k].answer_digest for k in checked_answers),
            'trust_version':self.trust_version})
        evidence = VerifiedReviewerEvidence(self.scope, self.reviewer, self.roles,
            'engineering.decision-source-reviewer', '1', self.trust_version,
            plan.request_digest, raw_ref.digest, observations_digest(observed), capability)
        return receipt, VerifiedReviewResponse(evidence, answers)

    def verify_response(self, context, plan, request, raw_response_ref, *, standard):
        with self._lock, self.method_guard.guard(context, plan.requirement.method_ref):
            receipt, verified = self._verified(context, plan, raw_response_ref)
            if (request.state != 'requested' or request.scope != context.scope
                    or request.review_id != plan.review_id
                    or (request.version, request.fence) != (receipt['request_version'],receipt['fence'])
                    or standard != self.bindings.review_inputs(context, plan)['standard']):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            return verified

    @contextmanager
    def guard_trust(self, context, records):
        from contextlib import ExitStack
        with self._lock, ExitStack() as guards:
            self._check(context)
            current = []
            for record in records:
                guards.enter_context(self.method_guard.guard(context, record.plan.requirement.method_ref))
                _, verified = self._verified(context, record.plan, record.raw_response_ref)
                if verified.reviewer_evidence != record.reviewer_evidence:
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref,
                    record.reviewer_evidence.verifier_id, self.trust_version))
            yield tuple(current)

    def close(self):
        """Revoke this local selection; shared provider/evidence lifetime is host-owned."""
        with self._lock:
            self._active = False


__all__ = ['DecisionReviewerSource']
