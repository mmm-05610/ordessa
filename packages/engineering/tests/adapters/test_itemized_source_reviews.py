"""Focused checks for the finite source-review/2 contract and provenance binding."""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from decision_runtime import DecisionAnswer, DecisionQuestion, PolicyRef, DecisionError
from decision_runtime.historical.values import canonical
from ordessa_engineering.adapters.decision.source_job import SourceReviewTask, SourceReviewJobServices

from ordessa_engineering.adapters.decision import source_reviewer
from ordessa_engineering.adapters.decision.source_bindings import (
    DeclaredSourceReviewBindings,
)
from ordessa_engineering.adapters.decision.source_reviewer import (
    DecisionReviewerSource, _V2_CHECK_IDS,
)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.provenance import (
    SourceLocator, SourceRef, VersionCapture,
)
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest


def _source():
    return SourceRef('captured-doc', 'document',
        SourceLocator('document', provider='source-provider', document_id='source-doc'),
        VersionCapture('version-1', Digest('sha256', sha256(b'data').hexdigest())),
        '2026-10-14T00:00:00.000000Z',
        ActorRef('capture-actor', 'service', 'capture-issuer'),
        'application/json', 4, None)


@pytest.mark.parametrize('field,mutation', (
    ('capture', lambda value: replace(value, capture=VersionCapture(
        'version-1', Digest('sha256', 'b' * 64)))),
    ('byte_length', lambda value: replace(value, byte_length=3)),
    ('media_type', lambda value: replace(value, media_type='text/plain')),
    ('captured_by', lambda value: replace(value, captured_by=
        ActorRef('other-actor', 'service', 'capture-issuer'))),
    ('captured_at', lambda value: replace(value, captured_at='2026-10-14T00:00:01.000000Z')),
    ('original_url', lambda value: replace(value, original_url='https://docs.example/source')),
    ('locator', lambda value: replace(value, locator=SourceLocator(
        'document', provider='source-provider', document_id='other-source-doc'))),
))
def test_baseline_candidate_binding_compares_every_source_ref_field(field, mutation):
    expected = _source()
    changed = mutation(expected)

    assert not DecisionReviewerSource._matches_exact_source(expected, asdict(changed)), field
    assert DecisionReviewerSource._matches_exact_source(expected, asdict(expected))


def test_exact_source_decoder_rejects_missing_or_extra_ref_fields():
    value = asdict(_source())
    value.pop('original_url')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_SOURCE_INVALID'):
        DecisionReviewerSource._decode_exact_source(value)
    value = asdict(_source())
    value['unrecognized'] = True
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_SOURCE_INVALID'):
        DecisionReviewerSource._decode_exact_source(value)


def test_captured_bytes_must_match_exact_version_digest_and_length():
    ref = _source()
    DecisionReviewerSource._verify_material_bytes(ref, b'data')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_SOURCE_MISMATCH'):
        DecisionReviewerSource._verify_material_bytes(ref, b'nope')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_SOURCE_MISMATCH'):
        DecisionReviewerSource._verify_material_bytes(ref, b'abc')


def test_duplicate_json_fields_are_rejected_before_any_review_call():
    with pytest.raises(ValueError, match='duplicate key'):
        DecisionReviewerSource._strict_json(b'{"checks": [], "checks": []}')


def test_contract_schema_pins_eight_fixed_check_ids_and_complete_native_result():
    root = Path(__file__).resolve().parents[4]
    method = root / 'methods/incremental-engineering/candidates/2.7.2/schemas'
    caller_schema = json.loads((method / 'caller-review-input.schema.json').read_text())
    result_schema = json.loads((method / 'review-result.schema.json').read_text())

    DeclaredSourceReviewBindings._validate_v2_input_schema(caller_schema)
    DeclaredSourceReviewBindings._validate_v2_result_schema(result_schema)
    caller_schema['properties']['checks']['maxItems'] = 7
    with pytest.raises(ValueError, match='SOURCE_REVIEW_INPUT_SCHEMA_INVALID'):
        DeclaredSourceReviewBindings._validate_v2_input_schema(caller_schema)
    result_schema['properties']['checks']['items']['properties']['answer_digest']['pattern'] = '.*'
    with pytest.raises(ValueError, match='SOURCE_REVIEW_RESULT_SCHEMA_INVALID'):
        DeclaredSourceReviewBindings._validate_v2_result_schema(result_schema)


def _result_schema():
    item_required = ['check_id', 'claim', 'evidence', 'native_run_ref',
                     'question_digest', 'answer_digest', 'choice']
    item_properties = {
        'check_id': {'enum': list(_V2_CHECK_IDS)},
        'claim': {'type': 'string', 'minLength': 1},
        'evidence': {'type': 'array', 'minItems': 1},
        'native_run_ref': {'type': 'string', 'minLength': 1},
        'question_digest': {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$'},
        'answer_digest': {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$'},
        'choice': {'enum': ['passed', 'not_passed', 'unknown']},
    }
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['scope', 'baseline', 'candidate', 'checks', 'aggregate'],
        'properties': {
            'scope': {'type': 'object'}, 'baseline': {'type': 'object'},
            'candidate': {'type': 'object'},
            'checks': {'type': 'array', 'minItems': 8, 'maxItems': 8,
                'items': {'type': 'object', 'additionalProperties': False,
                    'required': item_required, 'properties': item_properties}},
            'aggregate': {'type': 'object', 'additionalProperties': False,
                'required': ['policy', 'conclusion'], 'properties': {
                    'policy': {'const': 'all_required'},
                    'conclusion': {'enum': ['passed', 'not_passed', 'unknown']}}},
        },
    }


@pytest.mark.parametrize(('choices', 'expected'), (
    ({'source-version-preservation': 'unknown',
      'scoped-read-boundary': 'not_passed'}, 'not_passed'),
    ({'source-version-preservation': 'unknown'}, 'unknown'),
    ({}, 'passed'),
))
def test_pair_level_projection_requires_all_eight_native_choices_and_aggregates(choices, expected):
    source = DecisionReviewerSource.__new__(DecisionReviewerSource)
    source.scope = Scope('source-review-realm', 'source-review-project')
    source.bindings = type('Bindings', (), {'baseline': _source(), 'candidate': replace(
        _source(), source_id='candidate-doc', capture=VersionCapture(
            'version-2', Digest('sha256', 'b' * 64)))})()
    # Mirrors the adapter's own construction: the finite choice contract requires
    # a policy_ref on every question, so a question without one never exists.
    policy_ref = PolicyRef('source-review-binding', '2', 'sha256:' + '0' * 64)
    questions = tuple(DecisionQuestion(check_id, '1', 'choice', {'check_id':check_id},
        'Select the status.', options={'passed':'Passed','not_passed':'Not passed','unknown':'Unknown'},
        allowed_answer_ids=('passed','not_passed','unknown'), policy_ref=policy_ref)
        for check_id in _V2_CHECK_IDS)
    answers = {q.question_id:DecisionAnswer(q.question_id, 'choice',
        choices.get(q.question_id, 'passed'), {'provider':'controlled'}) for q in questions}
    caller_checks = tuple({'check_id':check_id, 'claim':'Caller claim',
        'evidence':[{'source_ref':asdict(_source()), 'excerpt':'captured'}]}
        for check_id in _V2_CHECK_IDS)
    selected = {'caller_checks':caller_checks, 'result_schema':_result_schema(),
                'schema_documents':{}}

    projected = source._v2_projection(selected, questions, answers, 'native-run-1')

    assert len(projected['checks']) == 8
    assert {row['native_run_ref'] for row in projected['checks']} == {'native-run-1'}
    assert projected['aggregate'] == {'policy':'all_required', 'conclusion':expected}
    assert all(set(row) == set(_result_schema()['properties']['checks']['items']['required'])
               for row in projected['checks'])


def _captured(raw):
    return SourceRef('captured-doc', 'document',
        SourceLocator('document', provider='source-provider', document_id='source-doc'),
        VersionCapture('version-1', Digest('sha256', sha256(raw).hexdigest())),
        '2026-10-14T00:00:00.000000Z',
        ActorRef('capture-actor', 'service', 'capture-issuer'),
        'application/json', len(raw), None)


def _gated_reviewer(raw, *, contract):
    """The smallest real _inputs path: one pinned target and no caller material.

    The v2 branch stops at the missing caller material, so a source that reaches
    that refusal has itself passed the single-source gate.
    """
    selected = {'policy': {'contract': contract, 'reviewer_roles': ('reviewer',),
                           'options': {'passed': {'description': 'Passed'}}},
                'refs': (SimpleNamespace(resource_id='source-review-binding',
                                         resource_digest=Digest('sha256', '0' * 64)),)}
    plan = SimpleNamespace(requirement=SimpleNamespace(expected_targets=SimpleNamespace(
        targets=(SimpleNamespace(role='base',
            ref=SimpleNamespace(source_ref=_captured(raw))),))))
    context = CommandContext(Scope('gate-realm', 'gate-project'), 'gate-principal',
        ActorRef('gate-actor', 'service', 'gate-issuer'), 'gate-command',
        '2026-10-14T00:00:00.000000Z', 'gate-trace')
    reviewer = DecisionReviewerSource.__new__(DecisionReviewerSource)
    reviewer._active = True
    reviewer.scope, reviewer.principal_id = context.scope, context.principal_id
    reviewer.reviewer, reviewer.roles, reviewer.trust_version = (
        ActorRef('gate-reviewer', 'service', 'gate-issuer'), ('reviewer',), 1)
    reviewer._reviewer_selection = (reviewer.reviewer, reviewer.roles, reviewer.trust_version)
    reviewer._provider = ('gate-provider/1', 'sha256:' + 'd' * 64)
    reviewer.services = SimpleNamespace(decision_provider=SimpleNamespace(
        binding_ref=reviewer._provider[0], settings_digest=reviewer._provider[1]))
    reviewer.bindings = SimpleNamespace(review_inputs=lambda context, plan: selected,
                                        binding_resource_id='source-review-binding')
    reviewer.materials = SimpleNamespace(read=lambda context, ref: raw)
    return reviewer, context, plan


def test_v2_single_source_gate_admits_256kib_and_refuses_the_next_byte():
    assert source_reviewer._V2_SOURCE_BYTES == 262144
    assert source_reviewer._V1_SOURCE_BYTES == 65536
    limit = source_reviewer._V2_SOURCE_BYTES

    reviewer, context, plan = _gated_reviewer(b'x' * limit,
        contract='engineering-source-review/2')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_MISSING'):
        reviewer._inputs(context, plan, 0, 1)

    reviewer, context, plan = _gated_reviewer(b'x' * (limit + 1),
        contract='engineering-source-review/2')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_LIMIT'):
        reviewer._inputs(context, plan, 0, 1)

    reviewer, context, plan = _gated_reviewer(
        b'x' * (source_reviewer._V1_SOURCE_BYTES + 1),
        contract='engineering-source-review/1')
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_LIMIT'):
        reviewer._inputs(context, plan, 0, 1)


def test_request_brief_keeps_exact_source_refs_and_eight_question_digests_without_full_text():
    baseline = _source()
    candidate = replace(baseline, source_id='candidate-doc',
        capture=VersionCapture('version-2', Digest('sha256', 'b' * 64)))
    source_inputs = (
        {'role': 'base', 'source_ref': asdict(baseline), 'text': 'captured baseline body'},
        {'role': 'proposed', 'source_ref': asdict(candidate), 'text': 'captured candidate body'},
    )
    caller_ref = _source()
    policy_ref = PolicyRef('source-review-binding', '2', 'sha256:' + '0' * 64)
    questions = tuple(
        DecisionQuestion(check_id, '1', 'choice',
            {'sources': source_inputs, 'caller_materials_ref': asdict(caller_ref)},
            'Select the status.', options={'passed': 'Passed', 'not_passed': 'Not passed'},
            allowed_answer_ids=('passed', 'not_passed'), evidence_ids=('sha256:' + '0' * 64,),
            policy_ref=policy_ref)
        for check_id in _V2_CHECK_IDS)

    brief = SourceReviewTask('review-request', '0', 'Review the exact supplied change.',
        inputs=source_reviewer._request_inputs(questions, source_inputs, asdict(caller_ref)),
        boundaries=('explicit-source-pins-only',))

    summary = brief.inputs[0]
    assert summary['sources'] == ({'role': 'base', 'source_ref': asdict(baseline)},
                                  {'role': 'proposed', 'source_ref': asdict(candidate)})
    assert summary['caller_materials_ref'] == asdict(caller_ref)
    assert summary['questions'] == tuple({'question_id': q.question_id,
        'version': q.version, 'question_digest': q.question_digest} for q in questions)
    encoded = json.dumps(brief.to_dict())
    assert 'captured baseline body' not in encoded
    assert 'captured candidate body' not in encoded
    # every real question still carries the exact full text the provider is asked about
    assert all(q.bounded_state['sources'][0]['text'] == 'captured baseline body' for q in questions)
    assert all(q.bounded_state['sources'][1]['text'] == 'captured candidate body' for q in questions)


def _full_input_reviewer(*, baseline_raw=b'baseline ' + b'b' * 142421,
                         candidate_raw=b'candidate ' + b'c' * 172029,
                         evidence_raw=None, claim='Captured claim', excerpt='baseline',
                         evidence_copies=1,
                         contract='engineering-source-review/2'):
    """Real _inputs/JSON-schema path with a controlled, exact-ref material reader."""
    from contextlib import nullcontext
    from threading import RLock
    from referencing import Resource
    from referencing.jsonschema import DRAFT202012
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef

    reviewer, context, _ = _gated_reviewer(baseline_raw, contract=contract)
    def captured(source_id, raw):
        return replace(_captured(raw), source_id=source_id,
            locator=SourceLocator('document', provider='project-files', document_id=source_id))
    baseline = captured('baseline', baseline_raw)
    candidate = captured('candidate', candidate_raw)
    evidence = (baseline if evidence_raw is None else
                captured('evidence', evidence_raw))
    refs_and_bytes = [(baseline, baseline_raw), (candidate, candidate_raw)]
    if evidence_raw is not None:
        refs_and_bytes.append((evidence, evidence_raw))
    method_root = Path(__file__).resolve().parents[4] / 'methods/incremental-engineering/candidates/2.7.2'
    policy = json.loads((method_root / 'criteria/source-review.json').read_text())
    policy['contract'] = contract
    caller = {'scope': asdict(context.scope), 'baseline': asdict(baseline),
        'candidate': asdict(candidate), 'checks': [
            {'check_id': check_id, 'claim': claim,
             'evidence': [{'source_ref': asdict(evidence), 'excerpt': excerpt}
                          for _ in range(evidence_copies)]}
            for check_id in _V2_CHECK_IDS]}
    caller_raw = json.dumps(caller).encode()
    caller_ref = captured('caller-materials', caller_raw)
    refs_and_bytes.append((caller_ref, caller_raw))
    documents = {}
    for name in ('scope', 'source-ref', 'caller-review-input'):
        uri = f'https://ordessa.invalid/method/schemas/{name}.schema.json'
        document = json.loads((method_root / f'schemas/{name}.schema.json').read_text())
        document['$id'] = uri
        documents[uri] = Resource.from_contents(document, default_specification=DRAFT202012)
        if name == 'caller-review-input':
            caller_schema = document
    selected = {'policy': policy, 'criteria': 'Pinned review criteria.',
        'prompt': 'Review the exact captured pair.', 'schema_documents': documents,
        'caller_input_schema': caller_schema, 'caller_materials_ref': caller_ref,
        'refs': (SimpleNamespace(resource_id='source-review-binding',
                                 resource_digest=Digest('sha256', '0' * 64)),)}
    plan = SimpleNamespace(review_id='full-input-review', plan_digest=Digest('sha256', '1' * 64),
        requirement=SimpleNamespace(method_ref=MethodRef('incremental-engineering', '2.7.2', 1,
            Digest('sha256', '2' * 64)), expected_targets=SimpleNamespace(targets=tuple(
                SimpleNamespace(role=role, ref=SimpleNamespace(source_ref=ref))
                for role, ref in (('base', baseline), ('proposed', candidate))))))
    reads = []
    def read(_context, ref):
        reads.append(ref)
        return next(raw for exact, raw in refs_and_bytes if exact == ref)
    reviewer.bindings = SimpleNamespace(review_inputs=lambda *_args: selected,
        baseline=baseline, candidate=candidate, binding_resource_id='source-review-binding')
    reviewer.materials = SimpleNamespace(read=read)
    reviewer._lock = RLock()
    reviewer.method_guard = SimpleNamespace(guard=lambda *_args: nullcontext())
    return reviewer, context, plan, selected, reads


def test_v2_full_sources_and_evidence_reach_all_eight_questions_without_brief_duplication():
    reviewer, context, plan, selected, reads = _full_input_reviewer()
    _, questions, _, request = reviewer._inputs(context, plan, 0, 1)

    assert len(questions) == 8
    assert tuple(q.question_id for q in questions) == _V2_CHECK_IDS
    for question in questions:
        state = question.bounded_state
        restored = tuple(''.join(state['source_text_blocks'][span['block_id']]
                                 for span in s['segments']) for s in state['sources'])
        assert tuple(len(text.encode()) for text in restored) == (142430, 172039)
        for source, text in zip(state['sources'], restored):
            assert sha256(text.encode()).hexdigest() == source['source_ref']['capture']['content_digest']['hex']
        assert question.bounded_state['caller_evidence'][0]['excerpt'] == 'baseline'
    assert reads.count(reviewer.bindings.baseline) == 9  # target plus eight evidence reads
    assert request.task.inputs[0]['caller_materials_ref'] == asdict(selected['caller_materials_ref'])
    assert request.task.inputs[0]['questions'] == tuple({'question_id': q.question_id,
        'version': q.version, 'question_digest': q.question_digest} for q in questions)
    assert len(canonical(request.task)) < 8192


def test_v2_evidence_source_admits_exact_256kib():
    reviewer, context, plan, _, reads = _full_input_reviewer(
        baseline_raw=b'baseline', candidate_raw=b'candidate',
        evidence_raw=b'baseline' + b'e' * (262144 - 8))
    _, questions, _, _ = reviewer._inputs(context, plan, 0, 1)
    assert len(questions) == 8
    assert sum(ref.source_id == 'evidence' for ref in reads) == 8


@pytest.mark.parametrize('refusal', ('evidence', 'question', 'v1-source'))
def test_oversized_evidence_or_question_refuses_before_decision_invocation(monkeypatch, refusal):
    import asyncio
    from decision_runtime import DecisionError as ContractError
    options = {
        'evidence': dict(baseline_raw=b'baseline', candidate_raw=b'candidate',
                         evidence_raw=b'baseline' + b'e' * (262145 - 8)),
        'question': dict(baseline_raw=b'baseline' + b'b' * (262144 - 8),
                         candidate_raw=b'candidate' + b'c' * (262144 - 9)),
        'v1-source': dict(baseline_raw=b'x' * 65537, candidate_raw=b'candidate',
                          contract='engineering-source-review/1'),
    }[refusal]
    reviewer, context, plan, _, _ = _full_input_reviewer(**options)
    calls = []
    async def no_decision(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('an oversized input reached the decision runner')
    monkeypatch.setattr(SourceReviewJobServices, 'run', no_decision)
    request_state = SimpleNamespace(scope=context.scope, review_id=plan.review_id,
                                    state='requested', version=0, fence=1)
    error = ContractError if refusal == 'question' else ApplicationError
    with pytest.raises(error, match='value_too_large' if refusal == 'question' else 'REVIEW_INPUT_LIMIT'):
        asyncio.run(reviewer.run_review(context, plan, request_state))
    assert calls == []


@pytest.mark.parametrize('change', ('source', 'claim', 'excerpt', 'question_text'))
def test_v2_request_digest_binds_full_question_state(change):
    reviewer, context, plan, selected, _ = _full_input_reviewer()
    _, original, _, request = reviewer._inputs(context, plan, 0, 1)
    if change == 'question_text':
        selected['policy']['required_checks'][0]['question_text'] += ' Changed question.'
    else:
        options = {'source': {'baseline_raw': b'baseline ' + b'z' * 142421},
                   'claim': {'claim': 'Changed caller claim'},
                   'excerpt': {'excerpt': 'baseline '}}[change]
        reviewer, context, plan, _, _ = _full_input_reviewer(**options)
    _, changed, _, changed_request = reviewer._inputs(context, plan, 0, 1)
    assert original[0].question_digest != changed[0].question_digest
    assert request.request_digest != changed_request.request_digest


@pytest.mark.parametrize('field', ('caller_claim', 'source_text'))
def test_question_state_change_alone_changes_request_digest_with_identical_source_pins(field):
    reviewer, context, plan, selected, _ = _full_input_reviewer()
    _, questions, _, request = reviewer._inputs(context, plan, 0, 1)
    state = deepcopy(questions[0].projection()['bounded_state'])
    if field == 'source_text':
        block = state['sources'][0]['segments'][0]['block_id']
        state['source_text_blocks'][block] += ' changed state'
    else:
        state['caller_claim'] += ' changed state'
    changed = (replace(questions[0], bounded_state=state), *questions[1:])
    # This is an isolated digest counterexample, not admissible changed source
    # material: leave every SourceRef/caller pin fixed to test transitive binding.
    inputs = source_reviewer._request_inputs(changed,
        questions[0].bounded_state['sources'], asdict(selected['caller_materials_ref']))
    changed_request = replace(request, task=replace(request.task, inputs=inputs))
    assert request.task.inputs[0]['sources'] == changed_request.task.inputs[0]['sources']
    assert request.task.inputs[0]['caller_materials_ref'] == changed_request.task.inputs[0]['caller_materials_ref']
    assert questions[0].question_digest != changed[0].question_digest
    assert request.request_digest != changed_request.request_digest


def test_v1_request_keeps_original_full_bounded_state_tuple():
    reviewer, context, plan, _, _ = _full_input_reviewer(
        baseline_raw=b'baseline', candidate_raw=b'candidate',
        contract='engineering-source-review/1')
    _, questions, _, request = reviewer._inputs(context, plan, 0, 1)
    assert len(questions) == 1
    assert request.task.inputs == tuple(q.bounded_state for q in questions)
    expected = SourceReviewTask(plan.review_id, '0', 'Review the exact supplied change.',
        inputs=tuple(q.bounded_state for q in questions), boundaries=('explicit-source-pins-only',))
    assert canonical(request.task) == canonical(expected)
    assert request.task.inputs[0]['sources'][0]['text'] == 'baseline'


_REPEATED = ('## BEGIN MEMBER SRS.md\n### 1. Scope\névidence cité\n'
             '## END MEMBER SRS.md\n## BEGIN MEMBER SDD.md\n'
             '### 2. Scope\névidence cité\n## END MEMBER SDD.md\n')


def test_quote_locations_do_not_treat_nested_code_fences_as_member_or_section_headings():
    text = ('## BEGIN MEMBER SRS.md\n### Real section\n````markdown\n```\n'
            '## BEGIN MEMBER wrong.md\n### Fake heading\nquoted\n'
            '````not-a-closing-fence\n### Another fake\nquoted\n````\n'
            '### Next section\nquoted\n')
    locations = source_reviewer._excerpt_locations(text, 'quoted')
    assert [x['member'] for x in locations] == ['SRS.md'] * 3
    assert [x['section'] for x in locations] == ['### Real section'] * 2 + ['### Next section']
    assert all(text.encode()[x['byte_start']:x['byte_end']] == b'quoted' for x in locations)


def test_lossless_full_pair_shares_readable_text_and_preserves_every_evidence_occurrence():
    baseline = ('# Baseline\n' + _REPEATED).encode()
    candidate = ('# Candidate\n' + _REPEATED + 'Proposed only.\n').encode()
    reviewer, context, plan, _, _ = _full_input_reviewer(
        baseline_raw=baseline, candidate_raw=candidate, excerpt='évidence cité', evidence_copies=2)
    selected, questions, _, _ = reviewer._inputs(context, plan, 0, 1)
    _, repeated, _, _ = reviewer._inputs(context, plan, 0, 1)
    assert [q.question_digest for q in questions] == [q.question_digest for q in repeated]
    for q in questions:
        state = q.bounded_state
        assert state['source_representation'] == source_reviewer._MATERIAL_REPRESENTATION
        assert 'actual readable text here' in state['representation_instructions']
        assert 'question_text' not in state['required_check']
        assert q.question_text == next(check['question_text'] for check in
            reviewer.bindings.review_inputs(context, plan)['policy']['required_checks']
            if check['check_id'] == q.question_id)
        texts = tuple(''.join(state['source_text_blocks'][span['block_id']]
                             for span in source['segments']) for source in state['sources'])
        assert tuple(t.encode() for t in texts) == (baseline, candidate)
        assert len(state['source_text_blocks']) < sum(len(s['segments']) for s in state['sources'])
        assert len(state['caller_evidence']) == 1 and tuple(state['caller_evidence_occurrences']) == (0, 0)
        locations = state['caller_evidence'][0]['locations']
        assert tuple(x['member'] for x in locations) == ('SRS.md', 'SDD.md')
        assert tuple(x['section'] for x in locations) == ('### 1. Scope', '### 2. Scope')
        for location in locations:
            assert baseline[location['byte_start']:location['byte_end']].decode() == 'évidence cité'
    # Original caller evidence is returned unchanged, including duplicates.
    assert len(selected['caller_checks'][0]['evidence']) == 2
    assert all(set(e) == {'source_ref', 'excerpt'} for e in selected['caller_checks'][0]['evidence'])


@pytest.mark.parametrize('attack', ('block', 'missing-block', 'extra-block', 'reference',
                                  'order', 'offset', 'pin', 'location', 'occurrence'))
def test_packed_material_tampering_refuses_before_original_decision_runner(monkeypatch, attack):
    import asyncio
    reviewer, context, plan, _, _ = _full_input_reviewer(
        baseline_raw=('# Baseline\n' + _REPEATED).encode(),
        candidate_raw=('# Candidate\n' + _REPEATED).encode(),
        excerpt='évidence cité', evidence_copies=2)
    original = source_reviewer._pack_review_materials
    def changed(*args):
        packed = original(*args)
        first = packed['sources'][0]['segments'][0]
        if attack == 'block': packed['source_text_blocks'][first['block_id']] += 'changed'
        elif attack == 'missing-block': packed['source_text_blocks'].pop(first['block_id'])
        elif attack == 'extra-block': packed['source_text_blocks']['extra'] = 'unreviewed material'
        elif attack == 'reference': first['block_id'] = 'missing'
        elif attack == 'order': packed['sources'][0]['segments'].reverse()
        elif attack == 'offset': first['byte_end'] += 1
        elif attack == 'pin': packed['sources'][0]['source_ref']['source_id'] = 'forged'
        elif attack == 'location': packed['caller_evidence'][0]['locations'].pop()
        else: packed['caller_evidence_occurrences'].pop()
        return packed
    monkeypatch.setattr(source_reviewer, '_pack_review_materials', changed)
    calls = []
    async def no_decision(*args, **kwargs):
        calls.append(True)
        raise AssertionError('tampered material reached the decision runner')
    monkeypatch.setattr(SourceReviewJobServices, 'run', no_decision)
    state = SimpleNamespace(scope=context.scope, review_id=plan.review_id,
                            state='requested', version=0, fence=1)
    with pytest.raises(ApplicationError, match='REVIEW_INPUT_PACKING_INVALID'):
        asyncio.run(reviewer.run_review(context, plan, state))
    assert calls == []
