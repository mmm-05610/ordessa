"""JEV source verification against original Decision and BlobStore authorities.

Run bindings are trusted local execution outputs, never wire parameters. Durable
Decision evidence proves the real answer; original instance capabilities prove
the currently selected service role. Neither is human authentication.
"""
import asyncio
import hashlib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from dataclasses import asdict, dataclass

from ordessa_decision.definitions import DecisionAnswer, DecisionQuestion, DecisionRequest, plain
from ordessa_decision.definitions.values import canonical
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer, VerifiedReviewResponse
from ordessa_engineering.application.orchestration.method_answers import nominal_criterion_answer
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import CurrentReviewTrust, observations_digest
from ordessa_engineering.methods.definitions.models.compiled import ChoiceVocabulary

JEV_SOURCE_CAPABILITY = 'engineering.reviewer.jev'


def frozen_input_digest(state):
    """Bind the exact bounded-state bytes with the Decision canonical encoder."""
    payload = {'contract_version':'ordessa.jev-frozen-input/1', 'state':plain(state)}
    return 'sha256:' + hashlib.sha256(canonical(payload, max_bytes=2097152)).hexdigest()


def structured_jev_answer_complete(question, answer):
    """Structural fact after the original JEV parser, never semantic quality.

    The trusted provider validates schema/probabilities before returning this
    DecisionAnswer. Durable question/answer/request matching is independently
    required before this fact reaches Engineering's nominal resolver.
    """
    if type(answer) is not DecisionAnswer or answer.kind != 'choice':
        return False
    receipt = answer.provider_receipt
    probabilities = receipt.get('probabilities')
    return (answer.question_id == question.question_id
        and receipt.get('question_digest') == question.question_digest
        and type(receipt.get('protocol_validation_version')) is str
        and bool(receipt['protocol_validation_version'])
        and isinstance(probabilities, Mapping)
        and set(probabilities) == set(question.options)
        and receipt.get('selection_status') in ('unique', 'tie')
        and 'confidence' in receipt and 'tied_option_ids' in receipt)


@dataclass(frozen=True)
class JevCheckExecution:
    check_key: object
    question: DecisionQuestion
    answer: DecisionAnswer
    evidence_refs: tuple
    input_digest: str | None = None
    input_truncated: bool | None = None
    answer_complete: bool | None = None


@dataclass(frozen=True)
class JevReviewRun:
    scope: object
    review_id: str
    plan_request_digest: object
    request_version: int
    fence: int
    run_id: str
    decision_request: DecisionRequest
    checks: tuple[JevCheckExecution, ...]
    evidence_only: bool = False


def encode_review_run(run):
    """Capture the actual structured source response, excluding model secrets."""
    return canonical({'schema':'ordessa.jev-review-source/2',
        'scope':asdict(run.scope), 'review_id':run.review_id,
        'plan_request_digest':asdict(run.plan_request_digest),
        'request_version':run.request_version, 'fence':run.fence, 'run_id':run.run_id,
        'evidence_only':run.evidence_only,
        'decision_request':plain(run.decision_request), 'checks':[
            {'check_key':asdict(c.check_key), 'question':plain(c.question),
                'answer':plain(c.answer), 'evidence_refs':[asdict(r) for r in c.evidence_refs],
                'input_digest':c.input_digest, 'input_truncated':c.input_truncated,
                'answer_complete':c.answer_complete}
            for c in run.checks]}, max_bytes=2097152)


class OriginalJevReviewerSource:
    def __init__(self, *, access, scope, blobs, evidence_reader, read_context,
            provider, runs, roles, accepted_models, flows, verifier_version='2',
            qualification_fixture=False, method_control=None):
        if (type(runs) is not tuple or not runs or any(type(r) is not JevReviewRun for r in runs)
                or len({(r.scope, r.review_id) for r in runs}) != len(runs)
                or type(roles) is not tuple or not roles or len(set(roles)) != len(roles)
                or type(accepted_models) is not tuple or not accepted_models
                or type(flows) is not tuple or not flows
                or type(qualification_fixture) is not bool):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        self.access, self.scope, self.blobs = access, scope, blobs
        self.reader, self.read_context, self.provider = evidence_reader, read_context, provider
        self.runs, self.roles, self.models = runs, roles, accepted_models
        self.qualification_fixture = qualification_fixture
        self.method_control = method_control
        for flow in flows:
            flow.validate()
        self.flows = flows
        self.binding_ref, self.settings_digest = provider.binding_ref, provider.settings_digest
        self.verifier_id, self.verifier_version = 'ordessa.jev-decision-source', verifier_version

    def _run(self, plan, *, evidence_only=False):
        matches = tuple(r for r in self.runs if r.scope == plan.scope and r.review_id == plan.review_id)
        if len(matches) != 1:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        run = matches[0]
        if run.evidence_only != evidence_only:
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        binding = {'scope':asdict(run.scope), 'review_id':run.review_id,
            'plan_request_digest':asdict(run.plan_request_digest),
            'request_version':run.request_version, 'fence':run.fence}
        if (run.plan_request_digest != plan.request_digest
                or plain(run.decision_request.extensions).get('ordessa.engineering.review') != binding
                or sum(flow.ref == run.decision_request.flow_ref for flow in self.flows) != 1):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        return run

    def _current(self, caller, plan):
        if (self.provider.binding_ref != self.binding_ref or self.provider.settings_digest != self.settings_digest
                or not set(plan.reviewer_requirements) <= set(self.roles)
                or not set(self.roles) <= set(plan.requirement.eligible_reviewer_roles)):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        return record_digest('product-jev-current-capability', {
            'scope':asdict(plan.scope), 'principal_id':caller.principal_id,
            'capability':JEV_SOURCE_CAPABILITY, 'credential_epoch':caller.credential_epoch,
            'provider_binding':self.binding_ref, 'provider_settings_digest':self.settings_digest,
            'roles':self.roles, 'accepted_models':self.models})

    @staticmethod
    def _standard_criteria(plan, standard, *, require_choice=False, check_keys=None):
        ref = plan.requirement.criterion_set_ref
        if (getattr(standard, 'standard_id', None) != ref.criterion_set_id
                or getattr(getattr(standard, 'resource_ref', None), 'sha256', None) != ref.digest.hex):
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        selected = {key.criterion_id for key in (plan.check_keys if check_keys is None else check_keys)}
        criteria = {}
        for criterion_id in selected:
            matches = [criterion for criterion in standard.criteria
                if criterion.criterion_id == criterion_id]
            if len(matches) != 1:
                raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
            criterion = matches[0]
            if (len(criterion.checks) != 1
                    or criterion.answer_vocabulary is not None
                        and type(criterion.answer_vocabulary) is not ChoiceVocabulary
                    or require_choice and type(criterion.answer_vocabulary) is not ChoiceVocabulary):
                raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
            criteria[criterion_id] = criterion
        return criteria

    @staticmethod
    def _check_facts(check, *, required=False):
        if not required:
            return
        if (type(check.input_digest) is not str or type(check.input_truncated) is not bool
                or type(check.answer_complete) is not bool):
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        expected = frozen_input_digest(check.question.bounded_state)
        if check.input_digest != expected:
            raise ApplicationError('REVIEW_SOURCE_INVALID')

    def _durable_checks(self, run, plan, raw_ref, standard, *, nominal_evidence_only=False):
        if self.blobs.read_verified(raw_ref) != encode_review_run(run):
            raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
        # The application port is synchronous, including calls in an HTTP loop.
        # Only the original read API runs in this temporary reader thread. No
        # command context, authority lock or business transaction moves threads.
        with ThreadPoolExecutor(max_workers=1) as worker:
            durable = worker.submit(asyncio.run,
                self.reader.read(run.run_id, self.read_context)).result()
        terminal = durable.get('terminal') or {}
        result = terminal.get('result') or {}
        if (durable.get('status') != 'completed' or durable.get('call_evidence') != 'recorded'
                or result.get('status') != 'completed' or result.get('run_id') != run.run_id
                or result.get('request_id') != run.decision_request.request_id
                or result.get('task_revision') != run.decision_request.task.task_revision
                or result.get('flow_ref') != plain(run.decision_request.flow_ref)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        events = [e['payload'] for e in durable.get('events', ())]
        started = [e for e in events if e.get('type') == 'run.started']
        if (len(started) != 1 or started[0].get('request_digest') != run.decision_request.request_digest
                or started[0].get('flow_digest') != run.decision_request.flow_ref.content_digest):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        intents = {e['call_id']:e for e in events if e.get('type') == 'call.intent'}
        responses = {e['call_id']:e for e in events if e.get('type') == 'call.response'}
        expected_keys = plan.check_keys
        if nominal_evidence_only:
            declared = self._standard_criteria(plan, standard)
            expected_keys = tuple(key for key in plan.check_keys
                if type(declared[key.criterion_id].answer_vocabulary) is ChoiceVocabulary)
        if (len(intents) != len(run.checks) or set(intents) != set(responses)
                or len({c.check_key for c in run.checks}) != len(run.checks)
                or {c.check_key for c in run.checks} != set(expected_keys)):
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        criteria = self._standard_criteria(plan, standard) if standard is not None else None
        verified = []
        consumed = set()
        for check in run.checks:
            question, answer = check.question, check.answer
            if check.answer_complete is True and not structured_jev_answer_complete(question, answer):
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            receipt = answer.provider_receipt
            flow = next(f for f in self.flows if f.ref == run.decision_request.flow_ref)
            question_binding = {'scope':asdict(run.scope), 'review_id':run.review_id,
                'plan_request_digest':asdict(run.plan_request_digest),
                'request_version':run.request_version, 'fence':run.fence,
                'check_key':asdict(check.check_key)}
            matching = [id for id, event in intents.items() if event['question_digest'] == question.question_digest]
            criterion = criteria[check.check_key.criterion_id] if criteria is not None else None
            vocabulary = criterion.answer_vocabulary if criterion is not None else None
            if criterion is not None and vocabulary is None and not self.qualification_fixture:
                # Deterministic or manual checks cannot be replaced with a
                # model question returning domain status names. This explicit
                # controlled protocol fixture is never a production fallback.
                raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
            self._check_facts(check, required=type(vocabulary) is ChoiceVocabulary)
            if type(vocabulary) is ChoiceVocabulary:
                expected_options = {option.option_id: option.description for option in vocabulary.options}
                options_valid = dict(question.options) == expected_options
            elif criterion is None:
                # guard_trust rechecks captured source only and has no standard
                # argument; it does not reduce answers to business statuses.
                options_valid = bool(question.options) and all(
                    type(key) is str and type(value) is str
                    for key, value in question.options.items())
            else:
                options_valid = dict(question.options) == {
                    'satisfied':'satisfied', 'violated':'violated',
                    'insufficient':'insufficient', 'unknown':'unknown'}
            selection_status = receipt.get('selection_status')
            if answer.value is None:
                tied = receipt.get('tied_option_ids', ())
                selected_valid = (selection_status == 'tie' and type(tied) in (tuple, list)
                    and len(tied) >= 2 and len(set(tied)) == len(tied)
                    and all(type(value) is str and value in question.options for value in tied))
            else:
                selected_valid = (selection_status == 'unique' and type(answer.value) is str
                    and answer.value in question.options)
            if (len(matching) != 1 or matching[0] in consumed
                    or responses[matching[0]]['answer_digest'] != answer.answer_digest
                    or receipt.get('question_digest') != question.question_digest
                    or receipt.get('provider_settings_digest') != self.settings_digest
                    or receipt.get('resolved_model') not in self.models
                    or question.policy_ref not in flow.policy_refs
                    or answer.question_id != question.question_id or answer.kind != 'choice'
                    or plain(question.bounded_state).get('engineering_review') != question_binding
                    or question.kind != 'choice' or not options_valid or not selected_valid):
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            consumed.add(matching[0])
            verified.append((check, answer, criterion))
        return tuple(verified)

    def verify_pending_evidence(self, context, plan, request, raw_response_ref, *, standard):
        """Verify the actual nominal subset without issuing review evidence DTOs."""
        run = self._run(plan, evidence_only=True)
        if (context.scope != run.scope or request.version != run.request_version
                or request.fence != run.fence or request.state != 'requested'):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY) as caller:
            self._current(caller, plan)
            verified = self._durable_checks(run, plan, raw_response_ref, standard,
                nominal_evidence_only=True)
            return tuple(nominal_criterion_answer(plan, standard, check.check_key,
                selected_option=answer.value, selection_status=answer.provider_receipt['selection_status'],
                answer_complete=check.answer_complete, input_truncated=check.input_truncated,
                evidence_refs=check.evidence_refs, rationale='Verified original JEV subset; full review pending')
                for check, answer, _ in verified)

    def verify_checks(self, context, plan, request, raw_response_ref, *, standard, check_keys):
        """rev50 leaf: actual nominal checks over the unchanged original plan.

        Frozen request fields correlate historical evidence; current request CAS
        belongs to ReviewUseCases. This method does not manufacture a reviewer
        principal, human disposition, or automatic quality admission.
        """
        from ordessa_engineering.application.contracts.mixed_reviews import (
            FrozenCheckRequest, VerifiedCheckResponse,
        )
        from ordessa_engineering.application.usecases.reviews.admission import review_observations_subset
        matches = tuple(r for r in self.runs if r.scope == plan.scope and r.review_id == plan.review_id)
        if len(matches) != 1:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        run = self._run(plan, evidence_only=matches[0].evidence_only)
        if (type(request) is not FrozenCheckRequest or request.plan_digest != plan.plan_digest
                or type(request.request_version) is not int or request.request_version < 0
                or type(request.fence) is not int or request.fence < 1
                or context.scope != run.scope or request.request_version != run.request_version
                or request.fence != run.fence):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        if (type(check_keys) is not tuple or not check_keys or len(set(check_keys)) != len(check_keys)
                or not set(check_keys) <= set(plan.check_keys)
                or set(check_keys) != {c.check_key for c in run.checks}):
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY) as caller:
            capability = self._current(caller, plan)
            verified = self._durable_checks(run, plan, raw_response_ref, standard,
                nominal_evidence_only=True)
            answers = tuple(nominal_criterion_answer(plan, standard, check.check_key,
                selected_option=answer.value, selection_status=answer.provider_receipt['selection_status'],
                answer_complete=check.answer_complete, input_truncated=check.input_truncated,
                evidence_refs=check.evidence_refs,
                rationale='Verified original JEV leaf; automatic quality remains unavailable').answer
                for check, answer, _ in verified)
            review_observations_subset(plan, standard, answers, check_keys)
            provenance = record_digest('product-jev-check-source', {
                'plan_digest':asdict(plan.plan_digest), 'request':asdict(request),
                'raw_response_ref':asdict(raw_response_ref), 'check_keys':[asdict(k) for k in check_keys],
                'answers':[asdict(a) for a in answers], 'run_id':run.run_id,
                'current_capability':asdict(capability),
                'verifier_id':self.verifier_id, 'verifier_version':self.verifier_version})
            return VerifiedCheckResponse(answers, provenance)

    @contextmanager
    def guard_checks(self, context, admissions):
        """Keep original method/source guards through the consumer's COMMIT."""
        from ordessa_engineering.application.contracts.mixed_reviews import CheckSourceAdmission
        if self.method_control is None:
            raise ApplicationError('METHOD_AUTHORITY_UNAVAILABLE')
        if getattr(getattr(self.method_control, 'factory', None), 'authority_id', None) != self.blobs.authority_id:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        if type(admissions) is not tuple or not admissions:
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        with ExitStack() as guards:
            guards.enter_context(self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY))
            for admission in admissions:
                if type(admission) is not CheckSourceAdmission:
                    raise ApplicationError('REVIEW_SOURCE_INVALID')
                plan = admission.plan
                snapshot = guards.enter_context(self.method_control.guard_method(context, plan.requirement.method_ref))
                ref = plan.requirement.criterion_set_ref
                standards = tuple(s for s in snapshot.program.standard_definitions
                    if s.standard_id == ref.criterion_set_id and s.resource_ref.sha256 == ref.digest.hex)
                if len(standards) != 1:
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                verified = self.verify_checks(context, plan, admission.request, admission.raw_response_ref,
                    standard=standards[0], check_keys=admission.check_keys)
                if verified != admission.response:
                    raise ApplicationError('UNTRUSTED_REVIEWER')
            yield

    def verify_response(self, context, plan, request, raw_response_ref, *, standard):
        run = self._run(plan)
        if (context.scope != run.scope or request.version != run.request_version
                or request.fence != run.fence or request.state != 'requested'):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY) as caller:
            capability = self._current(caller, plan)
            # Method-declared answer vocabularies require the original owner's
            # explicit semantic conversion. Four direct statuses cannot silently
            # replace actual three-choice/score/noul standard definitions.
            verified = self._durable_checks(run, plan, raw_response_ref, standard)
            answers = []
            for check, answer, criterion in verified:
                selection_status = answer.provider_receipt['selection_status']
                if type(criterion.answer_vocabulary) is ChoiceVocabulary:
                    resolution = nominal_criterion_answer(plan, standard, check.check_key,
                        selected_option=answer.value, selection_status=selection_status,
                        answer_complete=check.answer_complete, input_truncated=check.input_truncated,
                        evidence_refs=check.evidence_refs,
                        rationale='Actual JEV structured choice; bound original Decision run '+run.run_id)
                    answers.append(resolution.answer)
                else:
                    if answer.value not in {'satisfied','violated','insufficient','unknown'}:
                        raise ApplicationError('REVIEW_SOURCE_INVALID')
                    answers.append(CriterionAnswer(check.check_key, answer.value, check.evidence_refs,
                        'Actual JEV four-status qualification fixture; bound original Decision run '+run.run_id))
            answers = tuple(answers)
            observations = review_observations(plan, standard, answers)
            evidence = VerifiedReviewerEvidence(context.scope,
                ActorRef(self.binding_ref, 'checker', 'decision-runtime'), self.roles,
                self.verifier_id, self.verifier_version, caller.credential_epoch,
                plan.request_digest, raw_response_ref.digest, observations_digest(observations), capability)
            return VerifiedReviewResponse(evidence, answers)

    @contextmanager
    def guard_trust(self, context, records):
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY) as caller:
            current = []
            for record in records:
                evidence = record.reviewer_evidence
                capability = self._current(caller, record.plan)
                if (record.plan.scope != context.scope or evidence.roles != self.roles
                        or evidence.reviewer != ActorRef(self.binding_ref, 'checker', 'decision-runtime')
                        or evidence.verifier_id != self.verifier_id or evidence.verifier_version != self.verifier_version
                        or evidence.trust_version != caller.credential_epoch or evidence.capability_digest != capability):
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                self._durable_checks(self._run(record.plan), record.plan,
                    record.raw_response_ref, None)
                current.append(CurrentReviewTrust(record.ref, self.verifier_id, caller.credential_epoch))
            yield tuple(current)
