"""Actual 2.2 candidate loader/compiler/SQLite snapshot; no semantic model call.

The fixture catalog is explicitly host-admitted only for this isolated test.
Formal revision claims are authoritative; body-to-formal-claim business coverage
and authenticated reviewer provenance are separate, not inferred here.
"""
from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import json
import pytest
from test_proposal_usecases import SCOPE, ACTOR, CREATED_AT
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import MethodSource, CompilationCapabilities, CapabilityDescriptor
from ordessa_engineering.domain.artifacts.models import ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.provenance import Claim
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet

ROOT = Path(__file__).resolve().parents[4] / 'methods/incremental-engineering'
CANDIDATE = ROOT / 'candidates/2.2.0'
CASES = json.loads((CANDIDATE/'tests/per-claim-cases.json').read_bytes())['cases']


def published(library, root):
    catalog = json.loads((root/'contracts/capability-catalog.json').read_bytes())
    assert catalog['fixture_only'] is True
    caps = CompilationCapabilities(tuple(CapabilityDescriptor(r['capability_id'], r['kind'],
        r['interface_version'], r['contract_digest'], r['contract']) for r in catalog['capabilities']),
        'explicit-per-claim-test-host', 'host')
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, caps, 'ordessa.methods/v2')
    assert compiled.ok, compiled.error
    class Catalog:
        def read_current(self): return caps
    store = SQLiteSnapshotStore(library)
    frozen = freeze_method(compiled.value, store, store, capability_catalog=Catalog())
    assert frozen.ok, frozen.error
    snapshot = store.get(frozen.value.ref)
    assert snapshot.ref.snapshot_digest == json.loads((root/'bundle-lock.json').read_bytes())['method_ref']['snapshot_digest']['hex']
    return snapshot


def revision(identifier='one', *, empty=False):
    # A real Q&A basis is represented as test input, never claimed authenticated.
    body = {'claims': [
        {'kind':'design_choice','statement':'Use explicit transactions.', 'source_ids':['user-qa']},
        {'kind':'observation','statement':'All updates are atomic.', 'source_ids':[]}]}
    claims = tuple(Claim('C'+str(i+1), ContentSelector('json_pointer',pointer=f'/claims/{i}/statement'),
        Digest('sha256',hashlib.sha256(canonical_bytes(c['statement'])).hexdigest())) for i,c in enumerate(body['claims']))
    return ArtifactRevision(SCOPE, 'artifact-'+identifier, 'revision-'+identifier, CREATED_AT, ACTOR,
        InlinePayload.from_value('application/json','urn:test:claim-input',body), schema_version=2,
        claims=() if empty else claims)


def binding(revisions):
    targets = tuple(Target('primary', r.ref) for r in revisions)
    return EngineeringTargetBindings(SCOPE, TargetSet(targets), tuple((t,'did') for t in targets),
        ('source_captures','claim_bindings','method_content','proposal_ref','implementation_intent'),
        ('reviewer',), 'review_sources')


@pytest.fixture
def candidate(tmp_path):
    library = EngineeringLibrary.create((tmp_path/'claims.sqlite').resolve(), library_id='per-claim', schema_version=7)
    try: yield library, published(library,CANDIDATE)
    finally: library.close()


@pytest.mark.parametrize('case', [c['id'] for c in CASES])
def test_real_candidate_counterexamples(candidate, case):
    library, snapshot = candidate
    bridge = MethodBridge()
    first, second = revision(), revision('two')
    revisions = (first,second) if case in ('same-id-different-target','reordered-input') else (first,)
    bindings = binding(revisions)
    if case == 'old-release-not-reinterpreted':
        old = published(library,ROOT)
        with pytest.raises(ApplicationError,match='METHOD_CHECK_ITERATION_UNAVAILABLE'):
            bridge.review_requirements(old,bindings,revisions=revisions)
        return
    if case == 'empty-required-claims':
        empty = revision(empty=True)
        with pytest.raises(ApplicationError,match='METHOD_REQUIRED_CLAIMS_EMPTY'):
            bridge.review_requirements(snapshot,binding((empty,)),revisions=(empty,))
        return
    if case == 'changed-statement-or-revision':
        substituted = replace(first,revision_id='substituted')
        with pytest.raises(ApplicationError,match='UNRESOLVED_REVIEW_TARGET'):
            bridge.review_requirements(snapshot,bindings,revisions=(substituted,))
        # Original revision constructor also verifies the exact selected statement.
        from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
        with pytest.raises(ReferenceError):
            replace(first,claims=(replace(first.claims[0],statement_digest=Digest('sha256','b'*64)),))
        return
    requirements = bridge.review_requirements(snapshot,bindings,revisions=revisions)
    assert {r.criterion_set_ref.criterion_set_id for r in requirements}=={'source-review','quality-review'}
    requirement = next(r for r in requirements if r.criterion_set_ref.criterion_set_id=='source-review')
    plan = bridge.review_plan(snapshot,bindings,requirement,'review',revisions=revisions)
    support = tuple(k for k in plan.check_keys if k.criterion_id=='claim_support')
    assert {(k.target.ref,k.claim_id) for k in support} == {(r.ref,c.claim_id) for r in revisions for c in r.claims}
    if case == 'omit-original-claim':
        omitted = replace(requirement,required_check_keys=tuple(k for k in requirement.required_check_keys if k.claim_id!='C2'))
        with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
            bridge.review_plan(snapshot,bindings,omitted,'review',revisions=revisions)
    if case == 'reordered-input':
        assert bridge.review_requirements(snapshot,binding(tuple(reversed(revisions))),revisions=tuple(reversed(revisions)))==requirements
        reordered = bridge.review_plan(snapshot,binding(tuple(reversed(revisions))),requirement,'review',revisions=tuple(reversed(revisions)))
        assert reordered == plan
        assert hashlib.sha256(canonical_bytes(asdict(reordered))).digest()==hashlib.sha256(canonical_bytes(asdict(plan))).digest()
    standard = next(s for s in snapshot.program.standard_definitions if s.standard_id=='source-review')
    answers = tuple(CriterionAnswer(k,'satisfied',(),'test-only semantic status') for k in plan.check_keys)
    if case == 'missing-review-answer':
        with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
            review_observations(plan,standard,tuple(a for a in answers if a.check_key!=support[-1]))
    observations = review_observations(plan,standard,answers)
    assert all(o.result=='indeterminate' for o in observations if o.check_key in support)
    if case in ('missing-evidence-retained','link-presence-not-support'):
        # Even source_integrity=satisfied cannot promote an insufficient semantic answer.
        answers = tuple(replace(a,status='insufficient') if a.check_key in support else a for a in answers)
        observations = review_observations(plan,standard,answers)
        assert all(o.result=='fail' for o in observations if o.check_key in support)
