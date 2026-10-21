"""Method-required itemized source review through the original public Service."""
import asyncio
import copy
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json

import pytest
from ordessa_decision import DecisionAnswer
from ordessa_decision.historical import FileEvidenceReader, ReadContext
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from test_real_source_chain import (ROOT, SCOPE, context, source, build_local_chain, close_chain,
    create_proposal, request_and_run_review, associate_and_freeze, run_full_chain, read_job_answers)


EVIDENCE = ROOT/'docs/implementation/packages-convergence-20261012/engineering/real-source-chain-20261014'
ITEMIZED = EVIDENCE/'itemized-review'
CURRENT_FIXTURE = ROOT/'packages/engineering/tests/fixtures/itemized-source-current'
METHOD = ROOT/'methods/incremental-engineering/candidates/2.7.2'
CHECK_IDS = ('source-version-preservation','scoped-read-boundary','evidence-support',
    'unique-record-authority','public-call-chain','changed-source-refusal',
    'acceptance-coverage','declared-limitations')


def itemized_entries(*, material_mutation=None):
    manifest = json.loads((CURRENT_FIXTURE/'INPUT-MANIFEST.json').read_text())
    assert manifest['fixture_revision'] == 'itemized-current-job-fixture-v2'
    assert manifest['provenance']['original_manifest_sha256'] == sha256((ITEMIZED/'INPUT-MANIFEST.json').read_bytes()).hexdigest()
    assert manifest['scope'] == asdict(SCOPE)
    entries = []
    for logical,version,name in (
        ('itemized-source-mapping-DID','itemized-baseline-v1','trial-baseline.md'),
        ('itemized-source-mapping-DID','itemized-candidate-v2','trial-candidate.md'),
        ('itemized-spec','itemized-spec-v1','spec.md'),
        ('itemized-plan','itemized-plan-v1','plan.md'),
        ('itemized-tasks','itemized-tasks-v1','tasks.md'),
    ):
        raw = (ITEMIZED/'materials'/name).read_bytes()
        pin = manifest['materials']['materials/'+name]
        assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
        entries.append((logical,version,name,raw))
    for path in manifest['workspace_capture_order']:
        pin = manifest['workspace_captures'][path]
        raw = (ROOT/path).read_bytes()
        assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
        entries.append((pin['logical_document'],pin['upstream_version'],pin['local_path'],raw))
    raw = (CURRENT_FIXTURE/'caller-review-input.json').read_bytes()
    pin = manifest['materials']['materials/caller-review-input.json']
    assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
    caller = json.loads(raw)
    assert caller['baseline'] == asdict(source(*entries[0][:2],entries[0][3]))
    assert caller['candidate'] == asdict(source(*entries[1][:2],entries[1][3]))
    if material_mutation is not None:
        material_mutation(caller)
        raw = (json.dumps(caller,indent=2)+'\n').encode()
    entries.append(('itemized-review-materials',manifest['caller_material_revision'],'caller-review-input.json',raw))
    return tuple(entries)


def test_original_20261014_manifest_materials_and_capture_assertions_remain_frozen():
    """Inert preserved source bytes; no old helper imports or legacy execution."""
    manifest = json.loads((ITEMIZED/'INPUT-MANIFEST.json').read_text())
    assert manifest['scope'] == asdict(SCOPE)
    for name, pin in manifest['materials'].items():
        raw = (ITEMIZED/name).read_bytes()
        assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
    captured = {}
    for name in manifest['workspace_capture_order']:
        pin = manifest['workspace_captures'][name]
        raw = ((CURRENT_FIXTURE/'original-helper.py.txt') if name.endswith('/test_real_source_chain.py') else ROOT/name).read_bytes()
        assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
        captured[pin['logical_document']] = raw
    caller = json.loads((ITEMIZED/'materials/caller-review-input.json').read_text())
    for check in caller['checks']:
        for evidence in check['evidence']:
            ref = evidence['source_ref']
            if ref['source_id'] in captured:
                raw = captured[ref['source_id']]
                assert ref['byte_length'] == len(raw)
                assert ref['capture']['content_digest']['hex'] == sha256(raw).hexdigest()
                assert evidence['excerpt'] in raw.decode()


class ItemizedControlledProvider:
    """Explicit synthetic answers; never a replacement for actual JEV evidence."""
    binding_ref = 'controlled-itemized-review/1'
    settings_digest = 'sha256:'+'d'*64

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.questions = []

    async def decide(self, question, ctx):
        self.questions.append(question)
        assert question.kind == 'choice'
        assert question.question_id in CHECK_IDS
        assert set(question.options) == {'passed','not_passed','unknown'}
        ctx.claim(question,self.settings_digest)
        choice = self.answers.get(question.question_id,'passed')
        return DecisionAnswer(question.question_id,'choice',choice,
            {'selection_status':'unique','controlled':True,
             'question_digest':question.question_digest,
             'provider_settings_digest':self.settings_digest, 'resolved_model':'controlled',
             'requested_model':'controlled', 'protocol_validation_version':'controlled/1',
             'probabilities':{key:float(key == choice) for key in question.options}}, {'status':'unknown'})


def build_itemized_chain(directory, *, provider=None, answers=None, material_mutation=None):
    entries = itemized_entries(material_mutation=material_mutation)
    return build_local_chain(directory,provider or ItemizedControlledProvider(answers),
        method_directory=METHOD,material_entries=entries,caller_material_index=len(entries)-1)


def test_method_fixes_all_required_checks_and_schema_no_generated_findings():
    policy = json.loads((METHOD/'criteria/source-review.json').read_text())
    assert policy['contract'] == 'engineering-source-review/2'
    assert tuple(x['check_id'] for x in policy['required_checks']) == CHECK_IDS
    assert all(x['evaluation_scope'] == 'baseline_candidate_pair' for x in policy['required_checks'])
    assert policy['aggregation']['missing_input'] == 'reject_before_invocation'
    assert policy['aggregation']['policy'] == 'all_required'
    schema = json.loads((METHOD/'schemas/review-result.schema.json').read_text())
    assert 'checks' in schema['required'] and 'findings' not in schema['properties']
    assert schema['properties']['checks']['minItems'] == len(CHECK_IDS)
    assert schema['properties']['checks']['maxItems'] == len(CHECK_IDS)


def test_2_7_2_package_loads_and_is_consumed_but_stays_declaration_only():
    """A: the package loads and validates, and is not a compiled workflow."""
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.methods import compile_method, load_method, validate_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities

    loaded = load_method(MethodSource(METHOD, 'method.json'), FileResourceReader())
    assert loaded.ok, loaded.error
    assert str(loaded.value.identity.release_version) == '2.7.2'
    report = validate_method(loaded.value, CompilationCapabilities(()))
    assert report.valid is False and report.phase == 'declaration-only'
    assert [item.code for item in report.diagnostics] == ['METHOD_EXECUTION_UNSUPPORTED']
    compiled = compile_method(loaded.value, CompilationCapabilities(()), '1')
    assert compiled.ok is False and compiled.error.code == 'METHOD_EXECUTION_UNSUPPORTED'


def test_all_required_checks_public_service_package_reconnect_and_native_cold(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        result = run_full_chain(env)
        assert env.method.release_version == '2.7.2'
        assert len(env.plan.check_keys) == 2*len(CHECK_IDS)
        assert tuple(q.question_id for q in env.services.decision_provider.questions) == CHECK_IDS
        assert result.receipt['result']['aggregate'] == {'policy':'all_required','conclusion':'passed'}
        rows = result.receipt['result']['checks']
        assert tuple(x['check_id'] for x in rows) == CHECK_IDS
        assert all(x['native_run_ref'] == result.receipt['run_id'] for x in rows)
        assert all(x['evidence'] and x['choice'] == 'passed' for x in rows)
        native = read_job_answers(env, result.receipt)
        assert native.operation_ref == result.receipt['run_id']
        assert len(native.answers) == len(CHECK_IDS)
        assert [answer.question_id for answer in native.answers] == list(CHECK_IDS)
        assert [answer.answer_digest for answer in native.answers] == [row['answer_digest'] for row in rows]
        from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
        from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
        from ordessa_engineering.application.assembly import EngineeringPorts,build_engineering_service
        from test_real_source_chain import ControlledLocalAccess,context
        from dataclasses import asdict
        path = env.library.path
        env.library.close()
        reopened = EngineeringLibrary.open(path,library_id='local-source-chain')
        try:
            service = build_engineering_service(SQLiteUoWFactory(reopened),EngineeringPorts(ControlledLocalAccess()))
            restored = asyncio.run(service.query('engineering.references.resolve',
                {'ref':asdict(result.package_ref)},context('itemized-cold-package')))
            assert restored == result.package
            replay = asyncio.run(service.execute('engineering.packages.freeze',
                {'record':result.wire},context('freeze-source-package')))
            assert replay == result.frozen
        finally:reopened.close()
    finally:close_chain(env)


@pytest.mark.parametrize('answers,verdict,conclusion',(
    ({'evidence-support':'not_passed'},'fail','not_passed'),
    ({'acceptance-coverage':'unknown'},'indeterminate','unknown'),
    ({'evidence-support':'not_passed','acceptance-coverage':'unknown'},'fail','not_passed'),
))
def test_required_nonpass_is_recorded_per_item_and_blocks_package(tmp_path,answers,verdict,conclusion):
    env = build_itemized_chain(tmp_path,answers=answers)
    try:
        proposal = create_proposal(env)
        _,recorded,receipt = request_and_run_review(env)
        assert recorded.result['verdict'] == verdict
        assert receipt['result']['aggregate']['conclusion'] == conclusion
        assert {x['check_id']:x['choice'] for x in receipt['result']['checks']} == {
            x:answers.get(x,'passed') for x in CHECK_IDS}
        with pytest.raises(ApplicationError,match='PROPOSAL_REVIEW_ASSOCIATION_INVALID'):
            associate_and_freeze(env,proposal,decode_review_ref(recorded.result['review_ref']))
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
    finally:close_chain(env)


@pytest.mark.parametrize('mutation',('missing','duplicate','extra','excerpt','version','capture_actor'))
def test_invalid_required_materials_refuse_before_any_model_call(tmp_path,mutation):
    def change(caller):
        if mutation=='missing':caller['checks'].pop()
        elif mutation=='duplicate':caller['checks'][-1]=deepcopy(caller['checks'][0])
        elif mutation=='extra':caller['checks'][0]['invented']='not permitted'
        elif mutation=='excerpt':caller['checks'][0]['evidence'][0]['excerpt']='uncaptured fabricated excerpt'
        elif mutation=='version':caller['checks'][0]['evidence'][0]['source_ref']['capture']['upstream_version']='unavailable-version'
        else:caller['checks'][0]['evidence'][0]['source_ref']['captured_by']['actor_id']='substituted-author'
    provider=ItemizedControlledProvider()
    env=build_itemized_chain(tmp_path,provider=provider,material_mutation=change)
    try:
        with pytest.raises(ApplicationError):request_and_run_review(env)
        assert provider.questions == []
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 0
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
    finally:close_chain(env)


def _frozen_historical_native(root):
    """Original codec golden history, never a projection of the current job."""
    vector = json.loads((ROOT/'packages/engineering/tests/adapters/fixtures/source-review-history/historical-vector.json').read_text())
    root.mkdir(mode=0o700)
    directory = root/vector['run_id']; directory.mkdir(mode=0o700)
    for name, raw in [('events.jsonl',vector['events_jsonl']), ('terminal.json',vector['terminal_json']), ('writer.lock','')]:
        path=directory/name; path.write_text(raw); path.chmod(0o600)
    async def cold():
        ctx=ReadContext(object(),'itemized-frozen-history')
        reader=FileEvidenceReader(root,read_context=ctx)
        try:return await reader.read(vector['run_id'],ctx)
        finally:await reader.close()
    native=asyncio.run(cold())
    assert native['status'] == 'completed' and native['call_evidence'] == 'recorded'
    events = [e['payload'] for e in native['events']]
    assert sum(e['type']=='call.intent' for e in events) == len(CHECK_IDS)
    assert sum(e['type']=='call.response' for e in events) == len(CHECK_IDS)
    return vector,native


class _FixedEvidence:
    """Test reader that serves one already-persisted native projection unchanged."""
    durable = True

    def __init__(self, native):
        self._native = native

    async def read(self, run_id, read_context):
        return self._native


def _mutated_native(mutation, native):
    value = copy.deepcopy(native)
    events = value['events']
    intents = [e for e in events if e['payload'].get('type') == 'call.intent']
    responses = [e for e in events if e['payload'].get('type') == 'call.response']
    if mutation == 'duplicate_attempt':
        intents[1]['payload']['attempt'] = intents[0]['payload']['attempt']
    elif mutation == 'reordered_attempt':
        (intents[0]['payload']['attempt'], intents[1]['payload']['attempt']) = (
            intents[1]['payload']['attempt'], intents[0]['payload']['attempt'])
    elif mutation == 'misassociated_question_digest':
        intents[1]['payload']['question_digest'] = intents[0]['payload']['question_digest']
    elif mutation == 'swapped_question_digest':
        (intents[0]['payload']['question_digest'], intents[1]['payload']['question_digest']) = (
            intents[1]['payload']['question_digest'], intents[0]['payload']['question_digest'])
    elif mutation == 'wrong_answer_digest':
        responses[0]['payload']['answer_digest'] = 'sha256:' + '0' * 64
    elif mutation == 'missing_response':
        events.remove(responses[-1])
    else:
        raise AssertionError(mutation)
    return value


def _requested_itemized_chain(tmp_path):
    """Request + run once through the public entries, without recording."""
    env = build_itemized_chain(tmp_path)
    asyncio.run(env.service.execute('engineering.reviews.request',
        {'plan':decode_json(encode_plan(env.plan))}, context('request-source-review')))
    with env.factory.begin(SCOPE, 'read') as uow:
        request = uow.reviews.get_request(env.plan.review_id)
    raw_ref = asyncio.run(env.reviewer.run_review(context('run-source-review'), env.plan, request))
    raw = env.blobs.read_verified(raw_ref)
    native = read_job_answers(env, decode_json(raw))
    return env, request, raw_ref, raw, native


def test_native_association_rejects_duplicate_misordered_missing_or_mismatched(tmp_path):
    """Every check stays bound to its exact intent/response, not to array position."""
    env, request, raw_ref, raw, native = _requested_itemized_chain(tmp_path)
    try:
        standard = env.bindings.review_inputs(context('exact-standard'), env.plan)['standard']
        assert env.reviewer.verify_response(context('verify-current-association'), env.plan,
            request, raw_ref, standard=standard) is not None
        vector, native = _frozen_historical_native(tmp_path/'history')
        from types import SimpleNamespace
        from ordessa_decision.historical.models import DecisionRequest, DecisionQuestion, PolicyRef
        from ordessa_engineering.adapters.decision.source_history import historical_answers
        historical_request = DecisionRequest.from_dict(vector['request'])
        questions = tuple(DecisionQuestion.from_dict(q) for q in vector['questions'])
        flow = SimpleNamespace(ref=historical_request.flow_ref,
            policy_refs=tuple(PolicyRef.from_dict(p) for p in vector['policies']))
        def reverify(evidence):
            return historical_answers(evidence._native, vector['run_id'], historical_request,
                flow, questions, (vector['provider_binding'], ''), {'passed','not_passed'})
        # control: the unmutated native run still verifies
        assert reverify(_FixedEvidence(native)) is not None
        for mutation, expected in (
            ('duplicate_attempt', 'REVIEW_SOURCE_INVALID'),
            ('reordered_attempt', 'UNTRUSTED_REVIEWER'),
            ('swapped_question_digest', 'UNTRUSTED_REVIEWER'),
            ('misassociated_question_digest', 'REVIEW_SOURCE_INVALID'),
            ('wrong_answer_digest', 'UNTRUSTED_REVIEWER'),
            ('missing_response', 'REVIEW_SOURCE_INVALID'),
        ):
            with pytest.raises(ApplicationError) as refusal:
                reverify(_FixedEvidence(_mutated_native(mutation, native)))
            assert refusal.value.code == expected, mutation
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 0
    finally:
        close_chain(env)


def test_changed_material_bytes_and_changed_method_pin_refuse_reuse(tmp_path):
    """A capture or method pin that moved cannot admit the earlier response."""
    env, request, raw_ref, raw, native = _requested_itemized_chain(tmp_path)
    try:
        # the candidate capture no longer matches its pinned digest: the source
        # owner refuses to serve it, so the earlier response cannot be admitted
        (env.project/'trial-candidate.md').write_bytes(b'# edited after the native run\n')
        with pytest.raises(ApplicationError, match='SOURCE_CONTENT_MISMATCH'):
            asyncio.run(env.service.execute('engineering.reviews.record', {
                'review_id':env.plan.review_id, 'request_version':request.version,
                'fence':request.fence, 'raw_response_utf8':raw.decode()},
                context('record-source-review')))
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 0
        # the same frozen plan still resolves under its own pin, and refuses a moved one
        assert env.bindings.review_inputs(context('unchanged-pin'), env.plan)['standard'] is not None
        variant = copy.copy(env.bindings)
        variant.method_ref = replace(env.bindings.method_ref, snapshot_digest=Digest('sha256', '0' * 64))
        with pytest.raises(Exception):
            variant.plan(context('changed-method-pin'), 'local-source-review')
    finally:
        close_chain(env)


def test_recorded_review_is_idempotent_and_locates_every_check(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        _, recorded, receipt = request_and_run_review(env)
        assert recorded.result['verdict'] == 'pass'
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 1
        # exact replay of the same envelope is idempotent: same identity, no second row
        again = asyncio.run(env.service.execute('engineering.reviews.record', {
            'review_id':env.plan.review_id, 'request_version':recorded.result['request_version'],
            'fence':recorded.result['fence'],
            'raw_response_utf8':canonical_bytes(receipt).decode()},
            context('record-source-review')))
        assert again.result == recorded.result
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 1
        # the saved record is queryable and locates every check through its own evidence
        resolved = asyncio.run(env.service.query('engineering.references.resolve',
            {'ref':recorded.result['review_ref']}, context('resolve-recorded-review'))).record
        assert resolved.complete is True and resolved.verdict == 'pass'
        assert len(resolved.completed_check_keys) == len(env.plan.check_keys)
        assert {o.check_key.criterion_id for o in resolved.observations} == set(CHECK_IDS)
        assert resolved.raw_response_ref.digest.hex == sha256(canonical_bytes(receipt)).hexdigest()
        read_back = decode_json(env.blobs.read_verified(resolved.raw_response_ref))
        assert read_back == receipt
        assert all(row['native_run_ref'] == receipt['run_id'] for row in read_back['result']['checks'])
        assert all(row['evidence'] for row in read_back['result']['checks'])
    finally:
        close_chain(env)
