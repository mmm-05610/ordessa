"""Source review through public Decision services and their original evidence.

The host explicitly selects the scoped reviewer, roles and Decision services.
A model answer or a wire receipt cannot make that selection or authenticate
itself. This adapter owns no Decision run state and never calls a Unit.
"""
from __future__ import annotations

import asyncio
from bisect import bisect_right
from difflib import SequenceMatcher
import re
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256

from ordessa_decision import DecisionAnswer, DecisionQuestion, PolicyRef
from .source_job import SourceReviewJobServices, SourceReviewRequest, SourceReviewTask
from .source_history import historical_selection, historical_answers, _verified_native_result
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
from . import source_sections

_V2_CHECK_IDS = (
    'source-version-preservation', 'scoped-read-boundary', 'evidence-support',
    'unique-record-authority', 'public-call-chain', 'changed-source-refusal',
    'acceptance-coverage', 'declared-limitations',
)

# One pinned source per target may carry a full document under source-review/2.
# The finite v1 contract keeps its original 64KiB bound, including evidence reads.
_V1_SOURCE_BYTES = 65536
_V2_SOURCE_BYTES = 262144

_MATERIAL_REPRESENTATION = 'complete-captures/shared-text/1'
_MATERIAL_INSTRUCTIONS = (
    'Every sources entry is a COMPLETE original capture, not a summary or selected chapters. '
    'Read each document by concatenating source_text_blocks[segment.block_id] in its listed '
    'segments order, including repeated occurrences. The block table contains the actual readable '
    'text here; no hash lookup or external retrieval is needed. byte_start/byte_end are UTF-8 '
    'positions in that original document. All original member names, headings and text remain '
    'in this representation. Shared text does not merge baseline/candidate or SRS/SDD identities. '
    'caller_evidence contains unique original excerpts; locations lists ALL exact occurrences '
    'with original member, heading and byte positions. caller_evidence_occurrences indexes that '
    'list to restore the caller original evidence order and multiplicity. The check question '
    'text is the question instructions. This changes representation only; the method '
    'criteria and review instructions below remain authoritative.')


def _excerpt_locations(text, excerpt):
    """Original UTF-8 addresses; a repeated quote never acquires a single invented origin."""
    raw, needle = text.encode('utf-8'), excerpt.encode('utf-8')
    headings, offsets, member, fenced, offset = [], [], None, None, 0
    for line in text.splitlines(keepends=True):
        inside_fence = fenced is not None
        if inside_fence:
            marker, width = fenced
            if re.fullmatch(r' {0,3}' + re.escape(marker) + '{' + str(width) + r',}[ \t]*(?:\r?\n)?', line):
                fenced = None
        else:
            fence = re.match(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)', line)
            if fence and (fence[1][0] == '~' or '`' not in fence[2]):
                fenced = (fence[1][0], len(fence[1]))
        if not inside_fence and fenced is None:
            match = re.match(r'^(#{1,6}) (.+?)\s*$', line)
            if match:
                heading = match[0].rstrip()
                begin = re.fullmatch(r'BEGIN MEMBER (.+)', match[2])
                if begin:
                    member = begin[1]
                if match[2].startswith('END MEMBER '):
                    member = None
                offsets.append(offset); headings.append((member, heading))
        offset += len(line.encode('utf-8'))
    result, start = [], 0
    while (start := raw.find(needle, start)) >= 0:
        index = bisect_right(offsets, start) - 1
        member, heading = headings[index] if index >= 0 else (None, None)
        result.append({'byte_start': start, 'byte_end': start + len(needle),
                       'member': member, 'section': heading})
        start += 1
    return result


def _pack_review_materials(source_inputs, evidence):
    """One lossless in-memory representation for this pair-level reviewer only."""
    left, right = (source['text'].splitlines(keepends=True) for source in source_inputs)
    # Bound the matching algorithm, never the visible material. Dense line inputs
    # keep whole readable blocks under the same representation and validation.
    operations = (SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
                  if len(left) + len(right) <= 8192
                  else [('replace', 0, len(left), 0, len(right))])
    blocks, ids, segments, offsets = {}, {}, [[], []], [0, 0]
    for _kind, a, b, c, d in operations:
        for side, text in enumerate((''.join(left[a:b]), ''.join(right[c:d]))):
            if not text:
                continue
            if text not in ids:
                ids[text] = 'b' + str(len(blocks)); blocks[ids[text]] = text
            end = offsets[side] + len(text.encode('utf-8'))
            segments[side].append({'block_id': ids[text], 'byte_start': offsets[side], 'byte_end': end})
            offsets[side] = end
    unique, occurrences, seen = [], [], {}
    for item in evidence:
        key = canonical_bytes(item)
        if key not in seen:
            seen[key] = len(unique); unique.append(deepcopy(item))
        occurrences.append(seen[key])
    return {'sources': [{'role': source['role'], 'source_ref': deepcopy(source['source_ref']), 'segments': spans}
                        for source, spans in zip(source_inputs, segments)],
            'source_text_blocks': blocks, 'caller_evidence': unique,
            'caller_evidence_occurrences': occurrences}


def _verify_review_materials(packed, source_inputs, evidence):
    """Refuse malformed layout independently of the packer, before freezing a question."""
    try:
        if set(packed) != {'sources', 'source_text_blocks', 'caller_evidence', 'caller_evidence_occurrences'}:
            raise ValueError
        blocks, used = packed['source_text_blocks'], set()
        if type(blocks) is not dict or len(packed['sources']) != len(source_inputs):
            raise ValueError
        if (list(blocks) != ['b' + str(index) for index in range(len(blocks))]
                or len(set(blocks.values())) != len(blocks)):
            raise ValueError
        for source, expected in zip(packed['sources'], source_inputs):
            if (set(source) != {'role', 'source_ref', 'segments'}
                    or source['role'] != expected['role'] or source['source_ref'] != expected['source_ref']):
                raise ValueError
            chunks, offset = [], 0
            for span in source['segments']:
                if set(span) != {'block_id', 'byte_start', 'byte_end'}:
                    raise ValueError
                text = blocks[span['block_id']]
                if type(text) is not str or not text or type(span['byte_start']) is not int or type(span['byte_end']) is not int:
                    raise ValueError
                raw = text.encode('utf-8')
                if span['byte_start'] != offset or span['byte_end'] != offset + len(raw):
                    raise ValueError
                chunks.append(raw); used.add(span['block_id']); offset += len(raw)
            raw = b''.join(chunks)
            if (raw != expected['text'].encode('utf-8') or offset != source['source_ref']['byte_length']
                    or sha256(raw).hexdigest() != source['source_ref']['capture']['content_digest']['hex']):
                raise ValueError
        if used != set(blocks):
            raise ValueError
        unique, occurrences = packed['caller_evidence'], packed['caller_evidence_occurrences']
        if (len({canonical_bytes(item) for item in unique}) != len(unique)
                or any(type(index) is not int or not 0 <= index < len(unique) for index in occurrences)
                or set(occurrences) != set(range(len(unique)))
                or [unique[index] for index in occurrences] != evidence):
            raise ValueError
    except (KeyError, TypeError, ValueError, IndexError):
        raise ApplicationError('REVIEW_INPUT_PACKING_INVALID') from None


def _request_inputs(questions, source_inputs, caller_materials_ref):
    """V2 brief: exact source/caller pins and the full digest of each question.

    Each DecisionQuestion keeps its selected readable input representation, so
    the brief repeats only digests; SourceRefs still pin the complete captures.
    """
    return ({
        'sources': tuple({'role': item['role'], 'source_ref': item['source_ref']}
                         for item in source_inputs),
        'caller_materials_ref': caller_materials_ref,
        'questions': tuple({'question_id': question.question_id,
                            'version': question.version,
                            'question_digest': question.question_digest}
                           for question in questions),
    },)


def _wait(coroutine):
    """Bridge the synchronous Engineering source port to the public async reader."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result(timeout=10)




class DecisionReviewerSource:
    def __init__(self, factory, blobs, method_guard, source_materials, bindings, *,
                 scope: Scope, principal_id: str, reviewer: ActorRef,
                 roles: tuple[str, ...], services: SourceReviewJobServices, trust_version: int = 1):
        if (type(scope) is not Scope or type(reviewer) is not ActorRef
                or type(principal_id) is not str or not principal_id
                or type(roles) is not tuple or not roles or len(set(roles)) != len(roles)
                or type(trust_version) is not int or trust_version < 1
                or type(services) is not SourceReviewJobServices
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
        v2 = policy.get('contract') == 'engineering-source-review/2'
        source_limit = _V2_SOURCE_BYTES if v2 else _V1_SOURCE_BYTES
        source_inputs = []
        for target in plan.requirement.expected_targets.targets:
            ref = target.ref.source_ref
            raw = self.materials.read(context, ref)
            if type(raw) is not bytes or len(raw) > source_limit:
                raise ApplicationError('REVIEW_INPUT_LIMIT')
            if v2:
                self._verify_material_bytes(ref, raw)
            try:
                text = raw.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                raise ApplicationError('REVIEW_SOURCE_INVALID') from None
            source_inputs.append({'role':target.role, 'source_ref':asdict(ref), 'text':text})
        binding_ref = next(ref for ref in selected['refs']
                           if ref.resource_id == self.bindings.binding_resource_id)
        policy_ref = PolicyRef(binding_ref.resource_id, '2' if v2 else '1',
                               'sha256:' + binding_ref.resource_digest.hex)
        options = {key:value['description'] for key, value in policy['options'].items()}
        section_ref = selected.get('question_materials_ref')
        section_selection, input_policy = None, None
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
            if section_ref is not None:
                if type(section_ref) is not SourceRef:
                    raise ApplicationError('REVIEW_SECTION_SELECTION_INVALID')
                section_raw = self.materials.read(context, section_ref)
                if type(section_raw) is not bytes or len(section_raw) > _V2_SOURCE_BYTES:
                    raise ApplicationError('REVIEW_INPUT_LIMIT')
                self._verify_material_bytes(section_ref, section_raw)
                section_selection = source_sections.validate_selection(
                    self._strict_json(section_raw), source_inputs, scope=asdict(context.scope),
                    method_ref=asdict(plan.requirement.method_ref), check_ids=_V2_CHECK_IDS)
                input_policy = PolicyRef(source_sections.CONTRACT, '1',
                    'sha256:' + record_digest('source-review-input', asdict(section_ref)).hex)
            questions = []
            validated = []
            for item in checks:
                if (set(item) != {'check_id', 'claim', 'evidence'}
                        or type(item['claim']) is not str or not item['claim'].strip()
                        or type(item['evidence']) is not list or not item['evidence']):
                    raise ApplicationError('REVIEW_INPUT_INVALID')
                evidence = []
                located_evidence = []
                for entry in item['evidence']:
                    if (type(entry) is not dict or set(entry) != {'source_ref', 'excerpt'}
                            or type(entry['excerpt']) is not str or not entry['excerpt'].strip()):
                        raise ApplicationError('REVIEW_INPUT_INVALID')
                    source_ref = self._decode_exact_source(entry['source_ref'])
                    raw = self.materials.read(context, source_ref)
                    if type(raw) is not bytes or len(raw) > source_limit:
                        raise ApplicationError('REVIEW_INPUT_LIMIT')
                    self._verify_material_bytes(source_ref, raw)
                    try:
                        captured = raw.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        raise ApplicationError('REVIEW_INPUT_SOURCE_INVALID') from None
                    if entry['excerpt'] not in captured:
                        raise ApplicationError('REVIEW_INPUT_EXCERPT_MISMATCH')
                    evidence.append({'source_ref':asdict(source_ref), 'excerpt':entry['excerpt']})
                    located_evidence.append({**evidence[-1],
                        'locations': _excerpt_locations(captured, entry['excerpt'])})
                checked = {'check_id':item['check_id'], 'claim':item['claim'], 'evidence':evidence}
                validated.append(checked)
                if section_selection is None:
                    packed = _pack_review_materials(source_inputs, located_evidence)
                    _verify_review_materials(packed, source_inputs, located_evidence)
                else:
                    packed = source_sections.pack_sections(section_selection, source_inputs,
                                                          located_evidence, item['check_id'])
                state = {'scope':asdict(context.scope), 'method_ref':asdict(plan.requirement.method_ref),
                    'plan_digest':asdict(plan.plan_digest), 'engineering_request_version':request_version,
                    'engineering_request_fence':fence, **packed,
                    'source_representation': (_MATERIAL_REPRESENTATION if section_selection is None
                                              else source_sections.CONTRACT),
                    'representation_instructions': (_MATERIAL_INSTRUCTIONS if section_selection is None
                                                    else source_sections.INSTRUCTIONS),
                    'required_check':{key: value for key, value in next(c for c in policy['required_checks']
                        if c['check_id'] == item['check_id']).items() if key != 'question_text'},
                    'caller_claim':item['claim'],
                    'caller_materials_ref':asdict(selected['caller_materials_ref']),
                    'criteria':selected['criteria'], 'instructions':selected['prompt']}
                if section_selection is not None:
                    state['question_materials_ref'] = asdict(section_ref)
                    state['input_policy'] = asdict(input_policy)
                question_spec = next(c for c in policy['required_checks'] if c['check_id'] == item['check_id'])
                questions.append(DecisionQuestion(item['check_id'], '1' if section_selection is None else '2', 'choice', state,
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
        policies = (policy_ref,) if input_policy is None else (policy_ref, input_policy)
        request = SourceReviewRequest(plan.review_id + ':' + str(fence),
            SourceReviewTask(plan.review_id, str(request_version), 'Review the exact supplied change.',
                inputs=(_request_inputs(tuple(questions), source_inputs,
                    asdict(selected['caller_materials_ref'])) if v2 else
                    tuple(question.bounded_state for question in questions)),
                boundaries=('explicit-source-pins-only',)), tuple(questions), policies,
            self._provider[0], self._provider[1], 240.0 if v2 else 30.0)
        return selected, tuple(questions), request.to_job(), request

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

    def _check_request(self, context, plan, request_state):
        """Current original business selection, read under the method guard."""
        self._check(context)
        if (request_state.scope != context.scope or request_state.review_id != plan.review_id
                or request_state.state != 'requested'):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        selected = self.bindings.review_inputs(context, plan)
        if tuple(selected['policy']['reviewer_roles']) != self.roles:
            raise ApplicationError('UNTRUSTED_REVIEWER')
        with self.factory.begin(context.scope, 'read') as uow:
            original = uow.reviews.get_request(plan.review_id)
            original_plan = uow.reviews.get_plan(plan.review_id)
            if (original != request_state or original_plan.request_digest != plan.request_digest):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')

    async def run_review(self, context, plan, request_state):
        """One durable current job; original provider claim owns the send gate.

        No library/method lock survives an await. The synchronous claim guard
        rechecks original method/request/roles/provider just before the existing
        JEV SDK dispatch, in the same task/thread, with no intervening await.
        """
        with self._lock, self.method_guard.guard(context, plan.requirement.method_ref):
            selected, questions, job, request = self._inputs(context, plan,
                request_state.version, request_state.fence)
            self._check_request(context, plan, request_state)
        @contextmanager
        def claim_guard():
            with self._lock, self.method_guard.guard(context, plan.requirement.method_ref):
                self._check_request(context, plan, request_state)
                # Original method/request authority stays locked until the
                # independent permit's actual consumed mark is published.
                yield
        result = await self.services.run(request, context, claim_guard)
        if result.status != 'completed':
            error = ApplicationError('DECISION_REVIEW_NOT_COMPLETED', retry='reconcile')
            error.decision_run_id, error.decision_status = result.operation_ref, result.status
            raise error
        with self._lock, self.method_guard.guard(context, plan.requirement.method_ref):
            self._check_request(context, plan, request_state)
            native = self.services.reader(context, request.request_id).read(request.request_id,
                job, questions, provider_binding=self._provider[0], provider_settings=self._provider[1])
            receipt = {'schema_version': 'engineering-source-review-job/1',
                'run_id': native.operation_ref, 'request_version': request_state.version,
                'fence': request_state.fence, 'request_digest': request.request_digest,
                'question_digest': questions[0].question_digest}
            if selected['policy'].get('contract') == 'engineering-source-review/2':
                checked = {answer.question_id: answer for answer in native.answers}
                projection = self._v2_projection(selected, questions, checked, native.operation_ref)
                receipt = {'schema_version': 'engineering-source-review-job/1',
                    'run_id': native.operation_ref, 'request_version': request_state.version,
                    'fence': request_state.fence, 'request_digest': request.request_digest,
                    'question_digests': {q.question_id:q.question_digest for q in questions},
                    'caller_materials_ref': asdict(selected['caller_materials_ref']), 'result': projection}
            raw = canonical_bytes(receipt)
            return self.blobs.put_verified(raw, Digest('sha256', sha256(raw).hexdigest()), 'application/json')

    def _verified(self, context, plan, raw_ref):
        try:
            raw = self.blobs.read_verified(raw_ref)
            receipt = decode_json(raw)
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from None
        if type(receipt) is not dict:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        v2 = self.bindings.review_inputs(context, plan)['policy'].get('contract') == 'engineering-source-review/2'
        current_job = receipt.get('schema_version') == 'engineering-source-review-job/1'
        expected_receipt_fields = ({'run_id','request_version','fence','request_digest',
            'question_digests','caller_materials_ref','result'} if v2 else
            {'run_id','request_version','fence','request_digest','question_digest'})
        if current_job:
            expected_receipt_fields.add('schema_version')
        if set(receipt) != expected_receipt_fields:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        if (type(receipt['run_id']) is not str or not receipt['run_id']
                or type(receipt['request_version']) is not int or receipt['request_version'] < 0
                or type(receipt['fence']) is not int or receipt['fence'] < 1
                or type(receipt['request_digest']) is not str):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        selected, questions, job, request = self._inputs(context, plan,
            receipt['request_version'], receipt['fence'])
        if current_job:
            try:
                native = self.services.reader(context, request.request_id).read(request.request_id,
                    job, questions, provider_binding=self._provider[0], provider_settings=self._provider[1])
            except ApplicationError:
                raise
            except Exception:
                raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE') from None
            if native.operation_ref != receipt['run_id']:
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            checked_answers = {answer.question_id:answer for answer in native.answers}
        else:
            version = '3' if selected.get('question_materials_ref') is not None else ('2' if v2 else '1')
            questions, flow, request = historical_selection(request, contract_version=version)
            try:
                native = _wait(self.services.read_history(receipt['run_id']))
            except Exception:
                raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE') from None
            checked_answers = historical_answers(native, receipt['run_id'], request, flow,
                questions, self._provider, selected['policy']['options'])
        if (receipt['request_digest'] != request.request_digest
                or (not v2 and receipt.get('question_digest') != questions[0].question_digest)
                or (v2 and receipt.get('question_digests') != {q.question_id:q.question_digest for q in questions})
                or (v2 and receipt.get('caller_materials_ref') != asdict(selected['caller_materials_ref']))):
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
