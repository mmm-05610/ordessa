"""Security and losslessness checks for itemized source-review sections."""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json

import pytest
from decision_runtime.definitions.values import canonical_bytes as decision_canonical_bytes, MAX_JOB_DOCUMENT_BYTES

from ordessa_engineering.adapters.decision import source_sections, source_reviewer
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_itemized_source_reviews import _V2_CHECK_IDS, _captured, _full_input_reviewer


_BASE_TEXT = (
    '# Baseline identity\n'
    '## Current behavior\n'
    'baseline quote\n'
    '## Current data\n'
    'baseline quote\n'
)
_PROPOSED_TEXT = (
    '# Candidate identity\n'
    '## Proposed behavior\n'
    'candidate material\n'
    '## Proposed boundary\n'
    'more candidate material\n'
)


def _source_inputs():
    rows = []
    for role, text, source_id in (
            ('base', _BASE_TEXT, 'baseline'),
            ('proposed', _PROPOSED_TEXT, 'candidate')):
        raw = text.encode('utf-8')
        ref = replace(_captured(raw), source_id=source_id)
        rows.append({'role': role, 'source_ref': asdict(ref), 'text': text})
    return rows


def _section(source, heading, *, kind='chapter', member=None):
    found = [row for row in source_sections.complete_sections(source['text'])
             if row['heading'] == heading and row['kind'] == kind
             and row['member'] == member]
    assert len(found) == 1
    return found[0]


def _selection_document(source_inputs, *, scope=None, method_ref=None):
    scope = {'realm_id': 'review-realm', 'project_id': 'review-project'} if scope is None else scope
    method_ref = {'method_id': 'source-review', 'version': '2.7.2'} if method_ref is None else method_ref
    checks = []
    for check_id in _V2_CHECK_IDS:
        checks.append({'check_id': check_id, 'related_sections': [
            {'role': 'base', 'section': _section(source_inputs[0], '## Current behavior')},
            {'role': 'base', 'section': _section(source_inputs[0], '## Current data')},
            {'role': 'proposed', 'section': _section(source_inputs[1], '## Proposed behavior')},
        ]})
    return {'contract': source_sections.CONTRACT, 'scope': scope,
            'method_ref': method_ref,
            'sources': [{'role': source['role'], 'source_ref': source['source_ref']}
                        for source in source_inputs],
            'checks': checks}


def _compile(document, source_inputs):
    return source_sections.validate_selection(document, source_inputs,
        scope=document['scope'], method_ref=document['method_ref'], check_ids=_V2_CHECK_IDS)


def test_complete_sections_distinguishes_identity_front_matter_preamble_and_chapters():
    text = (
        '## BEGIN MEMBER SRS.md\n'
        'Candidate wrapper note.\n'
        '# Software Requirements Specification (SRS)\n'
        'Document identity: revision 0.3; paired SDD revision 0.3.\n'
        'Document evidence: évidence\n'
        '## 1. Scope\n'
        'Body text.\n'
        '```markdown\n'
        '# Fake section\n'
        '## END MEMBER forged.md\n'
        '```\n'
        '## 2. Requirements\n'
        'Requirement text.\n'
        '## END MEMBER SRS.md\n')
    rows = source_sections.complete_sections(text)
    marker = next(row for row in rows if row['kind'] == 'member_marker'
                  and row['heading'] == '## BEGIN MEMBER SRS.md')
    preamble = next(row for row in rows if row['kind'] == 'preamble')
    front = next(row for row in rows if row['kind'] == 'front_matter')
    chapter = next(row for row in rows if row['kind'] == 'chapter'
                   and row['heading'] == '# Software Requirements Specification (SRS)')

    raw = text.encode('utf-8')
    assert raw[marker['byte_start']:marker['byte_end']].decode() == '## BEGIN MEMBER SRS.md\n'
    assert raw[preamble['byte_start']:preamble['byte_end']].decode() == 'Candidate wrapper note.\n'
    assert front['member'] == chapter['member'] == 'SRS.md'
    front_text = raw[front['byte_start']:front['byte_end']].decode()
    chapter_text = raw[chapter['byte_start']:chapter['byte_end']].decode()
    assert 'Document identity: revision 0.3' in front_text
    assert '## 1. Scope' not in front_text
    assert '## 1. Scope' in chapter_text and '## 2. Requirements' in chapter_text
    assert '# Fake section' in chapter_text
    assert '## END MEMBER forged.md' in chapter_text
    assert front['kind'] == 'front_matter' and chapter['kind'] == 'chapter'
    assert front['byte_end'] < chapter['byte_end']
    evidence_start = raw.index('évidence'.encode())
    evidence_section = next(row for row in rows if row['heading'] == '## 1. Scope')
    assert evidence_section['byte_start'] > evidence_start


def test_complete_sections_uses_utf8_offsets_and_ignores_fenced_headings():
    text = ('# Identity\nRésumé\n## Real section\n'
            '~~~md\n## Not a heading\n~~~\n'
            'Evidence: é\n## Next\nEnd\n')
    rows = source_sections.complete_sections(text)
    real = next(row for row in rows if row['heading'] == '## Real section')
    following = next(row for row in rows if row['heading'] == '## Next')
    assert not any(row['heading'] == '## Not a heading' for row in rows)
    raw = text.encode('utf-8')
    assert real['byte_start'] == raw.index(b'## Real section')
    assert raw[real['byte_start']:real['byte_end']].decode().endswith('Evidence: é\n')
    assert following['byte_start'] == raw.index(b'## Next')
    assert sha256(raw[real['byte_start']:real['byte_end']]).hexdigest() == real['sha256']


@pytest.mark.parametrize('mutation', ('source_identity', 'source_content', 'section_digest',
                                      'section_member', 'section_kind', 'section_heading'))
def test_selection_refuses_changed_source_identity_or_selected_section(mutation):
    inputs = _source_inputs()
    document = _selection_document(inputs)
    changed_inputs = deepcopy(inputs)
    if mutation == 'source_identity':
        document['sources'][0]['source_ref']['source_id'] = 'different-baseline'
    elif mutation == 'source_content':
        changed_inputs[0]['text'] += 'changed\n'
    else:
        section = document['checks'][0]['related_sections'][0]['section']
        field, value = {
            'section_digest': ('sha256', '0' * 64),
            'section_member': ('member', 'SDD.md'),
            'section_kind': ('kind', 'front_matter'),
            'section_heading': ('heading', '## Forged section'),
        }[mutation]
        section[field] = value
    with pytest.raises(ApplicationError, match='REVIEW_SECTION_SELECTION_INVALID'):
        _compile(document, changed_inputs)


@pytest.mark.parametrize('mutation', ('partial_range', 'duplicate', 'overlap'))
def test_selection_refuses_partial_duplicate_or_overlapping_sections(mutation):
    inputs = _source_inputs()
    document = _selection_document(inputs)
    related = document['checks'][0]['related_sections']
    if mutation == 'partial_range':
        related[0]['section']['byte_end'] -= 1
    elif mutation == 'duplicate':
        related.append(deepcopy(related[0]))
    else:
        parent = _section(inputs[0], '# Baseline identity')
        related.append({'role': 'base', 'section': parent})
    with pytest.raises(ApplicationError, match='REVIEW_SECTION_SELECTION_INVALID'):
        _compile(document, inputs)


@pytest.mark.parametrize('mutation', ('scope', 'method_ref', 'check_order'))
def test_selection_refuses_scope_method_or_check_order_change(mutation):
    inputs = _source_inputs()
    document = _selection_document(inputs)
    scope, method_ref = document['scope'], document['method_ref']
    check_ids = _V2_CHECK_IDS
    if mutation == 'scope':
        scope = {'realm_id': 'other-realm', 'project_id': 'review-project'}
    elif mutation == 'method_ref':
        method_ref = {'method_id': 'source-review', 'version': '2.7.3'}
    else:
        document['checks'].reverse()
    with pytest.raises(ApplicationError, match='REVIEW_SECTION_SELECTION_INVALID'):
        source_sections.validate_selection(document, inputs, scope=scope,
            method_ref=method_ref, check_ids=check_ids)


@pytest.mark.parametrize('missing_role', ('base', 'proposed'))
def test_selection_requires_explicit_base_and_proposed_context(missing_role):
    inputs = _source_inputs()
    document = _selection_document(inputs)
    check = document['checks'][0]
    check['related_sections'] = [row for row in check['related_sections']
                                 if row['role'] != missing_role]
    with pytest.raises(ApplicationError, match='REVIEW_SECTION_SELECTION_INVALID'):
        _compile(document, inputs)


def test_selected_utf8_d_e_sections_cover_every_duplicate_quote_occurrence():
    from dataclasses import replace

    text = (
        '## BEGIN MEMBER SRS.md\n'
        '# SRS\n## Appendix D\n### D.2 Candidate requirement\nquoted-évidence\n'
        '## END MEMBER SRS.md\n'
        '## BEGIN MEMBER SDD.md\n'
        '# SDD\n## Appendix E\n### E.2 Candidate requirement\nquoted-évidence\n'
        '## END MEMBER SDD.md\n')
    raw = text.encode('utf-8')
    ref = replace(_captured(raw), source_id='candidate')
    source = {'role': 'proposed', 'source_ref': asdict(ref), 'text': text}
    rows = source_sections.complete_sections(text)
    d_section = next(row for row in rows if row['heading'] == '### D.2 Candidate requirement')
    e_section = next(row for row in rows if row['heading'] == '### E.2 Candidate requirement')
    locations = source_reviewer._excerpt_locations(text, 'quoted-évidence')
    evidence = {'source_ref': asdict(ref), 'excerpt': 'quoted-évidence', 'locations': locations}
    selection = {'check': [{'role': 'proposed', 'section': d_section},
                           {'role': 'proposed', 'section': e_section}]}

    packed = source_sections.pack_sections(selection, [source], [evidence, evidence], 'check')
    assert tuple(location['member'] for location in locations) == ('SRS.md', 'SDD.md')
    assert tuple(location['section'] for location in locations) == (
        '### D.2 Candidate requirement', '### E.2 Candidate requirement')
    assert packed['caller_evidence_occurrences'] == [0, 0]
    assert packed['caller_evidence'] == [evidence]
    assert packed['sources'][0]['selected_sections'] == [
        {**d_section, 'block_id': 'b0'}, {**e_section, 'block_id': 'b1'}]
    for section in packed['sources'][0]['selected_sections']:
        block = packed['source_text_blocks'][section['block_id']].encode('utf-8')
        assert text.encode()[section['byte_start']:section['byte_end']] == block

    only_d = {'check': [{'role': 'proposed', 'section': d_section}]}
    with pytest.raises(ApplicationError, match='REVIEW_SECTION_EVIDENCE_UNCOVERED'):
        source_sections.pack_sections(only_d, [source], [evidence], 'check')


def test_equal_selected_text_blocks_share_bytes_without_merging_source_occurrences():
    text = '# Same\n## Shared section\nIdentical body.\n'
    raw = text.encode()
    baseline_ref = replace(_captured(raw), source_id='baseline')
    candidate_ref = replace(_captured(raw), source_id='candidate')
    inputs = [
        {'role': 'base', 'source_ref': asdict(baseline_ref), 'text': text},
        {'role': 'proposed', 'source_ref': asdict(candidate_ref), 'text': text},
    ]
    section = _section(inputs[0], '## Shared section')
    selection = {'check': [{'role': 'base', 'section': section},
                           {'role': 'proposed', 'section': section}]}
    packed = source_sections.pack_sections(selection, inputs, [], 'check')
    assert packed['source_text_blocks'] == {'b0': '## Shared section\nIdentical body.\n'}
    assert [row['role'] for row in packed['sources']] == ['base', 'proposed']
    assert [row['source_ref'] for row in packed['sources']] == [
        asdict(baseline_ref), asdict(candidate_ref)]
    assert all(row['selected_sections'][0]['block_id'] == 'b0'
               for row in packed['sources'])


def test_section_selection_adds_independent_input_policy_and_stable_question_request_flow():
    baseline = ('# Baseline\n## Current behavior\nbaseline quote\n'
                '## Current data\nbaseline quote\n').encode()
    candidate = ('# Candidate\n## Proposed behavior\ncandidate material\n'
                 '## Proposed boundary\nmore candidate material\n').encode()
    reviewer, context, plan, selected, _ = _full_input_reviewer(
        baseline_raw=baseline, candidate_raw=candidate, excerpt='baseline quote')
    original_policy = deepcopy(selected['policy'])
    original_selected, full_questions, full_flow, full_request = reviewer._inputs(
        context, plan, 0, 1)
    assert original_selected['policy'] == original_policy

    source_inputs = [
        {'role': 'base', 'source_ref': asdict(reviewer.bindings.baseline),
         'text': baseline.decode()},
        {'role': 'proposed', 'source_ref': asdict(reviewer.bindings.candidate),
         'text': candidate.decode()},
    ]
    scope, method_ref = asdict(context.scope), asdict(plan.requirement.method_ref)
    manifest = _selection_document(source_inputs, scope=scope, method_ref=method_ref)
    section_raw = json.dumps(manifest, separators=(',', ':')).encode('utf-8')
    section_ref = _captured(section_raw)
    selected['question_materials_ref'] = section_ref
    original_read = reviewer.materials.read

    def read(ref_context, ref):
        if ref == section_ref:
            return section_raw
        return original_read(ref_context, ref)

    reviewer.materials.read = read
    selected_once, questions, flow, request = reviewer._inputs(context, plan, 0, 1)
    selected_twice, repeated_questions, repeated_flow, repeated_request = reviewer._inputs(
        context, plan, 0, 1)

    assert tuple(question.question_id for question in questions) == _V2_CHECK_IDS
    assert tuple(question.version for question in questions) == ('2',) * 8
    assert tuple(question.version for question in full_questions) == ('1',) * 8
    assert questions[0].question_digest != full_questions[0].question_digest
    assert request.request_digest != full_request.request_digest
    assert sha256(decision_canonical_bytes(flow, maximum=MAX_JOB_DOCUMENT_BYTES)).hexdigest() != sha256(decision_canonical_bytes(full_flow, maximum=MAX_JOB_DOCUMENT_BYTES)).hexdigest()
    assert [question.question_digest for question in questions] == [
        question.question_digest for question in repeated_questions]
    assert request.request_digest == repeated_request.request_digest
    assert sha256(decision_canonical_bytes(flow, maximum=MAX_JOB_DOCUMENT_BYTES)).hexdigest() == sha256(decision_canonical_bytes(repeated_flow, maximum=MAX_JOB_DOCUMENT_BYTES)).hexdigest()
    assert selected_once['policy'] == selected_twice['policy'] == original_policy
    assert selected_once['caller_materials_ref'] == selected_twice['caller_materials_ref']

    method_policy_ref = questions[0].policy_ref
    input_policy_ref = questions[0].bounded_state['input_policy']
    assert method_policy_ref.policy_id == 'source-review-binding'
    assert method_policy_ref.version == '2'
    assert input_policy_ref['policy_id'] == source_sections.CONTRACT
    assert input_policy_ref['version'] == '1'
    assert len(flow['input']['policy_refs']) == 2
    assert flow['input']['policy_refs'][0] == asdict(method_policy_ref)
    assert flow['input']['policy_refs'][1] == input_policy_ref
    assert questions[0].bounded_state['question_materials_ref'] == asdict(section_ref)
    assert questions[0].bounded_state['source_representation'] == source_sections.CONTRACT
    assert 'COMPLETE original baseline and candidate captures' in \
        questions[0].bounded_state['representation_instructions']


def test_published_source_review_plan_pins_selector_and_preserves_method_release(tmp_path):
    from contextlib import contextmanager
    from pathlib import Path

    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.decision.source_bindings import DeclaredSourceReviewBindings
    from ordessa_engineering.application.api.method_publication import publish_method_declaration
    from ordessa_engineering.application.assembly import build_method_management
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    from ordessa_engineering.domain.artifacts.provenance import (
        SourceLocator, SourceRef, VersionCapture,
    )
    from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.methods import load_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

    root = Path(__file__).resolve().parents[4]
    method_directory = root / 'methods/incremental-engineering/candidates/2.7.2'
    scope = Scope('section-selector-plan-test', 'caller-authored-project')
    author = ActorRef('section-selector-author', 'human', 'controlled-local-caller')
    principal_id = 'section-selector-principal'
    now = '2026-10-17T12:00:00.000000Z'

    def context(request_id):
        return CommandContext(scope, principal_id, author, request_id, now,
                              'section-selector-plan-test')

    class LocalAccess:
        def require(self, ctx, operation):
            if ctx.scope != scope or ctx.principal_id != principal_id:
                raise ApplicationError('ACCESS_DENIED')

    class LocalMethodManagement:
        @contextmanager
        def guard_management(self, ctx, operation, method, parameters):
            LocalAccess().require(ctx, operation)
            if operation != 'engineering.methods.control':
                raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
            yield record_digest('controlled-local-method-control', {
                'scope': asdict(ctx.scope), 'operation': operation,
                'parameters': parameters})

    library = EngineeringLibrary.create((tmp_path / 'engineering.sqlite').resolve(),
        library_id='section-selector-plan-test', schema_version=16)
    try:
        factory = SQLiteUoWFactory(library)
        snapshots = SQLiteSnapshotStore(library)
        loaded = load_method(MethodSource(method_directory, 'method.json'), FileResourceReader())
        assert loaded.ok, loaded.error
        published = publish_method_declaration(loaded.value, snapshots)
        assert published.ok, published.error
        method = published.value
        controls = SQLiteMethodControl(factory, snapshots)
        management = build_method_management(factory, access=LocalAccess(), snapshots=snapshots,
            management=LocalMethodManagement())
        management.control(method, context('enable-source-review-method'), expected_version=0,
            enabled=True, reason='controlled local source-review plan validation')

        def captured(logical_id, raw):
            return SourceRef(logical_id, 'document',
                SourceLocator('document', provider='project-files', document_id=logical_id),
                VersionCapture('v1', Digest('sha256', sha256(raw).hexdigest())),
                now, author, 'application/json', len(raw))

        baseline = captured('selector-baseline', b'# Pinned baseline\n')
        candidate = captured('selector-candidate', b'# Pinned candidate\n')
        caller_materials = captured('caller-review-input', b'{"checks": []}')
        selector_one = captured('question-materials', b'{"selection": "one"}')
        selector_two = captured('question-materials', b'{"selection": "two"}')

        def bindings(selector_ref):
            return DeclaredSourceReviewBindings(factory, controls, scope=scope,
                method_ref=method, baseline=baseline, candidate=candidate,
                action_id='incremental.review-change',
                binding_resource_id='source-review-binding',
                criteria_resource_id='change-review-criteria',
                prompt_resource_id='change-review-prompt',
                result_schema_resource_id='review-result-schema',
                caller_input_schema_resource_id='caller-review-input-schema',
                caller_materials_ref=caller_materials,
                question_materials_ref=selector_ref, reviewer_roles=('reviewer',))

        ctx = context('derive-selector-plan')
        first_binding, second_binding = bindings(selector_one), bindings(selector_two)
        first_plan = first_binding.plan(ctx, 'selector-plan-review')
        second_plan = second_binding.plan(ctx, 'selector-plan-review')
        first_inputs = first_binding.review_inputs(ctx, first_plan)
        second_inputs = second_binding.review_inputs(ctx, second_plan)
        first_requirement = first_plan.requirement
        second_requirement = second_plan.requirement

        assert first_requirement.requirement_version == 3
        assert second_requirement.requirement_version == 3
        assert first_inputs['standard'].revision == second_inputs['standard'].revision == '3'
        assert first_requirement.criterion_set_ref.version == 3
        assert second_requirement.criterion_set_ref.version == 3
        assert first_requirement.method_ref == second_requirement.method_ref == method
        assert method.release_version == '2.7.2'
        assert first_requirement.method_resource_refs == second_requirement.method_resource_refs
        assert all(ref.method_ref == method for ref in first_requirement.method_resource_refs)
        assert first_inputs['refs'] == second_inputs['refs']
        assert first_requirement.criterion_set_ref.criterion_set_id != \
            second_requirement.criterion_set_ref.criterion_set_id
        assert first_requirement.criterion_set_ref.digest == second_requirement.criterion_set_ref.digest
        assert first_requirement.criterion_set_ref.digest.hex == \
            first_inputs['standard'].resource_ref.sha256
        assert second_requirement.criterion_set_ref.digest.hex == \
            second_inputs['standard'].resource_ref.sha256
        assert first_plan.plan_digest != second_plan.plan_digest
        assert first_plan.request_digest != second_plan.request_digest
        assert first_binding.question_materials_ref == selector_one
        assert second_binding.question_materials_ref == selector_two

        class ControlledSourceMaterials:
            def __init__(self, source_factory, materials):
                self.factory = source_factory
                self.materials = materials

            def read(self, read_context, ref):
                if read_context.scope != scope:
                    raise ApplicationError('ACCESS_DENIED')
                for exact, raw in self.materials:
                    if ref == exact:
                        return raw
                raise ApplicationError('SOURCE_VERSION_UNAVAILABLE')

        source_materials = ControlledSourceMaterials(factory, (
            (baseline, b'# Pinned baseline\n'),
            (candidate, b'# Pinned candidate\n'),
        ))
        admission = EngineeringReviewAdmission(factory, controls, None,
            source_materials=source_materials, method_guard=controls,
            source_review_bindings=first_binding)
        with admission.guard_plan(ctx, first_plan):
            assert first_inputs['standard'].resource_ref.sha256 == \
                first_requirement.criterion_set_ref.digest.hex
    finally:
        library.close()


@pytest.mark.parametrize('attack', [None, 'roles', 'withdraw', 'fence', 'provider', 'await-disable'])
def test_selected_sections_native_eight_check_chain_records_and_reopens_original_terminal(tmp_path, attack):
    import asyncio
    from contextlib import contextmanager
    from pathlib import Path

    from decision_runtime import DecisionAnswer, FilesystemEvidenceStore, PolicyRef, default_host_limits
    from decision_runtime.evidence import EvidenceScope
    from ordessa_engineering.adapters.decision.source_job import SourceReviewJobServices
    from ordessa_infrastructure.encoding import decode_json
    from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.decision.source_bindings import DeclaredSourceReviewBindings
    from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
    from ordessa_engineering.application.api.method_publication import publish_method_declaration
    from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service, build_method_management
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
    from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.codec import encode_plan
    from ordessa_engineering.methods import load_method
    from ordessa_engineering.methods.definitions.models import MethodSource

    repository = Path(__file__).resolve().parents[4]
    method_directory = repository / 'methods/incremental-engineering/candidates/2.7.2'
    scope = Scope('sections-native-chain', 'caller-authored-project')
    author = ActorRef('sections-native-author', 'human', 'controlled-local-caller')
    reviewer_actor = ActorRef('sections-native-reviewer', 'service', 'explicit-host-selection')
    principal_id = 'sections-native-principal'
    now = '2026-10-17T12:00:00.000000Z'
    selector_ref = None

    def context(request_id):
        return CommandContext(scope, principal_id, author, request_id, now, 'sections-native-chain')

    class LocalAccess:
        def require(self, ctx, operation):
            if ctx.scope != scope or ctx.principal_id != principal_id:
                raise ApplicationError('ACCESS_DENIED')

    class LocalMethodManagement:
        @contextmanager
        def guard_management(self, ctx, operation, method, parameters):
            LocalAccess().require(ctx, operation)
            if operation != 'engineering.methods.control':
                raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
            yield record_digest('controlled-local-method-control', {
                'scope': asdict(ctx.scope), 'operation': operation, 'parameters': parameters})

    class ControlledProvider:
        binding_ref = 'controlled-sections-native-provider/1'
        settings_digest = 'sha256:' + 'e' * 64

        def __init__(self):
            self.questions = []
            self.physical = []

        async def decide(self, question, invocation):
            self.questions.append(question)
            assert question.kind == 'choice'
            assert question.version == '2'
            assert question.bounded_state['source_representation'] == source_sections.CONTRACT
            assert question.bounded_state['question_materials_ref'] == asdict(selector_ref)
            if len(self.questions) == 1:
                if attack == 'roles':
                    reviewer.roles = ('revoked-role',)
                elif attack == 'provider':
                    self.settings_digest = 'sha256:' + 'f' * 64
                elif attack in ('withdraw', 'fence'):
                    with factory.begin(scope, 'write') as uow:
                        if attack == 'withdraw':
                            uow.reviews.withdraw_request(plan.review_id, expected_version=0, fence=1)
                        else:
                            # Controlled original-DB adversary: change the fence
                            # without changing the caller's previously read DTO.
                            uow.reviews.access.execute('UPDATE eng_review_requests SET fence=fence+1 WHERE review_id=?',
                                                       (plan.review_id,))
                        uow.commit()
            invocation.claim(question, self.settings_digest)
            self.physical.append(question.question_id)
            if attack == 'await-disable' and len(self.physical) == 1:
                # A real method-control transaction on another thread must
                # finish while the response await is in progress.
                await asyncio.wait_for(asyncio.to_thread(management.control, method,
                    context('disable-during-response'), expected_version=1, enabled=False,
                    reason='Controlled response-time method stop'), 2)
            return DecisionAnswer(question.question_id, 'choice', 'passed', {
                'selection_status': 'unique', 'question_digest': question.question_digest,
                'provider_settings_digest': self.settings_digest, 'resolved_model': 'controlled',
                'requested_model': 'controlled', 'protocol_validation_version': 'controlled/1',
                'probabilities': {key: float(key == 'passed') for key in question.options}}, {'status': 'unknown'})

    def project_ref(logical_id, raw):
        return SourceRef(logical_id, 'document',
            SourceLocator('document', provider='project-files', document_id=logical_id),
            VersionCapture('v1', Digest('sha256', sha256(raw).hexdigest())), now, author,
            'application/json' if logical_id.endswith('.json') else 'text/markdown', len(raw))

    baseline_raw, candidate_raw = _BASE_TEXT.encode(), _PROPOSED_TEXT.encode()
    baseline = project_ref('baseline.md', baseline_raw)
    candidate = project_ref('candidate.md', candidate_raw)
    caller_checks = [{'check_id': check_id, 'claim': f'Caller claim for {check_id}.',
        'evidence': [{'source_ref': asdict(baseline), 'excerpt': 'baseline quote'}]}
        for check_id in _V2_CHECK_IDS]
    caller_value = {'scope': asdict(scope), 'baseline': asdict(baseline),
                    'candidate': asdict(candidate), 'checks': caller_checks}
    caller_raw = json.dumps(caller_value, ensure_ascii=False, separators=(',', ':')).encode()
    caller_ref = project_ref('caller-review-input.json', caller_raw)
    source_inputs = [
        {'role': 'base', 'source_ref': asdict(baseline), 'text': baseline_raw.decode()},
        {'role': 'proposed', 'source_ref': asdict(candidate), 'text': candidate_raw.decode()},
    ]
    library = EngineeringLibrary.create((tmp_path / 'engineering.sqlite').resolve(),
        library_id='sections-native-chain', schema_version=16)
    materials = sink = reviewer = None
    try:
        factory = SQLiteUoWFactory(library)
        snapshots = SQLiteSnapshotStore(library)
        loaded = load_method(MethodSource(method_directory, 'method.json'), FileResourceReader())
        assert loaded.ok, loaded.error
        published = publish_method_declaration(loaded.value, snapshots)
        assert published.ok, published.error
        method = published.value
        checks = []
        for check_id in _V2_CHECK_IDS:
            checks.append({'check_id': check_id, 'related_sections': [
                {'role': 'base', 'section': _section(source_inputs[0], '## Current behavior')},
                {'role': 'base', 'section': _section(source_inputs[0], '## Current data')},
                {'role': 'proposed', 'section': _section(source_inputs[1], '## Proposed behavior')},
            ]})
        selector_value = {'contract': source_sections.CONTRACT,
            'scope': asdict(scope), 'method_ref': asdict(method),
            'sources': [{'role': row['role'], 'source_ref': row['source_ref']}
                        for row in source_inputs], 'checks': checks}
        selector_raw = json.dumps(selector_value, ensure_ascii=False,
                                  separators=(',', ':')).encode()
        selector_ref = project_ref('question-materials.json', selector_raw)
        controls = SQLiteMethodControl(factory, snapshots)
        management = build_method_management(factory, access=LocalAccess(), snapshots=snapshots,
            management=LocalMethodManagement())
        management.control(method, context('enable-section-review-method'), expected_version=0,
            enabled=True, reason='controlled local sections source-review chain')

        project = tmp_path / 'caller-files'
        project.mkdir()
        files = ((baseline, 'baseline.md', baseline_raw),
                 (candidate, 'candidate.md', candidate_raw),
                 (caller_ref, 'caller-review-input.json', caller_raw),
                 (selector_ref, 'question-materials.json', selector_raw))
        for _ref, path, raw in files:
            (project / path).write_bytes(raw)
        materials = ProjectSourceMaterials(factory, scope=scope, root=project,
            source_mappings=tuple((ref, path) for ref, path, _raw in files))
        bindings = DeclaredSourceReviewBindings(factory, controls, scope=scope, method_ref=method,
            baseline=baseline, candidate=candidate, action_id='incremental.review-change',
            binding_resource_id='source-review-binding', criteria_resource_id='change-review-criteria',
            prompt_resource_id='change-review-prompt', result_schema_resource_id='review-result-schema',
            caller_input_schema_resource_id='caller-review-input-schema', caller_materials_ref=caller_ref,
            question_materials_ref=selector_ref, reviewer_roles=('reviewer',))
        plan = bindings.plan(context('sections-plan'), 'sections-native-review')
        selected = bindings.review_inputs(context('sections-selected'), plan)
        assert selected['standard'].revision == '3'
        assert selected['standard'].resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex
        assert plan.requirement.criterion_set_ref.criterion_set_id == selected['standard'].standard_id

        blobs = SQLiteBlobStore(library)
        evidence_root = tmp_path / 'decision-runs'
        evidence_root.mkdir(mode=0o700)
        evidence_owner = FilesystemEvidenceStore(evidence_root)
        evidence_scope = EvidenceScope('principal', principal_id)
        provider = ControlledProvider()
        method_resource = next(ref for ref in plan.requirement.method_resource_refs
                               if ref.resource_id == 'source-review-binding')
        method_policy = PolicyRef(method_resource.resource_id, '2',
                                  'sha256:' + method_resource.resource_digest.hex)
        services = SourceReviewJobServices(provider, evidence_owner,
            invocation_resolver=lambda ctx: ctx,
            evidence_scope_resolver=lambda *_: evidence_scope,
            invocation_context_factory=lambda ctx, request_id: replace(ctx, request_id=request_id),
            host_limits={**default_host_limits(), 'timeout_seconds': 240.0},
            job_document_max_bytes=MAX_JOB_DOCUMENT_BYTES)
        reviewer = DecisionReviewerSource(factory, blobs, controls, materials, bindings,
            scope=scope, principal_id=principal_id, reviewer=reviewer_actor,
            roles=('reviewer',), services=services)
        admission = EngineeringReviewAdmission(factory, controls, None, reviewer,
            source_materials=materials, method_guard=controls, source_review_bindings=bindings)
        service = build_engineering_service(factory, EngineeringPorts(LocalAccess(),
            review_admission=admission, blobs=blobs, source_materials=materials,
            method_guard=controls, source_review_bindings=bindings))

        requested = asyncio.run(service.execute('engineering.reviews.request',
            {'plan': decode_json(encode_plan(plan))}, context('sections-request')))
        with factory.begin(scope, 'read') as uow:
            request = uow.reviews.get_request(plan.review_id)
        assert request.state == 'requested' and request.version == 0 and request.fence == 1
        if attack is not None:
            with pytest.raises(ApplicationError) as rejected:
                asyncio.run(reviewer.run_review(context('sections-run'), plan, request))
            assert rejected.value.code == 'DECISION_REVIEW_NOT_COMPLETED'
            assert rejected.value.decision_status == 'unknown'
            assert len(provider.physical) == (1 if attack == 'await-disable' else 0)
            assert len(provider.questions) == (2 if attack == 'await-disable' else 1)
            # Re-entry after revocation never executes another model attempt.
            before = len(provider.questions)
            with pytest.raises(ApplicationError):
                asyncio.run(reviewer.run_review(context('sections-retry'), plan, request))
            assert len(provider.questions) == before
            with factory.begin(scope, 'read') as uow:
                assert uow.reviews.get_request(plan.review_id).state != 'recorded'
            return
        response_ref = asyncio.run(reviewer.run_review(context('sections-run'), plan, request))
        receipt = decode_json(blobs.read_verified(response_ref))
        assert len(provider.questions) == 8
        assert tuple(question.question_id for question in provider.questions) == _V2_CHECK_IDS
        flow_policy_refs = (
            asdict(provider.questions[0].policy_ref),
            provider.questions[0].bounded_state['input_policy'],
        )
        assert flow_policy_refs[0]['policy_id'] == 'source-review-binding'
        assert flow_policy_refs[0]['version'] == '2'
        assert flow_policy_refs[0]['content_digest'] == \
            'sha256:' + method_resource.resource_digest.hex
        assert flow_policy_refs[1]['policy_id'] == source_sections.CONTRACT
        assert flow_policy_refs[1]['version'] == '1'
        assert flow_policy_refs[1]['content_digest'] == \
            'sha256:' + record_digest('source-review-input', asdict(selector_ref)).hex
        assert receipt['result']['aggregate'] == {'policy': 'all_required', 'conclusion': 'passed'}
        assert tuple(row['check_id'] for row in receipt['result']['checks']) == _V2_CHECK_IDS
        assert all(row['choice'] == 'passed' and row['native_run_ref'] == receipt['run_id']
                   for row in receipt['result']['checks'])
        recorded = asyncio.run(service.execute('engineering.reviews.record', {
            'review_id': plan.review_id, 'request_version': request.version,
            'fence': request.fence,
            'raw_response_utf8': blobs.read_verified(response_ref).decode('utf-8')},
            context('sections-record')))
        assert recorded.result['verdict'] == 'pass'

        # Current evidence is an original scoped job result and summary, never
        # a fabricated decision-evidence/1 event/manifest projection.
        _, questions, job, job_request = reviewer._inputs(context('sections-cold'), plan, 0, 1)
        original = services.reader(context('sections-cold'), job_request.request_id).read(
            job_request.request_id, job, questions, provider_binding=provider.binding_ref,
            provider_settings=provider.settings_digest)
        assert original.operation_ref == receipt['run_id']
        assert len(original.answers) == 8
        assert [answer.answer_digest for answer in original.answers] == [
            row['answer_digest'] for row in receipt['result']['checks']]
        assert requested.result['request']['state'] == 'requested'
    finally:
        if reviewer is not None:
            reviewer.close()
        if materials is not None:
            materials.close()
        if sink is not None:
            asyncio.run(sink.close())
        library.close()


def test_frozen_historical_eight_check_manifest_and_terminal_are_read_by_original_reader(tmp_path):
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    from decision_runtime.historical import FileEvidenceReader, ReadContext
    from decision_runtime.historical.models import DecisionQuestion, PolicyRef
    vector = json.loads((Path(__file__).parent / 'fixtures/source-review-history/historical-vector.json').read_text())
    evidence_root = tmp_path / 'frozen-history'
    evidence_root.mkdir(mode=0o700)
    directory = evidence_root / vector['run_id']; directory.mkdir(mode=0o700)
    for name, raw in [('events.jsonl', vector['events_jsonl']), ('terminal.json', vector['terminal_json']), ('writer.lock', '')]:
        target = directory / name; target.write_text(raw); target.chmod(0o600)
    receipt = {'run_id': vector['run_id']}
    read_context = ReadContext(object(), 'sections-native-chain')
    provider = SimpleNamespace(questions=[DecisionQuestion.from_dict(q) for q in vector['questions']])
    # Independent input policy data was part of the original frozen manifest.
    provider.questions[0].bounded_state  # no execution or new permission
    expected_policies = vector['policies']
    async def cold_read():
        reader = FileEvidenceReader(evidence_root, read_context=ReadContext(
            read_context.authority, read_context.scope_ref))
        try:
            return await reader.read(receipt['run_id'], reader.read_context)
        finally:
            await reader.close()
    native = asyncio.run(cold_read())
    assert native['status'] == 'completed' and native['call_evidence'] == 'recorded'
    events = [event['payload'] for event in native['events']]
    assert sum(event['type'] == 'call.intent' for event in events) == 8
    assert sum(event['type'] == 'call.response' for event in events) == 8
    terminal = native['terminal']
    assert terminal['run_id'] == receipt['run_id'] and terminal['status'] == 'completed'
    assert terminal['result']['status'] == 'completed'
    assert terminal['result']['effective_policy_refs'] == expected_policies
    assert terminal['result']['run_manifest_digest'] == native['events'][0]['payload']['manifest_digest']


def test_historical_flow_code_digest_is_bound_to_preserved_original_source_bytes():
    from pathlib import Path
    from ordessa_engineering.adapters.decision.source_history import FROZEN_CODE_DIGESTS
    from decision_runtime.historical.models import PolicyRef
    from decision_runtime.historical.values import digest
    root = Path(__file__).parent / 'fixtures/source-review-history'
    provenance = json.loads((root / 'provenance.json').read_text())
    for path, expected in provenance['source_sha256'].items():
        assert sha256((root / (Path(path).name + '.txt')).read_bytes()).hexdigest() == expected
    for name, filenames in [('single', ['source_reviewer.py']),
                            ('sections', ['source_reviewer.py', 'source_sections.py'])]:
        reviewed = sha256(b'decision.reviewed-code/1\n')
        for filename in sorted(filenames):
            raw = (root / (filename + '.txt')).read_bytes()
            reviewed.update(str(len(raw)).encode() + b'\n' + raw + b'\n')
        assert 'sha256:' + reviewed.hexdigest() == FROZEN_CODE_DIGESTS[name]
        assert FROZEN_CODE_DIGESTS[name] == provenance['reviewed_code_digests'][name]
    vector = json.loads((root / 'historical-vector.json').read_text())
    terminal = json.loads(vector['terminal_json'])['terminal']
    expected = digest('flow', {'reviewed_code_digest': FROZEN_CODE_DIGESTS['sections'],
        'policy_refs': tuple(PolicyRef.from_dict(p) for p in vector['policies'])})
    assert terminal['result']['flow_ref']['content_digest'] == expected
