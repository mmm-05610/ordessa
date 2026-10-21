"""Candidate producer for exact frozen nominal-choice JEV questions.

This module deliberately consumes original, already validated owner objects.
It does not query repositories, infer a Claim from rendered prose, or accept
caller-authored question/input text. Other check kinds remain unavailable.
"""
from dataclasses import asdict
import hashlib

from ordessa_decision.definitions import DecisionQuestion, PolicyRef
from ordessa_decision.definitions.values import canonical
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_answers import nominal_binding
from ordessa_engineering.domain.artifacts.models import (
    ArtifactRevision, BlobPayload, InlinePayload, MethodPayload,
)
from ordessa_engineering.domain.artifacts.provenance import ExcerptCapture, VersionCapture
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.models import Proposal
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.methods.definitions.models.compiled import (
    ChoiceVocabulary, CompiledProgram, DecisionDefinition, QuestionDefinition,
    thaw_value,
)
from ordessa_engineering.methods.definitions.models.compiled import StandardDefinition
from ordessa_engineering.methods.definitions.models.snapshot import MethodSnapshot
from ordessa_engineering.domain.reviews.models import CheckKey, ReviewPlan


# Keep comfortably below DecisionQuestion's canonical DTO limit. Oversized
# inputs are refused whole; this builder has no truncation mode.
MAX_QUESTION_INPUT_BYTES = 128 * 1024


def _unavailable():
    raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')


def _bytes_text(value):
    try:
        return value.decode('utf-8', errors='strict')
    except (AttributeError, UnicodeDecodeError):
        _unavailable()


def _payload_bytes(revision, budget):
    payload = revision.payload
    if type(payload) is InlinePayload:
        return payload.content_bytes()
    if type(payload) is BlobPayload:
        return budget.read(payload.blob_ref)
    if type(payload) is MethodPayload:
        return payload.content_bytes()
    _unavailable()


def _source_excerpt(source, budget):
    capture = source.capture
    if type(capture) is VersionCapture:
        raise ApplicationError('SOURCE_VERSION_UNAVAILABLE')
    if type(capture) is not ExcerptCapture or source.kind == 'artifact':
        raise ApplicationError('SOURCE_OWNER_UNAVAILABLE')
    captured = budget.selectors.check(budget.read(capture.blob_ref),
        capture.selector, capture.excerpt_digest)
    return captured


def _link_input(link, budget):
    source = link.source_ref
    excerpt = _source_excerpt(source, budget)
    selected = budget.selectors.check(excerpt, link.source_selector)
    return {
        'source': asdict(source),
        'relation': link.relation,
        'rationale': link.rationale,
        'selected_text': _bytes_text(selected),
        'selected_digest': hashlib.sha256(selected).hexdigest(),
    }


def _compiled_question(snapshot, standard, criterion):
    if type(snapshot) is not MethodSnapshot or type(snapshot.program) is not CompiledProgram:
        _unavailable()
    bindings = thaw_value(criterion.checks[0].bindings)
    question_set = bindings.get('question_set')
    if type(question_set) is not dict or question_set.get('kind') != 'question_set':
        _unavailable()
    resource_id = question_set.get('resource_id')
    specs = [spec for spec in snapshot.program.decision_definitions
        if spec.resource_ref.resource_id == resource_id]
    if (len(specs) != 1 or type(specs[0]) is not DecisionDefinition
            or specs[0].resource_ref.sha256 != question_set.get('sha256')):
        _unavailable()
    spec = specs[0]
    if any(type(q) is not QuestionDefinition for q in spec.questions):
        _unavailable()
    questions = [q for q in spec.questions
        if q.answer_definition.field == 'answer_vocabulary'
        and q.answer_definition.from_criterion.resource_ref == standard.resource_ref
        and q.answer_definition.from_criterion.criterion_id == criterion.criterion_id
        and any(ref.resource_ref == standard.resource_ref
            and ref.criterion_id == criterion.criterion_id for ref in q.criterion_refs)]
    if (spec.input_contract != 'EvidenceRequiredClaimInput'
            or set(spec.required_input_slots) != {
                'claim', 'captured_sources', 'counter_sources', 'resolved_criterion'}
            or spec.result_contract != 'DecisionResult.v1'
            or spec.iteration != 'each_evidence_required_claim'
            or spec.truncation_policy != 'reject'
            or spec.missing_required_evidence != 'do_not_invoke'
            or spec.evidence_order != 'source_id_then_selector'
            or len(questions) != 1 or questions[0].kind != 'choice'
            or len(questions[0].criterion_refs) != 1
            or type(criterion.answer_vocabulary) is not ChoiceVocabulary
            ):
        _unavailable()
    return spec, questions[0]


def build_nominal_jev_questions(*, uow, budget, proposal, revisions, snapshot,
        plan, request, standard, policy_ref):
    """Build one exact JEV question per nominal ``claim_support`` check.

    The caller must invoke this inside the original MethodControl guard and UoW,
    passing that operation's validated Proposal/revision graph and material
    budget. This pure builder does not authenticate the UoW/budget or perform
    repository lookups; it rechecks local identity/content bindings.
    It returns ``ConfiguredJevQuestion`` values for the existing bounded-run
    entry. Any non-nominal check or unsupported source shape refuses the batch.
    """
    if (uow is None or budget is None or type(proposal) is not Proposal
            or type(revisions) is not tuple
            or not revisions or any(type(item) is not ArtifactRevision for item in revisions)
            or type(snapshot) is not MethodSnapshot
            or type(snapshot.program) is not CompiledProgram
            or type(plan) is not ReviewPlan or request is None
            or type(policy_ref) is not PolicyRef):
        _unavailable()
    if type(standard) is not StandardDefinition:
        _unavailable()
    if (request.scope != plan.scope or request.review_id != plan.review_id
            or request.state != 'requested'):
        raise ApplicationError('REVIEW_REQUEST_CHANGED')
    if (standard.standard_id != plan.requirement.criterion_set_ref.criterion_set_id
            or standard.resource_ref.sha256 != plan.requirement.criterion_set_ref.digest.hex):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    snapshot_ref = snapshot.ref
    method_ref = plan.requirement.method_ref
    if (snapshot_ref.method_id != method_ref.method_id
            or snapshot_ref.release_version != method_ref.release_version
            or snapshot_ref.schema_version != method_ref.schema_version
            or snapshot_ref.snapshot_digest != method_ref.snapshot_digest.hex
            or sum(s == standard for s in snapshot.program.standard_definitions) != 1):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    if (type(proposal.ref) is not ProposalRef or proposal.scope != plan.scope
            or proposal.method_ref != plan.requirement.method_ref):
        raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')

    graph = {revision.ref: revision for revision in revisions}
    if len(graph) != len(revisions):
        raise ApplicationError('INVALID_RESOLVED_GRAPH')
    roots = {mutation.proposed_ref for mutation in proposal.mutations}
    roots.update(mutation.base_ref for mutation in proposal.mutations if mutation.base_ref is not None)
    roots.update(item.owner_revision_ref for item in proposal.claim_refs)
    if not roots <= set(graph):
        raise ApplicationError('UNRESOLVED_REVIEW_TARGET')

    # The Proposal and every graph revision must account for every declared
    # source and every link. An unlinked capture cannot silently disappear from
    # the decision input; no artifact/version source owner is inferred here.
    proposal_sources = {source.source_id: source for source in proposal.basis_sources}
    if len(proposal_sources) != len(proposal.basis_sources):
        raise ApplicationError('MATERIAL_CONTENT_INVALID')
    proposal_linked = set()
    for link in proposal.evidence_links:
        if proposal_sources.get(link.source_ref.source_id) != link.source_ref:
            raise ApplicationError('MATERIAL_CONTENT_INVALID')
        proposal_linked.add(link.source_ref.source_id)
    if proposal_linked != set(proposal_sources):
        raise ApplicationError('MATERIAL_CONTENT_INVALID')
    for revision in revisions:
        revision_sources = {source.source_id: source for source in revision.sources}
        if len(revision_sources) != len(revision.sources):
            raise ApplicationError('MATERIAL_CONTENT_INVALID')
        revision_linked = set()
        for link in revision.evidence_links:
            if revision_sources.get(link.source_ref.source_id) != link.source_ref:
                raise ApplicationError('MATERIAL_CONTENT_INVALID')
            revision_linked.add(link.source_ref.source_id)
        if revision_linked != set(revision_sources):
            raise ApplicationError('MATERIAL_CONTENT_INVALID')

    criteria = [c for c in standard.criteria if c.criterion_id == 'claim_support']
    if len(criteria) != 1:
        _unavailable()
    criterion = criteria[0]
    if (len(criterion.checks) != 1 or criterion.decision_policy is not None
            or type(criterion.answer_vocabulary) is not ChoiceVocabulary):
        _unavailable()
    if nominal_binding(criterion) is None:
        _unavailable()
    spec, question_spec = _compiled_question(snapshot, standard, criterion)
    check_keys = tuple(k for k in plan.check_keys if k.criterion_id == criterion.criterion_id)
    if not check_keys or any(type(k) is not CheckKey or type(k.target.ref) is not ArtifactRevisionRef
            or k.claim_id is None for k in check_keys):
        _unavailable()

    from .engineering_jev_run import ConfiguredJevQuestion
    review_binding = {
        'scope': asdict(plan.scope), 'review_id': plan.review_id,
        'plan_request_digest': asdict(plan.request_digest),
        'request_version': request.version, 'fence': request.fence,
    }
    result = []
    seen = set()
    for key in check_keys:
        revision = graph.get(key.target.ref)
        if revision is None:
            raise ApplicationError('UNRESOLVED_REVIEW_TARGET')
        claim_matches = [c for c in revision.claims if c.claim_id == key.claim_id]
        if len(claim_matches) != 1:
            raise ApplicationError('METHOD_CLAIM_TARGET_UNAVAILABLE')
        claim = claim_matches[0]
        claim_bytes = budget.selectors.check(_payload_bytes(revision, budget),
            claim.selector, claim.statement_digest)

        proposal_links = [link for link in proposal.evidence_links
            if link.claim_ref.owner_revision_ref == revision.ref
            and link.claim_ref.claim_id == claim.claim_id
            and link.claim_ref.statement_digest == claim.statement_digest]
        revision_links = [link for link in revision.evidence_links if link.claim_id == claim.claim_id]
        links = proposal_links + revision_links
        links = sorted(links, key=lambda link: (link.source_ref.source_id,
            canonical_bytes(asdict(link.source_selector))))
        entries = tuple(_link_input(link, budget) for link in links)
        if not entries:
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        captured_sources = tuple(entries)
        counter_sources = tuple(entry for entry in entries if entry['relation'] == 'contradicts')
        inputs = {
            'claim': {'owner_revision_ref': asdict(revision.ref), 'claim_id': claim.claim_id,
                'statement_digest': claim.statement_digest.hex, 'text': _bytes_text(claim_bytes)},
            'captured_sources': captured_sources,
            'counter_sources': counter_sources,
            'resolved_criterion': {'standard_id': standard.standard_id,
                'standard_revision': standard.revision,
                'resource_ref': asdict(standard.resource_ref),
                'criterion_id': criterion.criterion_id, 'statement': criterion.statement,
                'options': {option.option_id: option.description
                    for option in criterion.answer_vocabulary.options}},
        }
        state = {
            'engineering_review': dict(review_binding, check_key=asdict(key)),
            'nominal_question_input': {
                'question_set_id': spec.question_set_id,
                'question_set_version': spec.question_set_version,
                'input_mapping_version': spec.input_mapping_version,
                'question_id': question_spec.question_id,
                'question_revision': question_spec.question_revision,
                'input_complete': True,
                'input_truncated': False,
                'inputs': inputs,
            },
        }
        from .engineering_reviewer_source import frozen_input_digest
        try:
            encoded = canonical(state, max_bytes=2097152)
            input_digest = frozen_input_digest(state)
        except Exception:
            raise ApplicationError('MATERIAL_LIMIT') from None
        if len(encoded) > MAX_QUESTION_INPUT_BYTES:
            raise ApplicationError('MATERIAL_LIMIT')
        if any(len(value.encode('utf-8')) > 65536
                for value in (inputs['claim']['text'], criterion.statement, question_spec.instructions)
                + tuple(entry['selected_text'] for entry in entries)):
            raise ApplicationError('MATERIAL_LIMIT')
        question_id = question_spec.question_id + '-' + input_digest.removeprefix('sha256:')[:16]
        question = DecisionQuestion(question_id, question_spec.question_revision, 'choice',
            state, question_spec.instructions,
            {option.option_id: option.description for option in criterion.answer_vocabulary.options},
            evidence_ids=(revision.ref.artifact_id + ':' + revision.ref.revision_id,),
            allowed_answer_ids=tuple(option.option_id for option in criterion.answer_vocabulary.options),
            policy_ref=policy_ref)
        if question.question_digest in seen:
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        seen.add(question.question_digest)
        result.append(ConfiguredJevQuestion(key, question, (revision.ref,),
            input_digest=input_digest, input_truncated=False))
    return tuple(result)
